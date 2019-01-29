import os
from csv import reader
from numpy import array
from scipy.stats import ttest_rel

# defining path parameters (you can change stuff here)
results_dir = '/Users/davidemiani/OneDrive - Alma Mater Studiorum ' \
              'Università di Bologna/TesiMagistrale_DavideMiani/' \
              'results/hgdecode'
ml_algorithm = 'FBCSP_rLDA'
dl_model = 'DeepConvNet'
ml_datetime = ['2019-01-26_18-54-54',
               '2019-01-26_20-42-32',
               '2019-01-26_23-46-51']
dl_datetime = ['2019-01-27_08-52-08',
               '2019-01-27_15-07-56',
               '2019-01-28_02-36-11']

for ml_dt, dl_dt in zip(ml_datetime, dl_datetime):
    # loading ml accuracies
    ml_acc_csv_path = os.path.join(results_dir, 'ml', ml_algorithm, ml_dt,
                                   'statistics', 'tables', 'acc.csv')
    with open(ml_acc_csv_path) as f:
        ml_csv = list(reader(f))
    ml_accs = array([float(ml_csv[x][-2]) for x in range(1, len(ml_csv))])

    # loading dl accuracies
    dl_acc_csv_path = os.path.join(results_dir, 'dl', dl_model, dl_dt,
                                   'statistics', 'tables', 'acc.csv')
    with open(dl_acc_csv_path) as f:
        dl_csv = list(reader(f))
    dl_accs = array([float(dl_csv[x][-2]) for x in range(1, len(dl_csv))])

    # running t-test
    statistic, p_value = ttest_rel(ml_accs, dl_accs)
    print(p_value)
