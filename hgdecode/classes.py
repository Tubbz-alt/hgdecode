import sys
import time
from numpy import ceil
from numpy import log10
from numpy import floor
from numpy import zeros
from numpy import arange
from numpy import unique
from numpy import repeat
from numpy import append
from numpy import random
from numpy import newaxis
from numpy import concatenate
from collections import OrderedDict
from keras.utils import Sequence
from keras.utils import to_categorical
from keras.callbacks import Callback
from hgdecode.utils import print_manager
from sklearn.metrics import confusion_matrix


class FilterBank(object):
    """Create filter bank for FBCSP algorithm.

    Compute frequencies for the filter bank of a specific FBCSP
    experiment.

    Parameters
    ----------
    min_freq : int or list of int
        filter banks min frequency
    max_freq : int or list of int
        filter banks max frequency
    window : int or list of int
        bandwidth of each filter
    overlap : int or list of int

    Returns
    -------
    filter_bank : instance of FilterBank object

    Author info
    -----------
    CREDITS:     Davide Miani (nov 2018)
    LAST REVIEW: Davide Miani (nov 2018)
    MAIL TO:     davide.miani2@gmail.com
    Visit my GitHub to find more:
    https://github.com/davidemiani
    """

    def __init__(self,
                 min_freq=0,
                 max_freq=12,
                 window=6,
                 overlap=3):
        # TODO: validate inputs

        # if multi-input, recalling itself recursively
        if type(min_freq) is list:
            bank = FilterBank(
                min_freq=min_freq[0],
                max_freq=max_freq[0],
                window=window[0],
                overlap=overlap[0]
            )
            for idx in range(1, len(min_freq)):
                bank = FilterBank.merge_banks(
                    bank,
                    FilterBank(min_freq=min_freq[idx],
                               max_freq=max_freq[idx],
                               window=window[idx],
                               overlap=overlap[idx])
                )
            # copying bank as final object
            self.min_freq = min_freq
            self.max_freq = bank.max_freq
            self.window = bank.window
            self.overlap = bank.overlap
            self.bank = bank.bank
        else:
            # copying inputs as properties with same names and values
            self.min_freq = min_freq
            self.max_freq = max_freq
            self.window = window
            self.overlap = overlap

            # computing filter bank
            self.bank = self.compute_bank()

        # fixing 0 frequency (not permitted from scipy.signal.butter)
        if self.bank[0, 0] == 0:
            self.bank[0, 0] = 0.1

    def __repr__(self):
        return repr(self.bank)

    def __str__(self):
        return str(self.bank)

    def __len__(self):
        return len(self.bank)

    def __iter__(self):
        return self.bank.__iter__()

    def __getitem__(self, item):
        return self.bank[item]

    @property
    def shape(self):
        return self.bank.shape

    @staticmethod
    def merge_banks(bank1, bank2):
        bank = bank1
        bank.min_freq = [bank1.min_freq, bank2.min_freq]
        bank.max_freq = [bank1.max_freq, bank2.max_freq]
        bank.window = [bank1.window, bank2.window]
        bank.overlap = [bank1.overlap, bank2.overlap]
        bank.bank = concatenate([bank1.bank, bank2.bank])
        return bank

    def compute_bank(self):
        # computing filter bank length for pre-allocation
        bank_length = int(floor((self.max_freq - self.min_freq) /
                                (self.window - self.overlap)) - 1)

        # pre-allocating numpy array
        bank = zeros((bank_length, 2))

        # determining first init and stop
        init = self.min_freq
        stop = init + self.window

        # cycling on bank to allocate
        for idx in range(bank_length):
            # allocating
            bank[idx, 0] = init
            bank[idx, 1] = stop

            # updating init and stop
            init = stop - self.overlap
            stop = init + self.window

        return bank


