import os
import argparse
import logging
import time

import torch
import torchvision.transforms as transforms
from torch.utils.data import DataLoader
from torch.utils.data import SubsetRandomSampler
from torchsummary import summary

import numpy as np
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix

from cnn import ConfigurableNet
from datasets import KMNIST, K49


def eval(model, loader, device, train_criterion, train=False):
    """
    Evaluation method
    :param model: Model to evaluate
    :param loader: data loader for either training or testing set
    :param device: torch device
    :param train: boolean to indicate if training or test set is used
    :return: accuracy on the data
    """
    true, pred = [], []
    tot_loss = []
    with torch.no_grad():  # no gradient needed
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)
            outputs = model(images)
            if type(train_criterion) == torch.nn.MSELoss:
                one_hot = torch.zeros((len(labels), 10))
                for i, l in enumerate(one_hot): one_hot[i][labels[i]] = 1
                loss = train_criterion(outputs, one_hot)
            else:
                loss = train_criterion(outputs, labels)
            tot_loss.append(loss)
            _, predicted = torch.max(outputs.data, 1)
            true.extend(labels)
            pred.extend(predicted)
        # return balanced accuracy where each sample is weighted according to occurrence in dataset
        score = balanced_accuracy_score(true, pred)
        # return the confusion matrix
        cnf_matrix = confusion_matrix(true, pred)
        str_ = 'rain' if train else 'est'
        logging.info('T{0} Accuracy of the model on the {1} t{0} images: {2}%'.format(str_, len(true), 100 * score))
        # return the mean loss obtained
        tot_loss = np.mean(tot_loss)
    return score, tot_loss, cnf_matrix


