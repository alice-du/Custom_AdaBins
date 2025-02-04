import torch
import torch.nn as nn

from torch.nn.utils.rnn import pad_sequence
from chamferdist import ChamferDistance


class BerhuLoss(nn.Module):
    def __init__(self):
        super(BerhuLoss, self).__init__()

    def forward(self, pred, target, mask=None, interpolate=True):
        if interpolate:
            pred = nn.functional.interpolate(pred, target.shape[-2:], mode='bilinear', align_corners=True)
        if mask is not None:
            pred = pred[mask]
            target = target[mask]
        c = 0.2*(torch.max(torch.abs(target-pred)))
        mat =  torch.abs(target-pred)
        result = torch.zeros_like(mat)
        result[mat > c] = (mat[mat > c]**2 + c **2)/(2*c)
        result[mat < c] = torch.abs(mat[mat < c])
        return torch.mean(result)


        

class MSELoss(nn.Module):
    def __init__(self):
        super(MSELoss, self).__init__()

    def forward(self, pred, target, mask=None, interpolate=True):
        if interpolate:
            pred = nn.functional.interpolate(pred, target.shape[-2:], mode='bilinear', align_corners=True)

        if mask is not None:
            pred = pred[mask]
            target = target[mask]
        return ((pred - target) ** 2).mean()
    
class SILogLoss(nn.Module):  # Main loss function used in AdaBins paper
    def __init__(self):
        super(SILogLoss, self).__init__()


    def forward(self, input, target, mask=None, interpolate=True):
        if interpolate:
            input = nn.functional.interpolate(input, target.shape[-2:], mode='bilinear', align_corners=True)

        if mask is not None:
            input = input[mask]
            target = target[mask]
        
        g = torch.log(input) - torch.log(target)

        Dg = torch.var(g) + 0.15 * torch.pow(torch.mean(g), 2)

        return 10 * torch.sqrt(Dg)
    
class BinsChamferLoss(nn.Module):  # Bin centers regularizer used in AdaBins paper
    def __init__(self):
        super().__init__()


    def forward(self, bin_center, ground_truth):

        gt_points = ground_truth.flatten(1)  # n, hwc
        mask = gt_points.ge(1e-3)  # only valid ground truth points
        gt_points = [p[m] for p, m in zip(gt_points, mask)]
        gt_length = torch.Tensor([len(t) for t in gt_points]).long().to(ground_truth.device)
        gt_points = pad_sequence(gt_points, batch_first=True).unsqueeze(2)  # .shape = n, T, 1
        chamferDist = ChamferDistance()
        loss= chamferDist(bin_center, gt_points)
        
        return loss
