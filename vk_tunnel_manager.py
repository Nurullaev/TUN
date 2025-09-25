import asyncio
import logging
import socket
import sys
import time
from asyncio.subprocess import PIPE
from logging.handlers import TimedRotatingFileHandler

try:
    import aiohttp
except ImportError:
    print("Ошибка: модуль aiohttp не найден. Установите его: pip install aiohttp", file=sys.stderr)
    sys.exit(1)

from telegram_commands import TelegramCommandHandler

# --- НАСТРОЙКИ (РЕДАКТИРОВАТЬ ЗДЕСЬ) ---
BOT_TOKEN = ""
CHAT_ID = ""
ALLOWED_USER_ID = ""

RESTART_INTERVAL_SECONDS = 5 * 3600  # 5 часов
HEALTH_CHECK_INTERVAL_SECONDS = 60  # Проверять каждую минуту
TUNNEL_HOST = "127.0.0.1"
TUNNEL_PORT = 8080
LOG_FILENAME = 'manager.log'

VK_TUNNEL_COMMAND = [
    "vk-tunnel", "--verbose", "--insecure=1", "--http-protocol=http", "--ws-protocol=ws",
    "--ws-origin=0", "--host", TUNNEL_HOST, "--port", str(TUNNEL_PORT),
    "--ws-ping-interval=30"
]
# ----------------------------------------------------

# Проверка конфигурации при старте
if not all([BOT_TOKEN, CHAT_ID, ALLOWED_USER_ID]):
    print("!!! КРИТИЧЕСКАЯ ОШИБКА !!!", file=sys.stderr)
    print("Пожалуйста, откройте скрипт и заполните переменные BOT_TOKEN, CHAT_ID и ALLOWED_USER_ID.", file=sys.stderr)
    sys.exit(1)

try:
    ALLOWED_USER_ID = int(ALLOWED_USER_ID)
except (ValueError, TypeError):
    print("!!! КРИТИЧЕСКАЯ ОШИБКА !!!", file=sys.stderr)
    print("ALLOWED_USER_ID должен быть числом.", file=sys.stderr)
    sys.exit(1)

# --- КОНФИГУРАЦИЯ ЛОГОВ С АВТОМАТИЧЕСКОЙ РОТАЦИЕЙ ---
log_formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
file_handler = TimedRotatingFileHandler(LOG_FILENAME, when='midnight', interval=1, backupCount=7, encoding='utf-8')
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

log = logging.getLogger("manager")
log_vktunnel = logging.getLogger("vk-tunnel")
log_telegram = logging.getLogger("telegram")

# --- ГЛОБАЛЬНОЕ СОСТОЯНИЕ ---
STATE = {
    'notification_sent': False,
    'process_start_time': None,
    'last_output_time': None,
    'process_pid': None,
    'last_health_check_time': None  # Добавляем отслеживание времени последней проверки
}

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

# Создаем обработчик команд
telegram_handler = TelegramCommandHandler(BOT_TOKEN, ALLOWED_USER_ID, STATE)

async def send_telegram_message(text: str, chat_id=None):
    """Отправка сообщения в Telegram (для обратной совместимости)"""
    target_chat_id = chat_id or CHAT_ID
    await telegram_handler.send_message(text, target_chat_id)

async def monitor_stream(stream: asyncio.StreamReader):
    """Мониторинг вывода процесса"""
    while True:
        try:
            line_bytes = await stream.readline()
            if not line_bytes:
                log.warning("Поток вывода процесса был закрыт.")
                break

            STATE['last_output_time'] = time.time()
            line = line_bytes.decode('utf-8', errors='ignore').strip()
            log_vktunnel.info(line)

            if not STATE['notification_sent'] and line.startswith("wss:"):
                try:
                    wss_url = line.split(maxsplit=1)[1]
                    log.info(f"Обнаружен WSS адрес: {wss_url}. Отправка уведомления...")
                    message = (f"🚀 *VK Tunnel запущен/перезапущен*\n\n"
                               f"🖥️ *Сервер:* `{SERVER_HOSTNAME}`\n"
                               f"🌐 *IP:* `{SERVER_IP}`\n\n"
                               f"✨ *Команда для подключения:*\n`python client.py --wss {wss_url}`")
                    await send_telegram_message(message)
                    STATE['notification_sent'] = True
                except IndexError:
                    log.warning(f"Не удалось извлечь URL из строки: '{line}'")
        except asyncio.CancelledError:
            break

