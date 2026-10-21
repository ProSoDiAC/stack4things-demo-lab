FROM docker:26-cli AS docker-cli

FROM python:3.11-slim
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
RUN pip install --no-cache-dir flask==3.1.3
WORKDIR /app
# lr_log_proxy.py is bind-mounted by docker-compose.yml
CMD ["python3", "/app/lr_log_proxy.py"]
