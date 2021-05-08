import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.utils.data.distributed
import random
import time
from torch.utils.tensorboard import SummaryWriter
import os
import shutil
import utils

from tqdm import tqdm

from models import VGG_16, UnetAdaptiveBins

from dataio import Depth_Dataset
from loss import SILogLoss, BinsChamferLoss
from args import depth_arg
from torch.utils.data import DataLoader
from torch.nn.utils import clip_grad_norm_


def train_model(model, model_dir, args, summary_fn=None, device=None):
    if os.path.exists(model_dir):
        val = input("The model directory %s exists. Overwrite? (y/n)"%model_dir)
        if val == 'y':
            shutil.rmtree(model_dir)

    os.makedirs(model_dir)

    summaries_dir = os.path.join(model_dir, 'summaries')
    utils.cond_mkdir(summaries_dir)

    checkpoints_dir = os.path.join(model_dir, 'checkpoints')
    utils.cond_mkdir(checkpoints_dir)

    writer = SummaryWriter(summaries_dir)
    
    # initialize dataset
    train_dataset = Depth_Dataset(args.dataset, 'train', small_data_num = 100) 
    train_dataset, val_dataset = torch.utils.data.random_split(train_dataset, 
                                                               [int(0.9 * len(train_dataset)), 
                                                                int(0.1 * len(train_dataset))])
   	
    train_data_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_data_loader = DataLoader(val_dataset, batch_size=1, shuffle=False)
    
    # define loss criterion for depth and bin maps
    criterion_depth = SILogLoss() 
    criterion_bins = BinsChamferLoss()
    
    model.train(True)
    
    # we want to tune the parameter of the pretrained encoder more carefully
    params = [{"params": model.get_1x_lr_params(), "lr": args.lr / 10},
              {"params": model.get_10x_lr_params(), "lr": args.lr}]
    
    # define optimizer
    optimizer = optim.AdamW(params, weight_decay=args.wd, lr=args.lr)
    
    # one cycle lr scheduler
    scheduler = optim.lr_scheduler.OneCycleLR(optimizer, args.lr, epochs=args.epochs, 
                                              steps_per_epoch=len(train_data_loader),
                                              cycle_momentum=True,
                                              base_momentum=0.85, max_momentum=0.95, 
                                              last_epoch=args.last_epoch,
                                              div_factor=args.div_factor,
                                              final_div_factor=args.final_div_factor)

    total_steps = 0
    
    with tqdm(total=len(train_data_loader) * args.epochs) as pbar:
        for epoch in range(args.epochs):
            print("Epoch {}/{}".format(epoch, args.epochs))
            print('-' * 10)
            epoch_train_losses = []
            
            if not (epoch+1) % args.epochs_til_checkpoint and epoch:
                torch.save(model.state_dict(),
                           os.path.join(checkpoints_dir, 'model_epoch_%04d.pth' % epoch))
                
            for step, batch in enumerate(train_data_loader):
                start_time = time.time()
                
                # image(N, 3, 427, 565)
                # depth(N, 1, 427, 565)
                optimizer.zero_grad()
                
                image, depth = batch['image'], batch['depth']
                image = image.to(device)
                depth = depth.to(device)
                
                bins, pred = model(image)

                mask = depth > args.min_depth
                mask = mask.to(torch.bool)
                loss_depth = criterion_depth(pred, depth, mask=mask)
                loss_bin = criterion_bins(bins, depth)
                
                loss = loss_depth + args.w_chamfer * loss_bin
                loss.backward()
                epoch_train_losses.append(loss.clone().detach().cpu().numpy())
                clip_grad_norm_(model.parameters(), 0.1)  # optional
                optimizer.step()
                
                
                scheduler.step()
                
                pbar.update(1)
                
                if not (total_steps+1) % args.steps_til_summary:
                    tqdm.write("Epoch [%d/%d], Step [%d/%d], Loss: %.4f, iteration time %0.6f sec" 
                    % (epoch, args.epochs, step, len(train_data_loader), loss, time.time() - start_time))
                    
                    torch.save(model.state_dict(),
                               os.path.join(checkpoints_dir, 'model_current.pth'))
                    writer.add_scalar("step_train_loss", loss, total_steps)
                    # summary_fn(depth, pred, image, writer, total_steps)
                        
                total_steps += 1
                
            writer.add_scalar("epoch_train_loss", np.mean(epoch_train_losses), epoch)


if __name__ == '__main__': 
    args = depth_arg()
    # Set random seed
    print(f'Using random')
    print(f'Using random seed {args.seed}')
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    
    root_path = os.path.join(args.logging_root, args.exp_name)
    
    
    gpu_ids = []
    if torch.cuda.is_available():
        gpu_ids += [gpu_id for gpu_id in range(torch.cuda.device_count())]
        device = torch.device(f'cuda:{gpu_ids[0]}')
        torch.cuda.set_device(device)
    else:
        device = torch.device('cpu')
    print(device)    
    model = UnetAdaptiveBins.build_encoder(n_bins=args.n_bins, min_val=args.min_depth, 
                                           max_val=args.max_depth, norm=args.norm)
    '''
    output_size = (320, 240) 
    model = VGG_16(output_size= output_size) 
    params = model.parameters()
    '''
    model.to(device) 
    args.epoch = 0 
    args.last_epoch = -1
    
    train_model(model, root_path, args, summary_fn=None, device=device)


