async def check_tunnel_health():
    """Проверка здоровья туннеля"""
    log.info(f"Активная проверка здоровья запущена. Интервал: {HEALTH_CHECK_INTERVAL_SECONDS}с.")
    await asyncio.sleep(15)  # Даем время на запуск

    while True:
        try:
            reader, writer = await asyncio.open_connection(TUNNEL_HOST, TUNNEL_PORT)
            writer.close()
            await writer.wait_closed()

            # Обновляем время последней успешной проверки
            STATE['last_health_check_time'] = time.time()
            log.info(f"Health check: порт {TUNNEL_HOST}:{TUNNEL_PORT} доступен.")

        except ConnectionRefusedError:
            log.error(f"HEALTH CHECK FAILED: порт {TUNNEL_HOST}:{TUNNEL_PORT} не отвечает. Инициирую перезапуск.")
            telegram_handler.manual_restart_event.set()
            break
        except asyncio.CancelledError:
            log.info("Активная проверка здоровья остановлена.")
            break
        except Exception as e:
            log.error(f"Неизвестная ошибка при проверке порта: {e}")

        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECONDS)

async def manage_vk_tunnel_lifecycle():
    """Основной цикл управления жизненным циклом vk-tunnel"""
    while True:
        log.info(f"Запуск нового цикла. Следующий плановый перезапуск через {RESTART_INTERVAL_SECONDS / 3600:.1f} часов.")
        STATE.update({
            'notification_sent': False,
            'process_start_time': time.time(),
            'last_output_time': time.time(),
            'process_pid': None,
            'last_health_check_time': time.time()
        })
        telegram_handler.manual_restart_event.clear()

        try:
            process = await asyncio.create_subprocess_exec(
                *VK_TUNNEL_COMMAND,
                stdout=PIPE,
                stderr=PIPE,
                stdin=None
            )
            STATE['process_pid'] = process.pid
            log.info(f"Процесс vk-tunnel запущен с PID: {process.pid}")
        except FileNotFoundError:
            log.critical("Команда 'vk-tunnel' не найдена! Повтор через 30с...")
            await asyncio.sleep(30)
            continue
        except Exception as e:
            log.critical(f"Не удалось запустить процесс vk-tunnel: {e}. Повтор через 30с...")
            await asyncio.sleep(30)
            continue

        # Создаем задачи мониторинга
        monitor_stdout_task = asyncio.create_task(monitor_stream(process.stdout))
        monitor_stderr_task = asyncio.create_task(monitor_stream(process.stderr))
        health_check_task = asyncio.create_task(check_tunnel_health())

        # Создаем задачи ожидания событий
        wait_process_task = asyncio.create_task(process.wait())
        wait_timer_task = asyncio.create_task(asyncio.sleep(RESTART_INTERVAL_SECONDS))
        wait_command_task = asyncio.create_task(telegram_handler.manual_restart_event.wait())

        # Ждем первое событие
        done, pending = await asyncio.wait(
            [wait_process_task, wait_timer_task, wait_command_task, health_check_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Определяем причину остановки
        reason = "неизвестная причина"
        if wait_process_task in done:
            reason = f"процесс завершился сам с кодом {process.returncode}"
        elif wait_timer_task in done:
            reason = "сработал плановый таймер"
        elif wait_command_task in done:
            reason = "получена команда или сработал health check"
        elif health_check_task in done:
            reason = "health check обнаружил проблему"

        log.warning(f"Инициирован перезапуск vk-tunnel (PID: {process.pid}). Причина: {reason}.")

        # Отменяем все незавершенные задачи
        for task in pending:
            task.cancel()

        monitor_stdout_task.cancel()
        monitor_stderr_task.cancel()
        health_check_task.cancel()

        await asyncio.gather(
            monitor_stdout_task,
            monitor_stderr_task,
            health_check_task,
            return_exceptions=True
        )

        # Завершаем процесс, если он еще работает
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5)
                log.info(f"Процесс {process.pid} успешно завершен (terminate).")
            except asyncio.TimeoutError:
                log.warning(f"Процесс {process.pid} не ответил на terminate. Убиваем (kill)...")
                process.kill()
                await process.wait()

        log.info("Пауза 5 секунд перед перезапуском...")
        await asyncio.sleep(5)

async def main():
    """Главная функция"""
    log.info("Запуск менеджера vk-tunnel с управлением через Telegram.")
    log.info(f"Конфигурация: BOT_TOKEN={'*' * 10}, CHAT_ID={CHAT_ID}, ALLOWED_USER_ID={ALLOWED_USER_ID}")

    # Запускаем обе задачи параллельно
    await asyncio.gather(
        manage_vk_tunnel_lifecycle(),
        telegram_handler.listen_for_commands()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Менеджер остановлен пользователем.")
    except Exception as e:
        log.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
