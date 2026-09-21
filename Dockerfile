FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Порт встроенного веб-сервера: Mini App (статика + API) и вебхук xRocket Pay.
# Railway подставляет свою переменную PORT автоматически.
EXPOSE 8085
CMD ["python", "-m", "app"]
