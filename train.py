import os
import torch
from torch.utils.data import DataLoader
import torch.nn.functional as F
from torch.utils.tensorboard import SummaryWriter

from model import fpn
from utils.mat2pic import trans_separate, GeneralDataset, ValDataset_diff, TestDataset_diff
from utils.model_init import weights_init
from utils.scheduler import WarmupMultiStepLR

project_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fpn_new')


def train(idx_train, num_data_train, net_name):
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    device = torch.device('cuda')
    if not torch.cuda.is_available():
        print("Use CPU")
        device = torch.device('cpu')
    else:
        print("Use GPU:", os.environ['CUDA_VISIBLE_DEVICES'])

    batch_size = 64
    max_epochs = 200
    model_valid_interval = 1
    LEARNING_RATE = 1e-3
    LOAD_PRETRAIN = True

    model = fpn().to(device)

    model_path = os.path.join(project_path, 'model', 'source', 'problem7', 'b', 'train40000_diff', '0', 'best_model')

    log_dir = os.path.join(project_path, 'log', 'fpn', 'finetune', 'problem1', net_name, num_data_train, str(idx_train))
    os.makedirs(log_dir, exist_ok=True)
    writer = SummaryWriter(log_dir)

    dataset = GeneralDataset(trans_separate, resize_shape=(200, 200))
    dataset_val = ValDataset_diff(trans_separate, resize_shape=(200, 200))

    train_loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=2)
    train_loader_diff = DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=2)
    valid_loader = DataLoader(dataset_val, batch_size=16, shuffle=False, drop_last=False)

    print("model path:", model_path)

    if LOAD_PRETRAIN and os.path.exists(model_path):
        if torch.cuda.is_available():
            model.load_state_dict(torch.load(model_path, map_location='cuda:0'))
        else:
            model.load_state_dict(torch.load(model_path, map_location='cpu'))
        print("model initiated with", model_path)
    else:
        model.backbone.apply(weights_init)
        print("model initiated without pretrain")
    for p in model.parameters():
        p.requires_grad = True

    print("\tLearning Rate:", LEARNING_RATE)
    print("\tBatch Size:", batch_size)
    print()

    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    scheduler = WarmupMultiStepLR(optimizer, milestones=[1000, 1400], warmup_iters=len(train_loader))

    train_iter_diff = iter(train_loader_diff)
    train_idx = 0
    best_mae = 999
    for epoch in range(max_epochs):
        for it, images in enumerate(train_loader):
            layout_image_diff, heat_image_diff = next(train_iter_diff)
            layout_image_diff, heat_image_diff = layout_image_diff.to(device), heat_image_diff.to(device)
            train_idx += 1
            if train_idx == len(train_loader_diff):
                train_iter_diff = iter(train_loader_diff)
                train_idx = 0

            layout_image = images[0].to(device) - layout_image_diff
            heat_image = images[1].to(device) - heat_image_diff
            m = model(layout_image)
            loss = F.l1_loss(m, heat_image)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            scheduler.step()

            print("\tEpoch[{}/{}] Iters[{}/{}] Loss: {:.3f}".format(
                epoch + 1, max_epochs, it, len(train_loader), loss.item()))
            writer.add_scalar('loss/loss', loss.item(), epoch * len(train_loader) + it)

        if (epoch + 1) % model_valid_interval == 0:
            mae, mse, num = 0.0, 0.0, 0.0
            model.eval()
            criterion1 = torch.nn.L1Loss()
            criterion2 = torch.nn.MSELoss()
            for it, images in enumerate(valid_loader):
                layout_image = images[0].to(device)
                heat_image = images[1].to(device)
                with torch.no_grad():
                    m = model(layout_image)
                    l1_loss = criterion1(m, heat_image) * layout_image.shape[0]
                    l2_loss = criterion2(m, heat_image) * layout_image.shape[0]
                num += layout_image.shape[0]
                mae += l1_loss.item()
                mse += l2_loss.item()
            mae = mae / num
            mse = mse / num
            print("test", "mae:", mae, "mse:", mse)
            writer.add_scalar("test/MAE", mae, epoch + 1)
            writer.add_scalar("test/MSE", mse, epoch + 1)
            model.train()
            if mae < best_mae:
                best_mae = mae
                model_save_path = os.path.join(project_path, "model", "finetune", "problem1", net_name, num_data_train,
                                               str(idx_train))
                os.makedirs(model_save_path, exist_ok=True)
                torch.save(model.state_dict(), model_save_path + "/best_model")
                print("Model Saved:", model_save_path + "/best_model")
    writer.close()


def test(idx_train, num_data_train, name_net):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = fpn().to(device)

    model_path = os.path.join(project_path, "model", "finetune", "problem1",
                              name_net, num_data_train, str(idx_train), "best_model")

    target_dataset_test = TestDataset_diff(trans_separate, resize_shape=(200, 200))
    target_test_loader = DataLoader(target_dataset_test, batch_size=16, shuffle=False, drop_last=False)
    print("model path:", model_path)

    if os.path.exists(model_path):
        if torch.cuda.is_available():
            model.load_state_dict(torch.load(model_path, map_location='cuda:0'))
        else:
            model.load_state_dict(torch.load(model_path, map_location='cpu'))
        print("model initiated with", model_path)

    mae, mse, num = 0.0, 0.0, 0.0
    model.eval()
    criterion1 = torch.nn.L1Loss()
    criterion2 = torch.nn.MSELoss()
    for it, images in enumerate(target_test_loader):
        layout_image = images[0].to(device)
        heat_image = images[1].to(device)
        with torch.no_grad():
            m = model(layout_image)
            l1_loss = criterion1(m, heat_image) * layout_image.shape[0]
            l2_loss = criterion2(m, heat_image) * layout_image.shape[1]
        num += layout_image.shape[0]
        mae += l1_loss.item()
        mse += l2_loss.item()
    mae = mae / num
    mse = mse / num
    return mae, mse


if __name__ == "__main__":

    num_data_train = 'p7_train500'
    name_net = 'b'
    num_train = 1
    for idx in range(num_train):
        train(idx, num_data_train, name_net)
    print("\n#################### Test ####################\n")
    mae_test, mse_test = 0.0, 0.0
    for idx in range(num_train):
        mae_test_idx, mse_test_idx = test(idx, num_data_train, name_net)
        print("[{}:{}]".format(idx, num_train), "mae:", mae_test_idx, "mse:", mse_test_idx)
        mae_test += mae_test_idx
        mse_test += mse_test_idx
    print("mae:", mae_test / num_train, "mse:", mse_test / num_train)