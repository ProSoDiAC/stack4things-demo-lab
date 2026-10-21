import os
import sys

import flwr as fl
import torch
import torch.nn as nn
import torch.nn.functional as F
import pandas as pd
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset
from collections import OrderedDict


# Define FCN model
class Net(nn.Module):
    def __init__(self, input_dim):
        super(Net, self).__init__()
        self.fc1 = nn.Linear(input_dim, 64)
        self.fc2 = nn.Linear(64, 32)
        self.fc3 = nn.Linear(32, 2)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return self.fc3(x)


def get_weights(model):
    return [val.cpu().numpy() for _, val in model.state_dict().items()]


def set_weights(model, parameters):
    keys = list(model.state_dict().keys())
    state_dict = OrderedDict({k: torch.tensor(v) for k, v in zip(keys, parameters)})
    model.load_state_dict(state_dict, strict=True)


def load_data(client_id, data_dir=None):
    base = data_dir or os.environ.get("FL_DATA_DIR", ".")
    scenario = os.environ.get("FL_SCENARIO", "heart")
    prefix = os.environ.get("FL_DATA_PREFIX") or ("heart" if scenario == "heart" else "machine")
    file_path = os.path.join(base, f"{prefix}_{client_id + 1}.csv")
    df = pd.read_csv(file_path)

    x = df.drop("target", axis=1).values.astype("float32")
    y = df["target"].values.astype("int64")

    x = StandardScaler().fit_transform(x)
    x = torch.tensor(x)
    y = torch.tensor(y)

    split = int(0.8 * len(x))
    x_train, x_test = x[:split], x[split:]
    y_train, y_test = y[:split], y[split:]

    return (x_train, y_train), (x_test, y_test), x.shape[1]


class MaintenanceClient(fl.client.NumPyClient):
    def __init__(self, client_id, data_dir=None):
        (self.x_train, self.y_train), (self.x_test, self.y_test), input_dim = load_data(
            client_id, data_dir
        )
        self.model = Net(input_dim)
        self.loss_fn = nn.CrossEntropyLoss()
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)

    def get_parameters(self, config):
        return get_weights(self.model)

    def fit(self, parameters, config):
        set_weights(self.model, parameters)
        self.model.train()

        dataset = TensorDataset(self.x_train, self.y_train)
        dataloader = DataLoader(dataset, batch_size=16, shuffle=True)

        for _ in range(1):  # Single epoch (Ch.19 lab)
            for x_batch, y_batch in dataloader:
                self.optimizer.zero_grad()
                outputs = self.model(x_batch)
                loss = self.loss_fn(outputs, y_batch)
                loss.backward()
                self.optimizer.step()

        return get_weights(self.model), len(self.x_train), {}

    def evaluate(self, parameters, config):
        set_weights(self.model, parameters)
        self.model.eval()

        with torch.no_grad():
            outputs = self.model(self.x_test)
            loss = self.loss_fn(outputs, self.y_test).item()
            preds = outputs.argmax(1)
            accuracy = (preds == self.y_test).float().mean().item()

        return loss, len(self.x_test), {"accuracy": accuracy}


def start_client(client_id, server_address=None, data_dir=None):
    addr = server_address or os.environ.get("FL_SERVER", "127.0.0.1:8087")
    fl.client.start_numpy_client(server_address=addr, client=MaintenanceClient(client_id, data_dir))


if __name__ == "__main__":
    cid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv = sys.argv[2] if len(sys.argv) > 2 else None
    start_client(cid, srv)