class EEGDataset(object):
    """
    # TODO: documentation for this class
    """

    def __init__(self,
                 epo_train_x,
                 epo_train_y,
                 epo_valid_x,
                 epo_valid_y,
                 epo_test_x,
                 epo_test_y):
        assert len(epo_train_x) == len(epo_train_y)
        assert len(epo_valid_x) == len(epo_valid_y)
        assert len(epo_test_x) == len(epo_test_y)
        self.X_train = epo_train_x
        self.y_train = epo_train_y
        self.X_valid = epo_valid_x
        self.y_valid = epo_valid_y
        self.X_test = epo_test_x
        self.y_test = epo_test_y

    def __repr__(self):
        return '<EEGDataset with train:{:d}, valid:{:d}, test:{:d}>'.format(
            len(self.y_train), len(self.y_valid), len(self.y_test)
        )

    def __str__(self):
        return '<EEGDataset with train:{:d}, valid:{:d}, test:{:d}>'.format(
            len(self.y_train), len(self.y_valid), len(self.y_test)
        )

    def __len__(self):
        return len(self.y_train) + len(self.y_valid) + len(self.y_test)

    @property
    def shape(self):
        return self.X_train.shape[1:]

    @property
    def train_frac(self):
        return len(self.y_train) / len(self)

    @property
    def valid_frac(self):
        return len(self.y_valid) / len(self)

    @property
    def test_frac(self):
        return len(self.y_test) / len(self)

    @property
    def n_channels(self):
        return self.shape[0]

    @property
    def n_samples(self):
        return self.shape[1]

    @staticmethod
    def from_epo_to_dataset(epo, train_len, test_len, validation_frac=0.2):
        # computing number of trails for each valid, train & test
        tot_len = len(epo.y)
        valid_len = int(floor(train_len * validation_frac))
        train_len = train_len - valid_len

        # computing indexes
        indexes = arange(tot_len)
        train_indexes = indexes[0:train_len]
        valid_indexes = indexes[train_len:(train_len + valid_len)]
        test_indexes = indexes[-test_len:]

        # cutting epo into train, valid & test
        epo_train_x = epo.X[train_indexes, ...]
        epo_train_y = epo.y[train_indexes, ...]
        epo_valid_x = epo.X[valid_indexes, ...]
        epo_valid_y = epo.y[valid_indexes, ...]
        epo_test_x = epo.X[test_indexes, ...]
        epo_test_y = epo.y[test_indexes, ...]

        return EEGDataset(epo_train_x,
                          epo_train_y,
                          epo_valid_x,
                          epo_valid_y,
                          epo_test_x,
                          epo_test_y)

    def make_crops(self, crop_sample_size=None, crop_step=None):
        # TODO: validating inputs
        if crop_sample_size is not None:
            # printing
            print_manager('CROPPING ROUTINE', 'double-dashed')

            # cropping train
            print_manager('Cropping train...')
            self.X_train, self.y_train = self.crop_X_y(self.X_train,
                                                       self.y_train,
                                                       crop_sample_size,
                                                       crop_step)
            print_manager('DONE!!', bottom_return=1)

            # cropping valid
            print_manager('Cropping validation...')
            self.X_valid, self.y_valid = self.crop_X_y(self.X_valid,
                                                       self.y_valid,
                                                       crop_sample_size,
                                                       crop_step)
            print_manager('DONE!!', bottom_return=1)

            # cropping test
            print_manager('Cropping test...')
            self.X_test, self.y_test = self.crop_X_y(self.X_test,
                                                     self.y_test,
                                                     crop_sample_size,
                                                     crop_step)
            print_manager('DONE!!', 'last', bottom_return=1)

    @staticmethod
    def crop_X_y(X, y, crop_sample_size, crop_step):
        # getting shapes
        d = X.shape[0]
        h = X.shape[1]
        w = X.shape[2]

        # determining how many crops
        n_crops = int(ceil(
            (w - crop_sample_size + 1) / crop_step
        ))
        new_d = n_crops * d
        new_h = h
        new_w = crop_sample_size

        # pre-allocating
        new_X = zeros((new_d, new_h, new_w))
        new_y = zeros(new_d)

        # filling pre-allocated arrays
        init = 0
        stop = init + n_crops
        for i in range(d):
            new_X[init:stop, ...] = EEGDataset.crop_X(X[i, ...],
                                                      n_crops,
                                                      crop_sample_size,
                                                      crop_step)
            new_y[init:stop, ...] = EEGDataset.crop_y(y[i], n_crops)

            # updating init & stop
            init = init + n_crops
            stop = stop + n_crops

        # returning new arrays
        return new_X, new_y

    @staticmethod
    def crop_X(X, n_crops, crop_sample_size, crop_step):
        # pre-allocating new_x
        new_X = zeros((n_crops, X.shape[0], crop_sample_size))

        # handling init & stop in X array
        init = 0
        stop = crop_sample_size

        # cycling on new_x depth
        for i in range(n_crops):
            new_X[i, ...] = X[:, init:stop]
            init = init + crop_step
            stop = stop + crop_step

        # returning new_x
        return new_X

    @staticmethod
    def crop_y(y, n_crops):
        return repeat(y, n_crops)

    def add_axis(self):
        # TODO: channel first or last
        self.X_train = self.X_train[:, newaxis, ...]
        self.X_valid = self.X_valid[:, newaxis, ...]
        self.X_test = self.X_test[:, newaxis, ...]

    def to_categorical(self, n_classes=None):
        if n_classes is None:
            n_classes = len(unique(self.y_train))
        self.y_train = to_categorical(self.y_train, n_classes)
        self.y_valid = to_categorical(self.y_valid, n_classes)
        self.y_test = to_categorical(self.y_test, n_classes)