def train(dataset,
          model_config,
          data_dir,
          num_epochs=10,
          batch_size=50,
          learning_rate=0.001,
          train_criterion=torch.nn.CrossEntropyLoss,
          model_optimizer=torch.optim.Adam,
          opti_aux_param=False,
          data_augmentations=None,
          save_model_str=None,
          test=False):
    '''
    Training loop for configurableNet.
    :param dataset: which dataset to load (str)
    :param model_config: configurableNet config (dict)
    :param data_dir: folder dump from where KMNIST/K49 can be loaded
    :param num_epochs: (int)
    :param batch_size: (int)
    :param learning_rate: model optimizer learning rate (float)
    :param train_criterion: Which loss to use during training (torch.nn._Loss)
    :param model_optimizer: Which model optimizer to use during trainnig (torch.optim.Optimizer)
    :param opti_aux_param:
    :param data_augmentations: List of data augmentations to apply such as rescaling.
        (list[transformations], transforms.Composition[list[transformations]], None)
        If none only ToTensor is used
    :param save_model_str: Directory to save the model
    :param test: True/False on whether the test set to be evaluated or validation obtained from training set
    :return: Model, Model statistics, confusion matrix
    '''

    if train_criterion == torch.nn.MSELoss:
        train_criterion = train_criterion(reduction='mean')  # not instantiated until now
    else:
        train_criterion = train_criterion()

    # Device configuration (fixed to cpu as we don't provide GPUs for the project)
    device = torch.device('cpu')  # 'cuda:0' if torch.cuda.is_available() else 'cpu')

    # Adding Rotation and Shear as transforms for Data Augmentation
    # https://discuss.pytorch.org/t/data-augmentation-in-pytorch/7925/9
    # if data_augmentations is not None:
    #     data_augmentations = transforms.Compose([
    #         transforms.ToPILImage(),
    #         transforms.RandomApply([transforms.RandomRotation(15),
    #                                 #transforms.Resize((28, 28)),
    #                                 transforms.RandomAffine(degrees=15, shear=10)]
    #         , p=model_config['aug_prob']),
    #         transforms.ToTensor()
    #     ])

    if data_augmentations is None:
        # We only use ToTensor here as that is al that is needed to make it work
        data_augmentations = transforms.ToTensor()
    elif isinstance(type(data_augmentations), list):
        data_augmentations = transforms.Compose(data_augmentations)
    elif not isinstance(data_augmentations, transforms.Compose):
        raise NotImplementedError

    if dataset == 'KMNIST':
        train_dataset = KMNIST(data_dir, True, data_augmentations)
        test_dataset = KMNIST(data_dir, False, data_augmentations)
    elif dataset == 'K49':
        train_dataset = K49(data_dir, True, data_augmentations)
        test_dataset = K49(data_dir, False, data_augmentations)
    else:
        raise NotImplementedError

    # fidelity_limit = 9  # Budget/Epochs under which the data will be sampled
    #
    # Cheap evaluations for low budget (Optimistic compromise)
    # Samples f_min samples from each class
    # where f_min = # of data points available for the lowest frequent class
    #
    # if num_epochs < fidelity_limit:
    #     # Sampling from all classes equally
    #     label_dict = {}
    #     for i in range(len(train_dataset)):
    #         c = train_dataset[i][-1]
    #         if c not in label_dict.keys():
    #             label_dict[c] = [i]
    #         else:
    #             label_dict[c].append(i)
    #     num_classes = len(label_dict.keys())
    #     # Frequency of most under-represented class
    #     f_min = len(train_dataset)
    #     for keys in label_dict.keys():
    #         if len(label_dict[keys]) < f_min:
    #             f_min = len(label_dict[keys])
    #     selected_data = np.array([])
    #     for label in label_dict.keys():
    #         # Samples 2*f_min samples from each class (with replacement for classes with lesser data points)
    #         selected_data = np.append(selected_data, np.random.choice(label_dict[label], 2*f_min))

    # Decides if evaluation is on Test set or Validation set obtained from Train
    if test is False:
        # if num_epochs < fidelity_limit:
        #     dataset_size = len(selected_data)
        #     indices = list(selected_data.astype(int))
        # else:
        dataset_size = len(train_dataset)
        indices = list(range(dataset_size))
        validation_split = 0.3
        # Splitting the Training Set into Train-Validation by 70%-30%
        split = int(np.floor(validation_split * dataset_size))
        np.random.shuffle(indices)
        train_indices, val_indices = indices[split:], indices[:split]

        # Creating PT data samplers and loaders:
        train_sampler = SubsetRandomSampler(train_indices)
        valid_sampler = SubsetRandomSampler(val_indices)

        train_loader = DataLoader(train_dataset, batch_size=batch_size, sampler=train_sampler)
        validation_loader = DataLoader(train_dataset, batch_size=batch_size, sampler=valid_sampler)
    else:
        # Make data batch iterable
        # Could modify the sampler to not uniformly random sample
        train_loader = DataLoader(dataset=train_dataset,
                                  batch_size=batch_size,
                                  shuffle=True)
        test_loader = DataLoader(dataset=test_dataset,
                                 batch_size=batch_size,
                                 shuffle=False)

    model = ConfigurableNet(model_config,
                            num_classes=train_dataset.n_classes,
                            height=train_dataset.img_rows,
                            width=train_dataset.img_cols,
                            channels=train_dataset.channels).to(device)
    total_model_params = np.sum(p.numel() for p in model.parameters())

    equal_freq = [1 / train_dataset.n_classes for _ in range(train_dataset.n_classes)]
    logging.debug('Train Dataset balanced: {}'.format(np.allclose(train_dataset.class_frequency, equal_freq)))
    logging.debug(' Test Dataset balanced: {}'.format(np.allclose(test_dataset.class_frequency, equal_freq)))
    logging.info('Generated Network:')
    summary(model, (train_dataset.channels, train_dataset.img_rows, train_dataset.img_cols), device='cpu')

    # Train the model
    if model_optimizer == torch.optim.Adam:
        optimizer = model_optimizer(model.parameters(), lr=learning_rate, amsgrad=opti_aux_param)
    elif model_optimizer == torch.optim.SGD:
        optimizer = model_optimizer(model.parameters(), lr=learning_rate, momentum=opti_aux_param)
    else:
        optimizer = model_optimizer(model.parameters(), lr=learning_rate)
    total_step = len(train_loader)
    train_time = time.time()
    epoch_times = []
    for epoch in range(num_epochs):
        logging.info('#' * 120)
        epoch_start_time = time.time()
        for i_batch, (images, labels) in enumerate(train_loader):
            images = images.to(device)
            labels = labels.to(device)
            # Forward -> Backward <- passes
            outputs = model(images)    # outputs.detach().numpy()
            if type(train_criterion) == torch.nn.MSELoss:
                one_hot = torch.zeros((len(labels), 10))
                for i, l in enumerate(one_hot): one_hot[i][labels[i]] = 1
                labels = one_hot
            loss = train_criterion(outputs, labels)
            optimizer.zero_grad()  # zero out gradients for new minibatch
            loss.backward()

            optimizer.step()
            if (i_batch + 1) % 100 == 0:
                logging.info('Epoch [{}/{}], Step [{}/{}], Loss: {:.4f}'.format(
                    epoch + 1, num_epochs, i_batch + 1, total_step, loss.item()))
        epoch_times.append(time.time() - epoch_start_time)
    train_time = time.time() - train_time

    # Test the model
    logging.info('~+~' * 40)
    model.eval()
    test_time = time.time()
    train_score, train_loss, _ = eval(model, train_loader, device, train_criterion, train=True)
    # Decides if evaluation is on Test set or Validation set obtained from Train
    if test:
        test_score, test_loss, cm = eval(model, test_loader, device, train_criterion)
    else:
        test_score, test_loss, cm = eval(model, validation_loader, device, train_criterion)
    logging.info("Evaluation done")
    test_time = time.time() - test_time
    if save_model_str:
        logging.info("Saving model...")
        # Save the model checkpoint can be restored via "model = torch.load(save_model_str)"
        if os.path.exists(save_model_str):
            save_model_str += '_'.join(time.ctime())
        torch.save(model.state_dict(), save_model_str)
    logging.info("Returning from train()")
    return train_score, train_loss, test_score, test_loss, train_time, test_time, total_model_params, model, cm

