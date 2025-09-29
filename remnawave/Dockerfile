FROM python:3.11-slim

WORKDIR /app

# Установка Node.js и npm для установки vk-tunnel
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Установка vk-tunnel через npm
RUN npm install -g @vkontakte/vk-tunnel

# Копирование файлов
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все необходимые файлы
COPY main.py api.py handlers.py admin.py ./

# Проверяем установку
RUN vk-tunnel --version

# Запуск приложения
CMD ["python", "-u", "main.py"]
