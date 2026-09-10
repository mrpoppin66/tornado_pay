FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Порт для приёма вебхуков xRocket Pay (см. XROCKET_WEBHOOK_PORT)
EXPOSE 8085
CMD ["python", "-m", "app"]