########################################################################################################################

def train_test(dataset,
          model_config,
          data_dir,
          num_epochs=10,
          batch_size=50,
          learning_rate=0.001,
          train_criterion=torch.nn.CrossEntropyLoss,
          model_optimizer=torch.optim.Adam,
          opti_aux_param=False,
          data_augmentations=None,
          save_model_str=None):
    '''
    This function is exactly like the train() above. The reason to have a second copy is as follows:
    1) Has no test=True/False parameter since it is assumed that test=True (Train not split to Validation)
    2) Evaluates the Test set at each epoch (hence slower)
    3) Tracks and returns two additional values - train & test loss over epochs
    4) Has no code for cheaper evaluations on subsetted data
    Primarily used to generate results for a given configuration or effectively train & test a model
    :return: Model, Model statistics, confusion matrix, training loss over epochs, test loss over epochs
    '''
    if train_criterion == torch.nn.MSELoss:
        train_criterion = train_criterion(reduction='mean')  # not instantiated until now
    else:
        train_criterion = train_criterion()

    # Device configuration (fixed to cpu as we don't provide GPUs for the project)
    device = torch.device('cpu')  # 'cuda:0' if torch.cuda.is_available() else 'cpu')

    # https://discuss.pytorch.org/t/data-augmentation-in-pytorch/7925/9
    if data_augmentations is not None:
        data_augmentations = transforms.Compose([
            transforms.ToPILImage(),
            transforms.RandomApply([transforms.RandomRotation(15),
                                    transforms.Resize((28, 28))]#,
                                    # transforms.RandomAffine(degrees=15, translate=(0,0.2),
                                    #                         scale=(0.8,1.2), shear=10)]
            , p=model_config['aug_prob']),
            transforms.ToTensor()
        ])

    if data_augmentations is None:
        # We only use ToTensor here as that is al that is needed to make it work
        data_augmentations = transforms.ToTensor()
    elif isinstance(type(data_augmentations), list):
        data_augmentations = transforms.Compose(data_augmentations)
    elif not isinstance(data_augmentations, transforms.Compose):
        raise NotImplementedError

    if dataset == 'KMNIST':
        train_dataset = KMNIST(data_dir, True, data_augmentations)
        test_dataset = KMNIST(data_dir, False, data_augmentations)
    elif dataset == 'K49':
        train_dataset = K49(data_dir, True, data_augmentations)
        test_dataset = K49(data_dir, False, data_augmentations)
    else:
        raise NotImplementedError

    train_loader = DataLoader(dataset=train_dataset,
                              batch_size=batch_size,
                              shuffle=True)
    test_loader = DataLoader(dataset=test_dataset,
                             batch_size=batch_size,
                             shuffle=False)

    model = ConfigurableNet(model_config,
                            num_classes=train_dataset.n_classes,
                            height=train_dataset.img_rows,
                            width=train_dataset.img_cols,
                            channels=train_dataset.channels).to(device)
    total_model_params = np.sum(p.numel() for p in model.parameters())

    equal_freq = [1 / train_dataset.n_classes for _ in range(train_dataset.n_classes)]
    logging.debug('Train Dataset balanced: {}'.format(np.allclose(train_dataset.class_frequency, equal_freq)))
    logging.debug(' Test Dataset balanced: {}'.format(np.allclose(test_dataset.class_frequency, equal_freq)))
    logging.info('Generated Network:')
    summary(model, (train_dataset.channels, train_dataset.img_rows, train_dataset.img_cols), device='cpu')

    # Train the model
    if model_optimizer == torch.optim.Adam:
        optimizer = model_optimizer(model.parameters(), lr=learning_rate, amsgrad=opti_aux_param)
    elif model_optimizer == torch.optim.SGD:
        optimizer = model_optimizer(model.parameters(), lr=learning_rate, momentum=opti_aux_param)
    else:
        optimizer = model_optimizer(model.parameters(), lr=learning_rate)
    total_step = len(train_loader)
    train_time = time.time()
    epoch_times = []
    track_train_loss = []
    track_test_loss = []
    for epoch in range(num_epochs):
        logging.info('#' * 120)
        epoch_loss = []
        epoch_start_time = time.time()
        for i_batch, (images, labels) in enumerate(train_loader):
            images = images.to(device)
            labels = labels.to(device)

            # Forward -> Backward <- passes
            outputs = model(images)    # outputs.detach().numpy()
            if type(train_criterion) == torch.nn.MSELoss:
                one_hot = torch.zeros((len(labels), 10))
                for i, l in enumerate(one_hot): one_hot[i][labels[i]] = 1
                labels = one_hot
            loss = train_criterion(outputs, labels)
            epoch_loss.append(loss.data.numpy())
            optimizer.zero_grad()  # zero out gradients for new minibatch
            loss.backward()

            optimizer.step()
            if (i_batch + 1) % 100 == 0:
                logging.info('Epoch [{}/{}], Step [{}/{}], Loss: {:.4f}'.format(
                    epoch + 1, num_epochs, i_batch + 1, total_step, loss.item()))
        epoch_times.append(time.time() - epoch_start_time)
        test_score, test_loss, cm = eval(model, test_loader, device, train_criterion)
        track_test_loss.append(test_loss)
        track_train_loss.append(np.mean(epoch_loss))
    train_time = time.time() - train_time

    # Test the model
    logging.info('~+~' * 40)
    model.eval()
    test_time = time.time()
    train_score, train_loss, _ = eval(model, train_loader, device, train_criterion, train=True)
    # if test:
    # test_score, test_loss = eval(model, test_loader, device, train_criterion)
    # else:
    #     test_score, test_loss = eval(model, validation_loader, device, train_criterion)
    logging.info("Evaluation done")
    test_time = time.time() - test_time
    if save_model_str:
        logging.info("Saving model...")
        # Save the model checkpoint can be restored via "model = torch.load(save_model_str)"
        if os.path.exists(save_model_str):
            save_model_str += '_'.join(time.ctime())
        torch.save(model.state_dict(), save_model_str)
    logging.info("Returning from train()")
    return train_score, train_loss, test_score, test_loss, train_time, test_time, total_model_params, model, \
           track_train_loss, track_test_loss, cm

