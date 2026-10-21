FROM python:3.11-slim
RUN pip install --no-cache-dir flask==3.1.3 influxdb==5.3.2
WORKDIR /app
# metrics_server.py and registry.py are bind-mounted by docker-compose.yml
CMD ["python3", "/app/metrics_server.py"]
