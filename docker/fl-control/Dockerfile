FROM python:3.11-slim
# Flower server + dashboard backend. CPU-only torch keeps the image small.
RUN pip install --no-cache-dir flask==3.1.3 flwr==1.36.0 pandas==3.0.5 scikit-learn==1.9.0 \
 && pip install --no-cache-dir torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
WORKDIR /lab/experiments/federated-learning
CMD ["python3", "/lab/experiments/federated-learning/control_server.py"]