########################################################################################################################

# Commenting out the original main code
# No longer compatible with the current structure

# if __name__ == '__main__':
#     """
#     This is just an example of how you can use train and evaluate to interact with the configurable network
#     """
#     loss_dict = {'cross_entropy': torch.nn.CrossEntropyLoss,
#                  'mse': torch.nn.MSELoss}
#     opti_dict = {'adam': torch.optim.Adam,
#                  'adad': torch.optim.Adadelta,
#                  'sgd': torch.optim.SGD}
#
#     cmdline_parser = argparse.ArgumentParser('ML4AAD final project')
#
#     cmdline_parser.add_argument('-d', '--dataset',
#                                 default='KMNIST',
#                                 help='Which dataset to evaluate on.',
#                                 choices=['KMNIST', 'K49'],
#                                 type=str.upper)
#     cmdline_parser.add_argument('-e', '--epochs',
#                                 default=10,
#                                 help='Number of epochs',
#                                 type=int)
#     cmdline_parser.add_argument('-b', '--batch_size',
#                                 default=100,
#                                 help='Batch size',
#                                 type=int)
#     cmdline_parser.add_argument('-D', '--data_dir',
#                                 default='../data',
#                                 help='Directory in which the data is stored (can be downloaded)')
#     cmdline_parser.add_argument('-l', '--learning_rate',
#                                 default=0.001,
#                                 help='Optimizer learning rate',
#                                 type=float)
#     cmdline_parser.add_argument('-L', '--training_loss',
#                                 default='cross_entropy',
#                                 help='Which loss to use during training',
#                                 choices=list(loss_dict.keys()),
#                                 type=str)
#     cmdline_parser.add_argument('-o', '--optimizer',
#                                 default='adam',
#                                 help='Which optimizer to use during training',
#                                 choices=list(opti_dict.keys()),
#                                 type=str)
#     cmdline_parser.add_argument('-m', '--model_path',
#                                 default=None,
#                                 help='Path to store model',
#                                 type=str)
#     cmdline_parser.add_argument('-v', '--verbose',
#                                 default='INFO',
#                                 choices=['INFO', 'DEBUG'],
#                                 help='verbosity')
#     args, unknowns = cmdline_parser.parse_known_args()
#     log_lvl = logging.INFO if args.verbose == 'INFO' else logging.DEBUG
#     logging.basicConfig(level=log_lvl)
#
#     if unknowns:
#         logging.warning('Found unknown arguments!')
#         logging.warning(str(unknowns))
#         logging.warning('These will be ignored')
#     # print(args)
#     # print(abcds)
#     a, b , d , e, f, g, h = train(
#         args.dataset,  # dataset to use
#         {  # model architecture
#             'n_layers': 2,
#             # 'conv_layer': 1
#             'n_conv_layer': 1
#         },
#         data_dir=args.data_dir,
#         num_epochs=args.epochs,
#         batch_size=args.batch_size,
#         learning_rate=args.learning_rate,
#         train_criterion=loss_dict[args.training_loss],
#         model_optimizer=opti_dict[args.optimizer],
#         data_augmentations=None,  # Not set in this example
#         save_model_str=args.model_path
#     )
#     print("train_score: ", a)
#     print("test_score :", b)
#     print("train_time :", d)
#     print("test_time :", e)
#     print("total_model_params :", f)
