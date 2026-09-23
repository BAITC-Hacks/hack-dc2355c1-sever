FROM node:22-slim AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Сборка фронта не должна ронять деплой: если она упала, static/ui остаётся пустой
# и FastAPI отдаёт прежние страницы из static/ (см. client_page в app/main.py).
RUN mkdir -p /static/ui && (npm run build || (echo "!!! Сборка фронтенда упала — отдаём прежние страницы" && mkdir -p /static/ui))

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY static ./static
COPY --from=frontend /static/ui ./static/ui
COPY data ./data

# Railway передаёт порт через $PORT; локально — 8000.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
