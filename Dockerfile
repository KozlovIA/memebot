# Используем официальный Python slim
FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта
COPY requirements.txt ./
COPY bot.py ./
COPY control_panel_ui.py ./
COPY config.yaml ./
COPY source ./source
COPY .env ./.env

# Устанавливаем зависимости Python
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Создаем папку для логов
RUN mkdir -p log

# Устанавливаем tini для корректного управления процессами
RUN apt-get update && apt-get install -y tini && rm -rf /var/lib/apt/lists/*

# Экспонируем порты для панели
EXPOSE 8501  

# Запуск обоих скриптов через bash
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-c", "python bot.py & python control_panel_ui.py"]
