import argparse
import hpbandster.core.result as hpres
from main import train
from main import train_test
import torch
import logging
import json
import time
from matplotlib import pyplot as plt

logging.basicConfig(level=logging.INFO)

def unified_config(parent, config):
    parent['batch_size'] = config['batch_size']
    for i in range(parent['n_conv_layer']):
        parent['channel_'+str(i+1)] = config['channel_'+str(i+1)]
    for i in range(parent['n_fc_layer']-1):
        del(parent['fc_'+str(i+1)])
    parent['n_fc_layer'] = config['n_fc_layer']
    for i in range(config['n_fc_layer']-1):
        parent['fc_'+str(i+1)] = config['fc_nodes']  #500
    return parent

def plot_learning_curve(train, test, out_dir):
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
    plt.savefig(out_dir+'learning_curve.png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--config_dir", dest="config_dir", type=str)
    parser.add_argument("--dataset", dest="dataset", type=str, default='KMNIST')
    parser.add_argument("--epochs", dest="epochs", type=int, default=1)
    parser.add_argument("--transfer", dest="transfer", type=bool, default=False)
    args, kwargs = parser.parse_known_args()

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
    # train_score, _, test_score, _, _, _, _, model = train(
    #     dataset=args.dataset,  # dataset to use
    #     model_config=inc_config,
    #     data_dir='../data',
    #     num_epochs=args.epochs,
    #     batch_size=int(inc_config['batch_size']),
    #     learning_rate=inc_config['learning_rate'],
    #     train_criterion=torch.nn.CrossEntropyLoss,
    #     model_optimizer=opti_dict[inc_config['model_optimizer']],
    #     opti_aux_param=opti_aux_param,
    #     data_augmentations=None,  # Not set in this example
    #     save_model_str=None,
    #     test=True
    # )
    train_score, _, test_score, _, _, _, _, model, train, test = train_test(
        dataset=args.dataset,  # dataset to use
        model_config=inc_config,
        data_dir='../data',
        num_epochs=args.epochs,
        batch_size=int(inc_config['batch_size']),
        learning_rate=inc_config['learning_rate'],
        train_criterion=torch.nn.CrossEntropyLoss,
        model_optimizer=opti_dict[inc_config['model_optimizer']],
        opti_aux_param=opti_aux_param,
        data_augmentations=None,  # Not set in this example
        save_model_str=None
        # test=True
    )
    plot_learning_curve(train, test, args.config_dir)
    print("Time take to train and evalaute: ", time.time() - start)
    print('~+~'*40)
    print("Training Accuracy: ", train_score)
    print("Test Accuracy: ", test_score)
