#!/bin/bash

# Функция для установки npm пакета, если он не установлен
install_npm_package() {
    PACKAGE_NAME=$1
    if ! command -v "$PACKAGE_NAME" &> /dev/null; then
        echo "🤔 '$PACKAGE_NAME' не найден. Установка..."
        npm i -g "@vkontakte/$PACKAGE_NAME"
        if [ $? -ne 0 ]; then
            echo "❌ Ошибка при установке '$PACKAGE_NAME'. Проверьте, что npm установлен и работает."
            exit 1
        fi
    fi
}

# --- ШАГ 1: НАСТРОЙКА ВИРТУАЛЬНОГО ОКРУЖЕНИЯ И ЗАВИСИМОСТЕЙ ---
echo "⚙️  Начало настройки окружения..."
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Создание виртуального окружения..."
    sleep 2
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "❌ Ошибка при создании виртуального окружения. Убедитесь, что Python3 установлен."
        exit 1
    fi
fi

# Активируем виртуальное окружение
source "$VENV_DIR/bin/activate"

echo "Установка Python-зависимостей..."
pip install aiohttp pycryptodome > /dev/null
if [ $? -ne 0 ]; then
    echo "❌ Ошибка при установке Python-пакетов."
    deactivate
    exit 1
fi
echo "✅ Python-зависимости установлены."

echo "Проверка и установка npm-пакета '@vkontakte/vk-tunnel'..."
npm i -g @vkontakte/vk-tunnel
echo "✅ npm-пакет установлен."

sleep 1

# --- ШАГ 2: НАСТРОЙКА КОНФИГУРАЦИОННЫХ ФАЙЛОВ ---
echo "✍️  Начало настройки конфигурационных файлов..."

# Настройка config_light.py
AES_CONFIG_FILE="config_light.py"
if [ ! -f "$AES_CONFIG_FILE" ]; then
    echo "❌ Ошибка: Файл '$AES_CONFIG_FILE' не найден. Пропускаю настройку AES ключа."
else
    AES_KEY=$(openssl rand -hex 16)
    sed -i.bak "s/\"aes_key_hex\": \"\"/\"aes_key_hex\": \"$AES_KEY\"/" "$AES_CONFIG_FILE"
    if [ $? -eq 0 ]; then
        echo "✅ Новый AES ключ успешно сгенерирован и добавлен в $AES_CONFIG_FILE."
    else
        echo "❌ Ошибка при обновлении AES ключа в файле $AES_CONFIG_FILE."
    fi
fi

sleep 1

# Настройка server.py
PYTHON_FILE="server.py"
if [ ! -f "$PYTHON_FILE" ]; then
    echo "❌ Ошибка: Файл '$PYTHON_FILE' не найден. Пропускаю настройку Telegram."
else
    echo "Введите ваш Telegram BOT_TOKEN:"
    read -r BOT_TOKEN
    echo "Введите ваш Telegram CHAT_ID и ALLOWED_USER_ID:"
    read -r USER_ID_AND_CHAT_ID

    sed -i.bak "
        s/BOT_TOKEN = \"\"/BOT_TOKEN = \"$BOT_TOKEN\"/
        s/CHAT_ID = \"\"/CHAT_ID = \"$USER_ID_AND_CHAT_ID\"/
        s/ALLOWED_USER_ID = .*/ALLOWED_USER_ID = $USER_ID_AND_CHAT_ID/
    " "$PYTHON_FILE"

    if [ $? -eq 0 ]; then
        echo "✅ Настройки Telegram успешно обновлены в файле '$PYTHON_FILE'."
    else
        echo "❌ Ошибка: Не удалось обновить файл '$PYTHON_FILE'."
    fi
fi

# --- ШАГ 3: ЗАПУСК ПРИЛОЖЕНИЯ ---
echo ""
read -p "🚀 Хотите ли вы запустить VK-TUNNEL сейчас? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Запуск процессов через 4 секунды..."
    sleep 4

    echo "Запуск server.py в фоновом режиме..."
    nohup python3 server.py > server.log 2>&1 &
    
    echo "Запуск vk-tunnel.py (если существует) в фоновом режиме..."
    if [ -f "vk-tunnel.py" ]; then
        nohup python3 vk-tunnel.py > vk-tunnel.log 2>&1 &
    else
        echo "Предупреждение: файл 'vk-tunnel.py' не найден. Запущен только server.py."
    fi

    echo ""
    echo "✅ Процессы запущены. Вы можете закрыть терминал."
    echo "Логи можно посмотреть в файлах server.log и vk-tunnel.log."
fi

# Деактивируем виртуальное окружение
deactivate
echo "🚪 Виртуальное окружение деактивировано."