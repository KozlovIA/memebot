# Используем официальный Python-образ
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файлы проекта в контейнер
COPY . /app

# Обновляем pip (опционально, но полезно)
RUN pip install --upgrade pip

# Устанавливаем зависимости
RUN pip install --no-cache-dir python-telegram-bot==20.3 pyyaml nest_asyncio collections

# Создаем папку для мемов, если её нет (опционально)
RUN mkdir -p ./memes

# Экспонируем переменную окружения для логов (если надо)
ENV PYTHONUNBUFFERED=1

# Запуск бота
CMD ["python", "bot.py"]