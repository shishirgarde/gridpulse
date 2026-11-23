
import torch
import torch.nn as nn
import torch.nn.functional as F


class TemporalBlock(nn.Module):
    def __init__(self, channels, dilation):
        super().__init__()

        self.conv = nn.Conv1d(
            channels,
            channels,
            kernel_size=3,
            dilation=dilation,
            padding=2 * dilation,
        )

        self.norm = nn.GroupNorm(4, channels)
        self.dropout = nn.Dropout(0.1)

    def forward(self, x):
        residual = x
        x = self.conv(x)

        x = x[:, :, :-self.conv.padding[0]]
        x = F.relu(self.norm(x))

        return residual + self.dropout(x)


class GridPulseTCN(nn.Module):
    def __init__(self, future_features=10, hidden=32):
        super().__init__()

        self.input_proj = nn.Conv1d(1, hidden, 1)

        self.tcn = nn.Sequential(
            TemporalBlock(hidden, dilation=1),
            TemporalBlock(hidden, dilation=2),
            TemporalBlock(hidden, dilation=4),
            TemporalBlock(hidden, dilation=8),
            TemporalBlock(hidden, dilation=16),
        )

        self.future_encoder = nn.Sequential(
            nn.Linear(future_features * 7, 32),
            nn.ReLU(),
        )

        self.head = nn.Sequential(
            nn.Linear(hidden + 32, 64),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(64, 7),
        )

    def forward(self, history, future):
        x = history.unsqueeze(1)
        x = self.input_proj(x)
        x = self.tcn(x)

        history_features = x[:, :, -1]

        future_features = self.future_encoder(
            future.flatten(start_dim=1)
        )

        combined = torch.cat(
            [history_features, future_features],
            dim=1,
        )

        return self.head(combined)
