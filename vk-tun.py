#!/usr/bin/env python3
import asyncio
import logging
import socket
import sys
from asyncio.subprocess import PIPE

try:
    import aiohttp
except ImportError:
    print("Ошибка: модуль aiohttp не найден. Установите его: pip install aiohttp", file=sys.stderr)
    sys.exit(1)

# --- НАСТРОЙКИ (РЕДАКТИРОВАТЬ ЗДЕСЬ) ---
BOT_TOKEN = ""
CHAT_ID = ""
# Вставьте сюда ваш Telegram User ID, полученный от @userinfobot. Это ВАЖНО для безопасности!
ALLOWED_USER_ID = ""

RESTART_INTERVAL_SECONDS = 5 * 3600  # 5 часов
VK_TUNNEL_COMMAND = [
    "vk-tunnel", "--insecure=1", "--http-protocol=http", "--ws-protocol=ws",
    "--ws-origin=0", "--host=127.0.0.1", "--port=8080",
    "--ws-ping-interval=30"
]

# <<< ИЗМЕНЕНИЕ 1: Проверка конфигурации при старте >>> 
# -------------------------------------------------------------------
if not all([BOT_TOKEN, CHAT_ID, ALLOWED_USER_ID]):
    print("!!! КРИТИЧЕСКАЯ ОШИБКА !!!", file=sys.stderr)
    print("Пожалуйста, откройте скрипт и заполните переменные BOT_TOKEN, CHAT_ID и ALLOWED_USER_ID.", file=sys.stderr)
    sys.exit(1)

try:
    # Сразу преобразуем в число для корректных сравнений
    ALLOWED_USER_ID = int(ALLOWED_USER_ID)
except (ValueError, TypeError):
    print("!!! КРИТИЧЕСКАЯ ОШИБКА !!!", file=sys.stderr)
    print("ALLOWED_USER_ID должен быть числом (например: 123456789), а не текстом.", file=sys.stderr)
    sys.exit(1)
# -------------------------------------------------------------------


# --- КОНФИГУРАЦИЯ ЛОГОВ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("manager")
log_vktunnel = logging.getLogger("vk-tunnel")
log_telegram = logging.getLogger("telegram")

# --- ГЛОБАЛЬНОЕ СОСТОЯНИЕ ---
STATE = {'notification_sent': False}
manual_restart_event = asyncio.Event()

def get_server_info():
    try:
        hostname = socket.getfqdn()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip_address = s.getsockname()[0]
        return ip_address, hostname
    except Exception:
        return "127.0.0.1", "localhost"

SERVER_IP, SERVER_HOSTNAME = get_server_info()

async def send_telegram_message(text: str, chat_id=None):
    target_chat_id = chat_id or CHAT_ID
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': target_chat_id, 'text': text, 'parse_mode': 'Markdown'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload, timeout=10) as response:
                if response.status == 200:
                    log_telegram.info(f"Сообщение в чат {target_chat_id} успешно отправлено.")
                else:
                    log_telegram.error(f"Ошибка отправки в Telegram: {response.status}")
    except Exception as e:
        log_telegram.error(f"Исключение при отправке в Telegram: {e}")

async def monitor_stream(stream: asyncio.StreamReader):
    while True:
        line_bytes = await stream.readline()
        if not line_bytes: break
        line = line_bytes.decode('utf-8', errors='ignore').strip()
        log_vktunnel.info(line)
        if not STATE['notification_sent'] and line.startswith("wss:"):
            try:
                wss_url = line.split(maxsplit=1)[1]
                log.info(f"Обнаружен WSS адрес: {wss_url}. Отправка уведомления...")
                message = (
                    f"🚀 *VK Tunnel запущен/перезапущен*\n\n"
                    f"🖥️ *Сервер:* `{SERVER_HOSTNAME}`\n"
                    f"🌐 *IP:* `{SERVER_IP}`\n\n"
                    f"✨ *Команда для подключения:*\n`python client.py --wss {wss_url}`"
                )
                await send_telegram_message(message)
                STATE['notification_sent'] = True
            except IndexError:
                log.warning(f"Не удалось извлечь URL из строки: '{line}'")

