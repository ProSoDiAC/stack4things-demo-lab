import os
import sys

import flwr as fl
import torch
import torch.nn as nn
import torch.nn.functional as F
import pandas as pd
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

FL_EXP = os.path.dirname(os.path.abspath(__file__))
if os.path.join(os.path.dirname(FL_EXP), "experiments", "federated-learning") not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(FL_EXP), "experiments", "federated-learning"))

try:
    from fl_events import emit, reset as reset_fl_events
    from visual_strategy import VisualFedAvg
    _DASHBOARD = os.environ.get("FL_DASHBOARD", "1") != "0"
except ImportError:
    _DASHBOARD = False
    VisualFedAvg = fl.server.strategy.FedAvg  # type: ignore[misc,assignment]
    reset_fl_events = emit = lambda *a, **k: None  # noqa: E731


# Define FCN model for tabular data
class Net(nn.Module):
    def __init__(self, input_dim):
        super(Net, self).__init__()
        self.fc1 = nn.Linear(input_dim, 64)
        self.fc2 = nn.Linear(64, 32)
        self.fc3 = nn.Linear(32, 2)  # 2 classes for CrossEntropyLoss

    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return self.fc3(x)


# Load test data for server-side evaluation
def load_test_data(input_dim=None):
    test_name = os.environ.get("FL_TEST_CSV", "data_test_heart.csv")
    if input_dim == 6 and "heart" in test_name:
        test_name = "data_test_pm.csv"
    elif input_dim == 13 and "pm" in test_name:
        test_name = "data_test_heart.csv"
    df = pd.read_csv(test_name)
    df = df.dropna()
    x = df.drop("target", axis=1).values.astype("float32")
    y = df["target"].values.astype("int64")
    x = StandardScaler().fit_transform(x)

    x = torch.tensor(x)
    y = torch.tensor(y)

    dataset = TensorDataset(x, y)
    dataloader = DataLoader(dataset, batch_size=32)
    return dataloader, x.shape[1]  # Return input_dim for Net()


# Set weights in the model
def set_weights(model, parameters):
    state_dict = dict(zip(model.state_dict().keys(), [torch.tensor(p) for p in parameters]))
    model.load_state_dict(state_dict, strict=True)


# Evaluation function
def evaluate_fn(server_round, parameters, config):
    weight_dim = int(parameters[0].shape[1]) if len(parameters) else None
    testloader, csv_dim = load_test_data(weight_dim)
    input_dim = weight_dim or csv_dim
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = Net(input_dim).to(device)
    set_weights(model, parameters)

    model.eval()
    criterion = nn.CrossEntropyLoss()
    total_loss = 0.0
    total_samples = 0
    correct = 0

    with torch.no_grad():
        for x_batch, y_batch in testloader:
            x_batch, y_batch = x_batch.to(device), y_batch.to(device)
            output = model(x_batch)
            batch_n = y_batch.size(0)
            batch_loss = criterion(output, y_batch).item()
            if batch_loss == batch_loss:  # finite
                total_loss += batch_loss * batch_n
            total_samples += batch_n
            correct += (output.argmax(1) == y_batch).sum().item()

    accuracy = correct / total_samples if total_samples else 0.0
    loss = total_loss / total_samples if total_samples else 0.0
    print(f"[Server Evaluation] Round {server_round} - Loss: {loss:.4f}, Accuracy: {accuracy:.4f}")
    if _DASHBOARD:
        emit(
            "metrics",
            f"Round {server_round} - accuracy {accuracy:.2%}",
            phase="evaluating",
            round=server_round,
            accuracy=float(accuracy),
            loss=float(loss),
            fl_scenario=os.environ.get("FL_SCENARIO", "heart"),
        )
    return loss, {"accuracy": accuracy}


# Start Flower server (Ch.19 — runs on S4T VM host, not on a board)
if __name__ == "__main__":
    rounds = int(os.environ.get("FL_ROUNDS", "2"))
    host = os.environ.get("FL_HOST", "0.0.0.0")
    port = int(os.environ.get("FL_PORT", "8087"))
    bind = f"{host}:{port}"

    scenario = os.environ.get("FL_SCENARIO", "heart")
    banners = {
        "heart": "Heart disease FL (Ch.19) — waiting for 3 edge cohorts",
        "pm": "Predictive maintenance FL — waiting for 3 production lines",
    }
    if _DASHBOARD:
        reset_fl_events(int(rounds), scenario=scenario)
        emit(
            "server_start",
            banners.get(scenario, "Flower server listening on {0}".format(bind)),
            phase="waiting_clients",
            round=0,
            fl_scenario=scenario,
        )

    strategy = VisualFedAvg(
        fraction_fit=1.0,
        min_fit_clients=3,
        min_available_clients=3,
        evaluate_fn=evaluate_fn,
        on_fit_config_fn=lambda rnd: {"round": rnd},
    )

    print(f"Flower FedAvg server listening on {bind} — {rounds} round(s), min 3 clients")
    if _DASHBOARD:
        print("FL dashboard: http://127.0.0.1:8090/  (Horizon: /horizon/fl/)")
    fl.server.start_server(
        server_address=bind,
        config=fl.server.ServerConfig(num_rounds=rounds),
        strategy=strategy,
    )
    if _DASHBOARD:
        emit("finished", "Federated learning run complete", phase="finished")