class EEGDataGenerator(Sequence):
    """
    # TODO: class description
    """

    def __init__(self,
                 # data
                 X,
                 y,
                 # main dimensions
                 batch_size=512,
                 n_classes=None,
                 # crop dimensions
                 crop_sample_size=512,
                 crop_step=1,
                 # others
                 shuffle=True):
        """Initialization"""
        # data
        self.X = X
        self.y = y

        # main dimensions
        self.batch_size = batch_size
        self.n_trials = X.shape[0]
        self.n_channels = X.shape[1]
        self.n_samples = X.shape[2]
        if n_classes is None:
            self.n_classes = len(unique(y))
        else:
            self.n_classes = n_classes

        # crop dimensions
        self.crop_sample_size = crop_sample_size
        self.crop_step = crop_step
        self.n_crops_for_trial = int(ceil(
            (self.n_samples - crop_sample_size + 1) / crop_step
        ))
        self.n_crops = self.n_crops_for_trial * self.n_trials

        # others
        self.shuffle = shuffle
        self.current_batch = None

        # allocating indexes to None, than updating using on_epoch_end()
        self.indexes = None  # pointer to trials
        self.next_to_unpack = None  # pointer to indexes
        self.on_epoch_end()

        # pre-allocating crop stack & unpacking the first trial indexed
        self.crop_stack_X = None
        self.crop_stack_y = None
        self.unpack_trial()

    def __len__(self):
        """Denotes the number of batches per epoch"""
        return int(floor(self.n_crops / self.batch_size))

    def __getitem__(self, index):
        """Generate one batch of data"""
        # registering current batch
        self.current_batch = index

        # Generate data
        X, y = self.__data_generation()

        return X, y

    def on_epoch_end(self):
        """
        Updates indexes after each epoch; the indexes order will tell the
        trainer what is the next trial order to unpack
        """
        # TODO: set seed rng
        self.indexes = arange(self.n_trials)
        if self.shuffle is True:
            random.shuffle(self.indexes)
        self.next_to_unpack = 0

    def __data_generation(self):
        """Generates data containing batch_size samples"""
        while len(self.crop_stack_y) < self.batch_size:
            self.unpack_trial()

        # getting first batch_size elements from stacks
        start = 0
        stop = self.batch_size
        indexes = arange(start=start, stop=stop)
        X = self.crop_stack_X[indexes, ...]
        y = self.crop_stack_y[indexes]

        # popping stack
        start = self.batch_size
        stop = len(self.crop_stack_y)
        indexes = arange(start=start, stop=stop)
        self.crop_stack_X = self.crop_stack_X[indexes, ...]
        self.crop_stack_y = self.crop_stack_y[indexes]

        # forcing the x examples to have 4 dimensions
        X = X[:, newaxis, ...]

        # parsing y to categorical
        y = to_categorical(y, num_classes=self.n_classes)

        # returning data generated
        return X, y

    def unpack_trial(self):
        # first unpack has to (re)create the stack
        if self.next_to_unpack is 0:
            # unpacking first X trial
            self.crop_stack_X = EEGDataset.crop_X(
                self.X[self.indexes[self.next_to_unpack], ...],
                self.n_crops_for_trial, self.crop_sample_size, self.crop_step
            )

            # unpacking first y trial
            self.crop_stack_y = EEGDataset.crop_y(
                self.y[self.indexes[self.next_to_unpack]],
                self.n_crops_for_trial
            )
        else:
            # appending X
            self.crop_stack_X = append(
                self.crop_stack_X,
                EEGDataset.crop_X(
                    self.X[self.indexes[self.next_to_unpack], ...],
                    self.n_crops_for_trial,
                    self.crop_sample_size,
                    self.crop_step
                ),
                axis=0
            )

            # appending y
            self.crop_stack_y = append(
                self.crop_stack_y,
                EEGDataset.crop_y(
                    self.y[self.indexes[self.next_to_unpack]],
                    self.n_crops_for_trial
                )
            )

        # updating next_to_unpack
        self.next_to_unpack += 1


