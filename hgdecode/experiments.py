# General modules
import numpy as np
from numpy import arange
from numpy import setdiff1d
from numpy import int as npint
from pickle import load
from os.path import join
from os.path import dirname
from itertools import combinations
from hgdecode.utils import touch_dir
from hgdecode.utils import my_formatter
from hgdecode.utils import print_manager
from sklearn.metrics import confusion_matrix
from multiprocessing import cpu_count

# Deep Learning
from hgdecode import models
from keras import optimizers
from keras.callbacks import CSVLogger
from keras.callbacks import EarlyStopping
from keras.callbacks import ModelCheckpoint
from hgdecode.classes import MetricsTracker
from hgdecode.classes import EEGDataGenerator

# Machine Learning
from hgdecode.classes import FilterBank
from hgdecode.fbcsprlda import BinaryFBCSP
from hgdecode.fbcsprlda import FBCSP
from hgdecode.fbcsprlda import MultiClassWeightedVoting
from braindecode.datautil.iterators import get_balanced_batches


class FBCSPrLDAExperiment(object):
    """
        A Filter Bank Common Spatial Patterns with rLDA
        classification Experiment.

        Parameters
        ----------
        cnt : RawArray
            The continuous train recordings with events in info['events']
        clean_trial_mask : bool array
            Bool array containing information about valid/invalid trials
        name_to_start_codes: dict
            Dictionary mapping class names to marker numbers, e.g.
            {'1 - Correct': [31], '2 - Error': [32]}
        epoch_ival_ms : sequence of 2 floats
            The start and end of the trial in milliseconds with respect to
            the markers.
        min_freq : int or list or tuple
            The minimum frequency/ies of the filterbank/s.
        max_freq : int or list or tuple
            The maximum frequency/ies of the filterbank/s.
        window : int or list or tuple
            Bandwidths of filters in filterbank/s.
        overlap : int or list or tuple
            Overlap frequencies between filters in filterbank/s.
        filt_order : int
            The filter order of the butterworth filter which computes the
            filterbands.
        n_folds : int
            How many folds. Also determines size of the test fold, e.g.
            5 folds imply the test fold has 20% of the original data.
        n_top_bottom_csp_filters : int or None
            Number of top and bottom CSP filters to select from all computed
            filters. Top and bottom refers to CSP filters sorted by their
            eigenvalues. So a value of 3 here will lead to 6(!) filters.
            None means all filters.
        n_selected_filterbands : int or None
            Number of filterbands to select for the filterbank.
            Will be selected by the highest training accuracies.
            None means all filterbands.
        n_selected_features : int or None
            Number of features to select for the filterbank.
            Will be selected by an internal cross validation across feature
            subsets.
            None means all features.
        forward_steps : int
            Number of forward steps to make in the feature selection,
            before the next backward step.
        backward_steps : int
            Number of backward steps to make in the feature selection,
            before the next forward step.
        stop_when_no_improvement: bool
            Whether to stop the feature selection if the internal cross
            validation accuracy could not be improved after an epoch finished
            (epoch=given number of forward and backward steps).
            False implies always run until wanted number of features.
        shuffle: bool
            Whether to shuffle the clean trials before splitting them into
            folds. False implies folds are time-blocks, True implies folds are
            random mixes of trials of the entire file.
    """

    def __init__(self,
                 # signal-related inputs
                 cnt,
                 clean_trial_mask,
                 name_to_start_codes,
                 random_state,
                 name_to_stop_codes=None,
                 epoch_ival_ms=(-500, 4000),
                 cross_subject_object=None,

                 # bank filter-related inputs
                 min_freq=0,
                 max_freq=12,
                 window=6,
                 overlap=3,
                 filt_order=3,

                 # machine learning-related inputs
                 n_folds=5,
                 fold_file=None,
                 n_top_bottom_csp_filters=None,
                 n_selected_filterbands=None,
                 n_selected_features=None,
                 forward_steps=2,
                 backward_steps=1,
                 stop_when_no_improvement=False,
                 shuffle=False,
                 average_trial_covariance=True):
        # signal-related inputs
        self.cnt = cnt
        self.clean_trial_mask = clean_trial_mask
        self.epoch_ival_ms = epoch_ival_ms
        self.name_to_start_codes = name_to_start_codes
        self.name_to_stop_codes = name_to_stop_codes
        self.random_state = random_state
        if cross_subject_object is None:
            self.cross_subject_object = None
            self.cross_subject_computation = False
        else:
            self.cross_subject_object = cross_subject_object
            self.cross_subject_computation = True

        # bank filter-related inputs
        self.min_freq = min_freq
        self.max_freq = max_freq
        self.window = window
        self.overlap = overlap
        self.filt_order = filt_order

        # machine learning-related inputs
        self.n_folds = n_folds
        self.n_top_bottom_csp_filters = n_top_bottom_csp_filters
        self.n_selected_filterbands = n_selected_filterbands
        self.n_selected_features = n_selected_features
        self.forward_steps = forward_steps
        self.backward_steps = backward_steps
        self.stop_when_no_improvement = stop_when_no_improvement
        self.shuffle = shuffle
        self.average_trial_covariance = average_trial_covariance
        if fold_file is None:
            self.fold_file = None
            self.load_fold_from_file = False
        else:
            self.fold_file = fold_file
            self.load_fold_from_file = True

        # other fundamental properties (they will be filled in further
        # computational steps)
        self.filterbank_csp = None
        self.class_pairs = None
        self.folds = None
        self.binary_csp = None
        self.filterbands = None
        self.multi_class = None

        # computing other properties for further computation
        self.n_classes = len(self.name_to_start_codes)
        self.class_pairs = list(combinations(range(self.n_classes), 2))
        self.n_trials = self.clean_trial_mask.astype(npint).sum()

    def create_filter_bank(self):
        self.filterbands = FilterBank(
            min_freq=self.min_freq,
            max_freq=self.max_freq,
            window=self.window,
            overlap=self.overlap
        )

    def create_folds(self):
        if self.cross_subject_computation is True:
            # in case of cross-subject computation
            folds = [
                arange(
                    self.cross_subject_object.subject_indexes[x][0],
                    self.cross_subject_object.subject_indexes[x][1]
                )
                for x in range(len(self.cross_subject_object.subject_indexes))
            ]
            self.n_folds = len(folds)
            self.folds = [
                {
                    'train': setdiff1d(arange(self.n_trials), fold),
                    'test': fold
                }
                for fold in folds
            ]
        elif self.load_fold_from_file is True:
            # in case of pre-batched computation
            self.folds = np.load(self.fold_file)['folds']
        elif self.n_folds == 0:
            self.n_folds = 1

            # creating schirrmeister fold
            all_idxs = np.array(range(len(self.clean_trial_mask)))
            self.folds = [
                {
                    'train': all_idxs[:-160],
                    'test': all_idxs[-160:]
                }
            ]
            self.folds[0]['train'] = self.folds[0]['train'][
                self.clean_trial_mask[:-160]]
            self.folds[0]['test'] = self.folds[0]['test'][
                self.clean_trial_mask[-160:]]
        else:
            # getting pseudo-random folds
            folds = get_balanced_batches(
                n_trials=self.n_trials,
                rng=self.random_state,
                shuffle=self.shuffle,
                n_batches=self.n_folds
            )
            self.folds = [
                {
                    'train': setdiff1d(arange(self.n_trials), fold),
                    'test': fold
                }
                for fold in folds
            ]

    def run(self):
        # printing routine start
        print_manager(
            'INIT TRAINING ROUTINE',
            'double-dashed',
        )

        # creating filter bank
        print_manager('Creating filter bank...')
        self.create_filter_bank()
        print_manager('DONE!!', bottom_return=1)

        # creating folds
        print_manager('Creating folds...')
        self.create_folds()
        print_manager('DONE!!', 'last')

        # running binary FBCSP
        print_manager("RUNNING BINARY FBCSP rLDA",
                      'double-dashed',
                      top_return=1)
        self.binary_csp = BinaryFBCSP(
            cnt=self.cnt,
            clean_trial_mask=self.clean_trial_mask,
            filterbands=self.filterbands,
            filt_order=self.filt_order,
            folds=self.folds,
            class_pairs=self.class_pairs,
            epoch_ival_ms=self.epoch_ival_ms,
            n_filters=self.n_top_bottom_csp_filters,
            marker_def=self.name_to_start_codes,
            name_to_stop_codes=self.name_to_stop_codes,
            average_trial_covariance=self.average_trial_covariance
        )
        self.binary_csp.run()

        # at the very end of the binary CSP experiment, running the real one
        print_manager("RUNNING FBCSP rLDA", 'double-dashed', top_return=1)
        self.filterbank_csp = FBCSP(
            binary_csp=self.binary_csp,
            n_features=self.n_selected_features,
            n_filterbands=self.n_selected_filterbands,
            forward_steps=self.forward_steps,
            backward_steps=self.backward_steps,
            stop_when_no_improvement=self.stop_when_no_improvement
        )
        self.filterbank_csp.run()

        # and finally multiclass
        print_manager("RUNNING MULTICLASS", 'double-dashed', top_return=1)
        self.multi_class = MultiClassWeightedVoting(
            train_labels=self.binary_csp.train_labels_full_fold,
            test_labels=self.binary_csp.test_labels_full_fold,
            train_preds=self.filterbank_csp.train_pred_full_fold,
            test_preds=self.filterbank_csp.test_pred_full_fold,
            class_pairs=self.class_pairs)
        self.multi_class.run()
        print('\n')


