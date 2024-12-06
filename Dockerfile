FROM python:3.10-slim

WORKDIR /app

# Установим зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Скопируем всё остальное (код бота) в контейнер
COPY . .

# Запуск бота
CMD ["python", "bot.py"]
