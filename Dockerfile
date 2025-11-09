# Используем официальный Python slim
FROM python:3.11-slim

# Устанавливаем зависимости системы
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта
COPY requirements.txt .
COPY bot.py .
COPY control_panel_ui.py .
COPY memes ./memes
COPY config.yaml .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Создаем папку для логов
RUN mkdir -p log

# Устанавливаем tini для корректного управления процессами
RUN apt-get update && apt-get install -y tini && rm -rf /var/lib/apt/lists/*

# Экспонируем порты для бота и панели
EXPOSE 8501  
# порт Flask
# Телеграм бот не требует открытого порта, он сам опрашивает API

# Запуск обоих скриптов через bash
# & ставит bot.py в фон, а затем запускает Flask в переднем плане
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-c", "python bot.py & python control_panel_ui.py"]
