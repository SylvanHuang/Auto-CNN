import argparse
import hpbandster.core.result as hpres
from main import train, train_test
import torch
import logging
import json
import time
import numpy as np
from matplotlib import pyplot as plt

logging.basicConfig(level=logging.INFO)

def unified_config(parent, config):
    '''
    Function to concatenate configurations reveived from two different BOHB setups
    Used for the Transfer Config setup wherein a parent configuration provides the Neural Architecture params and
    other training hyperparameters. The config contains a subset of such parameters that are re-configured.
    :param parent: Original configuration
    :param config: Updating a subset of the original configuration
    :return: Updated configuration
    '''
    parent['batch_size'] = config['batch_size']
    for i in range(parent['n_conv_layer']):
        parent['channel_'+str(i+1)] = config['channel_'+str(i+1)]
    for i in range(parent['n_fc_layer']-1):
        del(parent['fc_'+str(i+1)])
    parent['n_fc_layer'] = config['n_fc_layer']
    for i in range(config['n_fc_layer']-1):
        parent['fc_'+str(i+1)] = config['fc_nodes']
    return parent


def plot_learning_curve(train, test, out_dir, name):
    '''
    Plots the learning curve - loss over epochs
    :param train: The set of training losses over epochs
    :param test: The set of test losses over epochs
    :param out_dir: Directory to save the plots
    :param name: Name appended to the plot saved 'learning_curve_[name].png'
    :return: void
    '''
    plt.plot(range(1, len(train)+1), train, color='red', label='Training Loss')
    plt.plot(range(1, len(test)+1), test, color='green', label='Test Set Loss')
    plt.title('Learning Curve')
    plt.xlabel('Epochs')
    plt.ylabel('Loss')
    plt.xticks(range(1, len(train)+1))
    plt.xlim(1,len(train))
    plt.legend()
    plt.grid(which='major', linestyle=':') #, axis='y')
    plt.grid(which='minor', linestyle='--', axis='y')
    plt.savefig(out_dir+'learning_curve_'+str(name)+'.png',dpi=300)