# TODO: MetricsTracker class with: __init__(), on_epoch_end(), and
#  on_train_end(); the first one initializes the class, the second one
#  evaluate the model and print a report, the third one plots train,
#  validation and test curve and saves it
class MetricsTracker(Callback):
    def __init__(self,
                 dataset,
                 epochs,
                 n_classes,
                 batch_size,
                 plot_paths_dict):
        # allocating inputs as properties
        self.dataset = dataset
        self.epochs = epochs
        self.n_classes = n_classes
        self.batch_size = batch_size
        self.plot_paths_dict = plot_paths_dict

        # pre-allocating train, valid and test dicts with loss and conf_mtx
        self.train = {'loss': zeros(epochs),
                      'acc': zeros(epochs)}
        self.valid = {'loss': zeros(epochs),
                      'acc': zeros(epochs)}
        self.test = {'loss': zeros(epochs),
                     'acc': zeros(epochs)}

        # calling the super class constructor
        Callback.__init__(self)

    def on_epoch_end(self, epoch, logs=None):
        print('Computing statistics on this epoch:')
        epoch_string_length = len(str(self.epochs)) * 2 + 1
        progress_bar_length = 30 + epoch_string_length + 1
        progress_bar = ProgressBar(target=5, width=progress_bar_length)
        progress_bar.update(current=0, message='evaluating test')

        # loss for training and validation is stored in logs dict
        self.train['loss'][epoch] = logs['loss']
        self.valid['loss'][epoch] = logs['val_loss']

        # computing loss and other metrics for test
        score = self.model.evaluate(
            x=self.dataset.X_test,
            y=self.dataset.y_test,
            batch_size=self.batch_size,
            verbose=0
        )
        if score is list:
            self.test['loss'][epoch] = score[0]
        else:
            self.test['loss'][epoch] = score

        # predicting train
        progress_bar.update(current=1, message='predicting train')
        y_true_train = self.dataset.y_train.argmax(axis=1)
        y_pred_train = self.model.predict(x=self.dataset.X_train,
                                          batch_size=self.batch_size,
                                          verbose=0).argmax(axis=1)

        # predicting valid
        progress_bar.update(current=2, message='predicting valid')
        y_true_valid = self.dataset.y_valid.argmax(axis=1)
        y_pred_valid = self.model.predict(x=self.dataset.X_valid,
                                          batch_size=self.batch_size,
                                          verbose=0).argmax(axis=1)

        # predicting test
        progress_bar.update(current=3, message='predicting test')
        y_true_test = self.dataset.y_test.argmax(axis=1)
        y_pred_test = self.model.predict(x=self.dataset.X_test,
                                         batch_size=self.batch_size,
                                         verbose=0).argmax(axis=1)

        # from prediction, computing confusion matrix
        progress_bar.update(current=4, message='computing conf mtx')
        self.train['conf_mtx'][epoch, ...] = confusion_matrix(
            y_pred=y_pred_train, y_true=y_true_train
        )
        self.valid['conf_mtx'][epoch, ...] = confusion_matrix(
            y_pred=y_pred_valid, y_true=y_true_valid
        )
        self.test['conf_mtx'][epoch, ...] = confusion_matrix(
            y_pred=y_pred_test, y_true=y_true_test
        )

        # updating prog bar for the end
        progress_bar.update(current=5, message='statistics completed')
        print('train loss: {0:.4f}'.format(self.train['loss'][epoch]),
              'valid loss: {0:.4f}'.format(self.valid['loss'][epoch]),
              'test loss: {0:.4f}'.format(self.test['loss'][epoch]))

    def on_train_end(self, logs=None):
        pass

    @staticmethod
    def get_loss_from_score(score):
        if score is list:
            return score[0]
        else:
            return score


