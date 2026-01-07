FROM python:3.11-slim

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Python-зависимости
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY bot.py .
COPY control_panel_ui.py .
COPY config.yaml .
COPY source ./source
COPY .env ./.env

# Логи (если понадобятся)
RUN mkdir -p /app/log

# Порт UI
EXPOSE 8501

# tini — как init
ENTRYPOINT ["/usr/bin/tini", "--"]