def plot_confusion_matrix(cm, classes, out_dir,name, dataset='KMNIST', cmap=plt.cm.Blues,
                          normalize=False, title='Confusion matrix'):
    '''
    This function prints and plots the confusion matrix.
    Normalization can be applied by setting `normalize=True`.
    :param cm: Confusion Matrix result from sklearn
    :param classes: Names of the classes
    :param out_dir: Directory to save the plot
    :param name: Name appended to the plot saved 'confusion_matrix_[name].png'
    :param dataset: Needed to mark low frequency classes for K49
    :param cmap: Matplotlib color map to decide color palette for the plot
    :param normalize: True to plot confusion matrix with the values normalized for true class distribution
    :param title: Title for the plot
    :return: void
    '''
    if normalize:
        cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
        print("Normalized confusion matrix")
    else:
        print('Confusion matrix, without normalization')
    print(cm)
    plt.clf()
    plt.imshow(cm, interpolation='nearest', cmap=cmap)
    plt.title(title)
    plt.colorbar()
    tick_marks = np.arange(len(classes))
    plt.xticks(tick_marks, classes, fontsize=4, rotation=90)
    if dataset=='K49':
        plt.axvspan(2.5, 3.5, color='red', alpha=0.1, label='<1000 training examples')
        plt.axvspan(43.5, 45.5, color='red', alpha=0.1)
        plt.axvspan(31.5, 32.5, color='orange', alpha=0.1, label='<1000 training examples')
        plt.axvspan(35.5, 36.5, color='orange', alpha=0.1)
        # plt.legend(loc='bottom left')
    plt.yticks(tick_marks, classes, fontsize=4)
    fmt = '.2f' if normalize else 'd'
    thresh = cm.max() / 2.
    # Disabled for legibility on the large K49 [49x49] matrix
    # Marks the cells with actual values
    # for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
    #     plt.text(j, i, format(cm[i, j], fmt),
    #              horizontalalignment="center",
    #              color="white" if cm[i, j] > thresh else "black")
    plt.ylabel('True label')
    plt.xlabel('Predicted label')
    plt.tight_layout()
    plt.savefig(out_dir+'confusion_matrix_'+str(name)+'.png',dpi=300)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-c', "--config_dir", dest="config_dir", type=str,
                        help='Directory that has config.json and results.json from a BOHB run')
    parser.add_argument('-d', "--dataset", dest="dataset", type=str, default='KMNIST', choices=['KMNIST', 'K49'],
                        help='Dataset to evaluate the incumbent configuration on')
    parser.add_argument('-e', "--epochs", dest="epochs", type=int, default=1, choices=list(range(1,21)),
                        help='Number of epochs for training')
    parser.add_argument('-t', "--transfer", dest="transfer", type=bool, default=False, choices=[True, False],
                        help='Set to True if evaluating a Transfer Config BOHB output')
    parser.add_argument('-a', "--data_augmentation", dest="data_augmentation", type=str, default=None,
                        help='Set to True if Training data needs to be augmented')
    parser.add_argument('-v', '--verbose', default='INFO', choices=['INFO', 'DEBUG'], help='verbosity')
    args, kwargs = parser.parse_known_args()
    log_lvl = logging.INFO if args.verbose == 'INFO' else logging.DEBUG
    logging.basicConfig(level=log_lvl)

    result = hpres.logged_results_to_HBS_result(args.config_dir)
    id2conf = result.get_id2config_mapping()
    inc_id = result.get_incumbent_id()
    inc_config = id2conf[inc_id]['config']
    info = result.get_runs_by_id(inc_id)[-1]['info']

    if args.transfer:
        parent_config = json.load(open(args.config_dir+'parent.json'))
        inc_config = unified_config(parent_config, inc_config)

    print("Best configuration: ", inc_config)
    print()
    print(info)
    print()
    print('~+~'*40)
    print("Building model on full train set for ", args.dataset,
     " to be evaluated on full test set.")

    if inc_config['model_optimizer'] == 'adam':
        if inc_config['amsgrad'] == 'True':
            opti_aux_param = True
        else:
            opti_aux_param = False
    elif inc_config['model_optimizer'] == 'sgd':
        opti_aux_param = inc_config['momentum']
    else:
        opti_aux_param = None
    opti_dict = {'adam': torch.optim.Adam, 'adad': torch.optim.Adadelta,
                'sgd': torch.optim.SGD}

    start = time.time()

    if args.data_augmentation is not None:
        data_augmentation = inc_config['aug_prob']
    else:
        data_augmentation = None

    train_score, _, test_score, _, _, _, _, model, train, test, cm = train_test(
        dataset=args.dataset,  # dataset to use
        model_config=inc_config,
        data_dir='../data',
        num_epochs=args.epochs,
        batch_size=int(inc_config['batch_size']),
        learning_rate=inc_config['learning_rate'],
        train_criterion=torch.nn.CrossEntropyLoss,
        model_optimizer=opti_dict[inc_config['model_optimizer']],
        opti_aux_param=opti_aux_param,
        data_augmentations=data_augmentation,
        save_model_str=None
        # test=True
    )
    plot_learning_curve(train, test, args.config_dir, args.epochs)
    if args.dataset == 'K49':
        plot_confusion_matrix(cm, range(0,49), out_dir=args.config_dir, dataset=args.dataset, name=args.epochs, normalize=False)
    else:
        plot_confusion_matrix(cm, range(0,10), out_dir=args.config_dir, dataset=args.dataset, name=args.epochs, normalize=False)

    print('~+~' * 40)
    print("Time take to train and evalaute: ", time.time() - start)
    print('~+~'*40)
    print("Training Accuracy: ", train_score)
    print("Test Accuracy: ", test_score)