class DLExperiment(object):
    """
    # TODO: a description for this class
    """

    def __init__(self,
                 # non-default inputs
                 dataset,
                 model_name,
                 results_dir,
                 subj_results_dir,
                 name_to_start_codes,
                 random_state,
                 fold_idx,

                 # hyperparameters
                 dropout_rate=0.5,
                 learning_rate=0.001,
                 batch_size=128,
                 epochs=10,
                 early_stopping=False,
                 monitor='val_acc',
                 min_delta=0.0001,
                 patience=5,
                 loss='categorical_crossentropy',
                 optimizer='Adam',
                 shuffle='False',
                 crop_sample_size=None,
                 crop_step=None,

                 # other parameters
                 subject_id=1,
                 data_generator=False,
                 workers=cpu_count(),
                 save_model_at_each_epoch=False):
        # non-default inputs
        self.dataset = dataset
        self.model_name = model_name
        self.results_dir = results_dir
        self.subj_results_dir = subj_results_dir
        self.datetime_results_dir = dirname(subj_results_dir)
        self.name_to_start_codes = name_to_start_codes
        self.random_state = random_state
        self.fold_idx = fold_idx

        # hyperparameters
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.epochs = epochs
        self.early_stopping = early_stopping
        self.monitor = monitor
        self.min_delta = min_delta
        self.patience = patience
        self.loss = loss
        self.optimizer = optimizer
        self.shuffle = shuffle
        if crop_sample_size is None:
            self.crop_sample_size = self.n_samples
            self.crop_step = 1
        else:
            self.crop_sample_size = crop_sample_size
            self.crop_step = crop_step

        # other parameters
        self.subject_id = subject_id
        self.data_generator = data_generator
        self.workers = workers
        self.save_model_at_each_epoch = save_model_at_each_epoch
        self.metrics_tracker = None

        # managing paths
        self.dl_results_dir = None
        self.model_results_dir = None
        self.fold_results_dir = None
        self.statistics_dir = None
        self.figures_dir = None
        self.tables_dir = None
        self.model_picture_path = None
        self.model_report_path = None
        self.train_report_path = None
        self.h5_models_dir = None
        self.h5_model_path = None
        self.log_path = None
        self.fold_stats_path = None
        self.paths_manager()

        # importing model
        print_manager('IMPORTING & COMPILING MODEL', 'double-dashed')
        model_inputs_str = ', '.join([str(i) for i in [self.n_classes,
                                                       self.n_channels,
                                                       self.crop_sample_size,
                                                       self.dropout_rate]])
        expression = 'models.' + self.model_name + '(' + model_inputs_str + ')'
        self.model = eval(expression)

        # creating optimizer instance
        if self.optimizer is 'Adam':
            opt = optimizers.Adam(lr=self.learning_rate)
        else:
            opt = optimizers.Adam(lr=self.learning_rate)

        # compiling model
        self.model.compile(loss=self.loss,
                           optimizer=opt,
                           metrics=['accuracy'])
        self.model.summary()
        print_manager('DONE!!', print_style='last', bottom_return=1)

    def __repr__(self):
        return '<DLExperiment with model: {:s}>'.format(self.model_name)

    def __str__(self):
        return '<DLExperiment with model: {:s}>'.format(self.model_name)

    def __len__(self):
        return len(self.dataset)

    @property
    def shape(self):
        return self.dataset.shape

    @property
    def train_frac(self):
        return self.dataset.train_frac

    @property
    def valid_frac(self):
        return self.dataset.valid_frac

    @property
    def test_frac(self):
        return self.dataset.test_frac

    @property
    def n_classes(self):
        return len(self.name_to_start_codes)

    @property
    def n_channels(self):
        return self.dataset.n_channels

    @property
    def n_samples(self):
        return self.dataset.n_samples

    def paths_manager(self):
        # results_dir is: .../results/hgdecode
        # dl_results_dir is: .../results/hgdecode/dl
        dl_results_dir = join(self.results_dir, 'dl')

        # model_results_dir is: .../results/hgdecode/dl/model_name
        model_results_dir = join(dl_results_dir, self.model_name)

        # fold_results_dir is .../results/dataset/dl/model/datetime/subj/fold
        fold_str = str(self.fold_idx + 1)
        if len(fold_str) == 1:
            fold_str = '0' + fold_str
        fold_str = 'fold' + fold_str
        fold_results_dir = join(self.subj_results_dir, fold_str)

        # setting on object self
        self.dl_results_dir = dl_results_dir
        self.model_results_dir = model_results_dir
        self.fold_results_dir = fold_results_dir

        # touching only the last directory will be create also the other ones
        touch_dir(self.fold_results_dir)

        # statistics_dir is: .../results/hgdecode/dl/model/datetime/statistics
        statistics_dir = join(self.datetime_results_dir, 'statistics')

        # figures_dir is: .../results/hgdecode/dl/model/dt/stat/figures/subject
        figures_dir = join(statistics_dir, 'figures',
                           my_formatter(self.subject_id, 'subj'))

        # tables_dir is: .../results/hgdecode/dl/model/datetime/stat/tables
        tables_dir = join(statistics_dir, 'tables')

        # setting on object self
        self.statistics_dir = statistics_dir
        self.figures_dir = figures_dir
        self.tables_dir = tables_dir
        touch_dir(figures_dir)
        touch_dir(tables_dir)

        # files in datetime_results_dir
        self.model_report_path = join(self.datetime_results_dir,
                                      'model_report.txt')
        self.model_picture_path = join(self.datetime_results_dir,
                                       'model_picture.png')

        # files in subj_results_dir
        self.log_path = join(self.subj_results_dir, 'log.bin')

        # files in fold_results_dir
        self.train_report_path = join(self.fold_results_dir,
                                      'train_report.csv')
        self.fold_stats_path = join(self.fold_results_dir, 'fold_stats.pickle')

        # if the user want to save the model on each epoch...
        if self.save_model_at_each_epoch:
            # ...creating models directory and an iterable name, else...
            self.h5_models_dir = join(self.fold_results_dir, 'h5_models')
            touch_dir(self.h5_models_dir)
            self.h5_model_path = join(self.h5_models_dir, 'net{epoch:02d}.h5')
        else:
            # ...pointing to the same results directory
            self.h5_model_path = join(self.fold_results_dir,
                                      'net_best_val_loss.h5')

    def train(self):
        # saving a model picture
        # TODO: model_pic.png saving routine

        # saving a model report
        with open(self.model_report_path, 'w') as mr:
            self.model.summary(print_fn=lambda x: mr.write(x + '\n'))

        # pre-allocating callbacks list
        callbacks = []

        # saving a train report
        csv = CSVLogger(self.train_report_path)
        callbacks.append(csv)

        # saving model each epoch
        if self.save_model_at_each_epoch:
            mcp = ModelCheckpoint(self.h5_model_path)
            callbacks.append(mcp)
        # else:
        # mcp = ModelCheckpoint(self.h5_model_path,
        #                      monitor='val_loss',
        #                      save_best_only=True)
        # callbacks.append(mcp)

        # if early_stopping is True...
        if self.early_stopping is True:
            # putting epochs to a very large number
            epochs = 1000

            # creating early stopping callback
            esc = EarlyStopping(monitor=self.monitor,
                                min_delta=self.min_delta,
                                patience=self.patience,
                                verbose=1)
            callbacks.append(esc)
        else:
            # getting user defined epochs value
            epochs = self.epochs

        # using fit_generator if a data generator is required
        if self.data_generator is True:
            training_generator = EEGDataGenerator(self.dataset.X_train,
                                                  self.dataset.y_train,
                                                  self.batch_size,
                                                  self.n_classes,
                                                  self.crop_sample_size,
                                                  self.crop_step)
            validation_generator = EEGDataGenerator(self.dataset.X_train,
                                                    self.dataset.y_train,
                                                    self.batch_size,
                                                    self.n_classes,
                                                    self.crop_sample_size,
                                                    self.crop_step)

            # training!
            print_manager(
                'RUNNING TRAINING ON FOLD {}'.format(self.fold_idx + 1),
                'double-dashed'
            )
            self.model.fit_generator(generator=training_generator,
                                     validation_data=validation_generator,
                                     use_multiprocessing=True,
                                     workers=self.workers,
                                     epochs=epochs,
                                     verbose=1,
                                     callbacks=callbacks)
        else:
            # creating crops
            self.dataset.make_crops(self.crop_sample_size, self.crop_step)

            # forcing the x examples to have 4 dimensions
            self.dataset.add_axis()

            # parsing y to categorical
            self.dataset.to_categorical()

            # TODO: MetricsTracker for Data Generation routine
            # creating a MetricsTracker instance
            if self.metrics_tracker is None:
                callbacks.append(
                    MetricsTracker(
                        dataset=self.dataset,
                        epochs=self.epochs,
                        n_classes=self.n_classes,
                        batch_size=self.batch_size,
                        h5_model_path=self.h5_model_path,
                        fold_stats_path=self.fold_stats_path
                    )
                )
            else:
                callbacks.append(self.metrics_tracker)

            # training!
            print_manager(
                'RUNNING TRAINING ON FOLD {}'.format(self.fold_idx + 1),
                'double-dashed'
            )
            self.model.fit(x=self.dataset.X_train,
                           y=self.dataset.y_train,
                           validation_data=(self.dataset.X_valid,
                                            self.dataset.y_valid),
                           batch_size=self.batch_size,
                           epochs=epochs,
                           verbose=1,
                           callbacks=callbacks,
                           shuffle=self.shuffle)
        # TODO: if validation_frac is 0 or None, not to split train and test
        #  to train the epochs hyperparameter.

    def test(self):
        # TODO: evaluate_generator if data_generator is True
        # loading best net
        self.model.load_weights(self.h5_model_path)

        # computing loss and other metrics
        score = self.model.evaluate(
            self.dataset.X_test,
            self.dataset.y_test,
            verbose=1
        )

        print('Test loss:', score[0])
        print('Test  acc:', score[1])

        # making predictions on X_test with final model and getting also
        # y_test from memory; parsing both back from categorical
        y_pred = self.model.predict(self.dataset.X_test).argmax(axis=1)
        if self.data_generator is True:
            y_test = self.dataset.y_test
        else:
            y_test = self.dataset.y_test.argmax(axis=1)

        # computing confusion matrix
        conf_mtx = confusion_matrix(y_true=y_test, y_pred=y_pred)
        print("Confusion matrix:\n", conf_mtx)

    def prepare_for_transfer_learning(self,
                                      cross_subj_dir_path,
                                      subject_id,
                                      train_anyway=False):
        # printing the start
        print_manager('PREPARING FOR TRANSFER LEARNING', 'double-dashed')

        # getting this subject cross-subject dir
        cross_subj_this_subj_dir_path = join(cross_subj_dir_path,
                                             'subj_cross',
                                             my_formatter(subject_id, 'fold'))

        # loading
        self.model.load_weights(join(cross_subj_this_subj_dir_path,
                                     'net_best_val_loss.h5'))

        if train_anyway is False:
            # pre-saving this net as best one
            self.model.save(self.h5_model_path)

            # creating metrics tracker instance
            self.metrics_tracker = MetricsTracker(
                dataset=self.dataset,
                epochs=self.epochs,
                n_classes=self.n_classes,
                batch_size=self.batch_size,
                h5_model_path=self.h5_model_path,
                fold_stats_path=self.fold_stats_path
            )

            # loading cross-subject info
            with open(join(cross_subj_this_subj_dir_path,
                           'fold_stats.pickle'), 'rb') as f:
                results = load(f)

            # forcing best net to be the 0 one
            self.metrics_tracker.best['loss'] = results['test']['loss']
            self.metrics_tracker.best['acc'] = results['test']['acc']
            self.metrics_tracker.best['idx'] = 0

        # printing the end
        print_manager('DONE!!', print_style='last', bottom_return=1)

    def freeze_layers(self, layers_to_freeze):
        print_manager('FREEZING LAYERS', 'double-dashed')
        if layers_to_freeze == 0:
            print('NOTHING TO FREEZE!!')
        else:
            print("I'm gonna gonna freeze {} layers.".format(layers_to_freeze))

            # freezing layers
            frozen = 0
            if layers_to_freeze > 0:
                idx = 0
                step = 1
            else:
                idx = -1
                step = -1
                layers_to_freeze = - layers_to_freeze
            while frozen < layers_to_freeze:
                layer = self.model.layers[idx]
                if layer.name[:4] == 'conv' or layer.name[:5] == 'dense':
                    layer.trainable = False
                    frozen += 1
                idx += step

            # creating optimizer instance
            if self.optimizer is 'Adam':
                opt = optimizers.Adam(lr=self.learning_rate)
            else:
                opt = optimizers.Adam(lr=self.learning_rate)

            # compiling model
            self.model.compile(loss=self.loss,
                               optimizer=opt,
                               metrics=['accuracy'])

            # printing model information
            self.model.summary()
        print_manager('DONE!!', print_style='last', bottom_return=1)