async def listen_for_telegram_commands():
    """Бесконечно слушает команды от Telegram через long polling."""
    last_update_id = 0
    log.info("Запуск слушателя команд Telegram...")
    while True:
        try:
            # <<< ИЗМЕНЕНИЕ 2: Оборачиваем сетевой запрос в гарантированный тайм-аут >>>
            async with asyncio.timeout(60): # Если весь блок займет больше 60с - прервется
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                params = {'offset': last_update_id + 1, 'timeout': 50} # Сам запрос ждет до 50с
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            log.error(f"Ошибка API Telegram: {response.status}")
                            await asyncio.sleep(10)
                            continue

                        data = await response.json()
                        for update in data.get("result", []):
                            last_update_id = update["update_id"]
                            message = update.get("message")
                            if message and "text" in message:
                                user_id = message["from"]["id"]
                                chat_id = message["chat"]["id"]
                                command = message["text"].strip()

                                log.info(f"Получено сообщение '{command}' от пользователя {user_id}")
                                if command == "/restart-tunnel":
                                    if user_id == ALLOWED_USER_ID:
                                        log.info(f"Команда принята от разрешенного пользователя {user_id}.")
                                        await send_telegram_message("✅ Принято! Инициирую перезапуск туннеля...", chat_id=chat_id)
                                        manual_restart_event.set()
                                    else:
                                        log.warning(f"Отклонена команда от НЕАВТОРИЗОВАННОГО пользователя {user_id} (ожидался {ALLOWED_USER_ID}).")
                                        await send_telegram_message("❌ Доступ запрещен.", chat_id=chat_id)
        except asyncio.TimeoutError:
            log.warning("Тайм-аут при запросе к Telegram API. Повторяю запрос...")
            # Ничего страшного, просто идем на следующую итерацию цикла
            continue
        except Exception as e:
            log.error(f"Критическая ошибка в слушателе Telegram: {e}. Перезапуск через 10 секунд...")
            await asyncio.sleep(10)


async def manage_vk_tunnel_lifecycle():
    """Главный цикл, управляющий процессом vk-tunnel."""
    while True:
        log.info(f"Запуск нового цикла. Следующий плановый перезапуск через {RESTART_INTERVAL_SECONDS / 3600:.1f} часов.")
        STATE['notification_sent'] = False
        manual_restart_event.clear()

        try:
            process = await asyncio.create_subprocess_exec(
                *VK_TUNNEL_COMMAND, stdout=PIPE, stderr=PIPE, stdin=None
            )
            log.info(f"Процесс vk-tunnel запущен с PID: {process.pid}")
        except FileNotFoundError:
            log.critical("Команда 'vk-tunnel' не найдена! Повтор через 30с...")
            await asyncio.sleep(30)
            continue

        monitor_stdout_task = asyncio.create_task(monitor_stream(process.stdout))
        monitor_stderr_task = asyncio.create_task(monitor_stream(process.stderr))

        wait_process_task = asyncio.create_task(process.wait())
        wait_timer_task = asyncio.create_task(asyncio.sleep(RESTART_INTERVAL_SECONDS))
        wait_command_task = asyncio.create_task(manual_restart_event.wait())

        done, pending = await asyncio.wait(
            [wait_process_task, wait_timer_task, wait_command_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        if wait_process_task in done:
            log.warning(f"Процесс vk-tunnel (PID: {process.pid}) завершился сам с кодом {process.returncode}. Перезапускаем...")
        elif wait_timer_task in done:
            log.info(f"Сработал таймер. Плановый перезапуск vk-tunnel (PID: {process.pid})...")
        elif wait_command_task in done:
            log.info(f"Ручная команда. Перезапуск vk-tunnel (PID: {process.pid})...")

        for task in pending:
            task.cancel()

        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=10)
                log.info(f"Процесс {process.pid} успешно завершен (terminate).")
            except asyncio.TimeoutError:
                log.warning(f"Процесс {process.pid} не ответил на terminate. Убиваем (kill)...")
                process.kill()
                await process.wait()

        monitor_stdout_task.cancel()
        monitor_stderr_task.cancel()

        log.info("Пауза 5 секунд перед перезапуском...")
        await asyncio.sleep(5)

async def main():
    """Запускает менеджер и слушателя команд."""
    await asyncio.gather(
        manage_vk_tunnel_lifecycle(),
        listen_for_telegram_commands()
    )

if __name__ == "__main__":
    try:
        log.info("Запуск менеджера vk-tunnel с управлением через Telegram.")
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Менеджер остановлен пользователем.")