class ProgressBar(object):
    """Displays a progress bar.
    # Arguments
        target: Total number of steps expected, None if unknown.
        width: Progress bar width on screen.
        verbose: Verbosity mode, 0 (silent), 1 (verbose), 2 (semi-verbose)
        stateful_metrics: Iterable of string names of metrics that
            should *not* be averaged over time. Metrics in this list
            will be displayed as-is. All others will be averaged
            by the progress bar before display.
        interval: Minimum visual progress update interval (in seconds).
    """

    def __init__(self, target, width=30, interval=0.05):
        self.target = target
        self.width = width
        self.interval = interval
        self._dynamic_display = ((hasattr(sys.stdout, 'isatty') and
                                  sys.stdout.isatty()) or
                                 'ipykernel' in sys.modules)
        self._total_width = 0
        self._seen_so_far = 0
        self._values = OrderedDict()
        self._start = time.time()
        self._last_update = 0

    def update(self, current, message=''):
        """Updates the progress bar.
        # Arguments
            current: Index of current step.
            message: Message to display at the end of the bar.
        """
        now = time.time()
        info = ' - %.0fs' % (now - self._start)

        if (now - self._last_update < self.interval and
                self.target is not None and current < self.target):
            return

        prev_total_width = self._total_width
        if self._dynamic_display:
            sys.stdout.write('\b' * prev_total_width)
            sys.stdout.write('\r')
        else:
            sys.stdout.write('\n')

        if self.target is not None:
            numdigits = int(floor(log10(self.target))) + 1
            barstr = '%%%dd/%d [' % (numdigits, self.target)
            bar = barstr % current
            prog = float(current) / self.target
            prog_width = int(self.width * prog)
            if prog_width > 0:
                bar += ('=' * (prog_width - 1))
                if current < self.target:
                    bar += '>'
                else:
                    bar += '='
            bar += ('.' * (self.width - prog_width))
            bar += ']'
        else:
            bar = '%7d/Unknown' % current

        self._total_width = len(bar)
        sys.stdout.write(bar)

        if current:
            time_per_unit = (now - self._start) / current
        else:
            time_per_unit = 0
        if self.target is not None and current < self.target:
            eta = time_per_unit * (self.target - current)
            if eta > 3600:
                eta_format = ('%d:%02d:%02d' %
                              (eta // 3600, (eta % 3600) // 60, eta % 60))
            elif eta > 60:
                eta_format = '%d:%02d' % (eta // 60, eta % 60)
            else:
                eta_format = '%ds' % eta

            info = ' - ETA: %s' % eta_format
        else:
            if time_per_unit >= 1:
                info += ' %.0fs/step' % time_per_unit
            elif time_per_unit >= 1e-3:
                info += ' %.0fms/step' % (time_per_unit * 1e3)
            else:
                info += ' %.0fus/step' % (time_per_unit * 1e6)

        if message is not '':
            info += ' - ' + message

        self._total_width += len(info)
        if prev_total_width > self._total_width:
            info += (' ' * (prev_total_width - self._total_width))

        if self.target is not None and current >= self.target:
            info += '\n'

        sys.stdout.write(info)
        sys.stdout.flush()

        self._last_update = now
