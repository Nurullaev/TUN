import asyncio
import logging
import os
import re
import signal
import subprocess
from typing import Optional, Dict, Any

import aiohttp
from admin import AdminManager  # Добавляем импорт

log = logging.getLogger("telegram")

class TelegramCommandHandler:
    def __init__(self, bot_token: str, allowed_user_id: int, state: Dict[str, Any]):
        self.bot_token = bot_token
        self.owner_id = allowed_user_id  # Главный администратор (владелец)
        self.state = state
        self.manual_restart_event = asyncio.Event()
        self.admin_manager = AdminManager()  # Создаем менеджер администраторов
        
        # Добавляем владельца в администраторы при первом запуске
        if allowed_user_id not in self.admin_manager.admins:
            self.admin_manager.add_admin(allowed_user_id)
    
    def is_admin(self, user_id: int) -> bool:
        """Проверка прав администратора"""
        return self.admin_manager.is_admin(user_id)
    
    def is_owner(self, user_id: int) -> bool:
        """Проверка, является ли пользователь владельцем"""
        return user_id == self.owner_id

    async def send_message(self, text: str, chat_id: str):
        """Отправка сообщения в Telegram"""
        if len(text) > 4096:
            text = text[:4090] + "\n[...]"

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload, timeout=10) as response:
                    if response.status == 200:
                        log.info(f"Сообщение в чат {chat_id} успешно отправлено.")
                    else:
                        log.error(f"Ошибка отправки в Telegram: {response.status}, {await response.text()}")
        except Exception as e:
            log.error(f"Исключение при отправке в Telegram: {e}")

    async def get_aes_key(self) -> Optional[str]:
        """Извлечение AES ключа из config_light.py"""
        try:
            with open('config_light.py', 'r', encoding='utf-8') as f:
                content = f.read()

            # Ищем паттерн "aes_key_hex": "значение"
            match = re.search(r'"aes_key_hex"\s*:\s*"([^"]*)"', content)
            if match:
                return match.group(1)
            return None
        except Exception as e:
            log.error(f"Ошибка при чтении AES ключа: {e}")
            return None

    async def restart_server(self) -> tuple[bool, str]:
        """Перезапуск server.py"""
        try:
            # Находим PID процесса server.py
            result = subprocess.run(['pgrep', '-f', 'server.py'],
                                  capture_output=True, text=True)

            if result.returncode != 0 or not result.stdout.strip():
                return False, "Процесс server.py не найден"

            pids = result.stdout.strip().split('\n')

            # Убиваем процессы
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    log.info(f"Процесс server.py (PID: {pid}) остановлен")
                except Exception as e:
                    log.error(f"Ошибка при остановке PID {pid}: {e}")

            # Ждем немного
            await asyncio.sleep(2)

            # Запускаем заново через nohup
            subprocess.Popen(['nohup', 'python', 'server.py'],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           preexec_fn=os.setpgrp)

            await asyncio.sleep(2)

            # Проверяем, что запустился
            check_result = subprocess.run(['pgrep', '-f', 'server.py'],
                                        capture_output=True, text=True)

            if check_result.returncode == 0 and check_result.stdout.strip():
                new_pids = check_result.stdout.strip().split('\n')
                return True, f"Server.py успешно перезапущен. Новые PID: {', '.join(new_pids)}"
            else:
                return False, "Не удалось запустить server.py"

        except Exception as e:
            log.error(f"Критическая ошибка при перезапуске server.py: {e}")
            return False, f"Ошибка: {str(e)}"

    async def handle_command(self, command: str, chat_id: str, user_id: int):
        """Обработка команды"""
        # Команды управления администраторами (только для владельца)
        if command.startswith("/add-admin"):
            if not self.is_owner(user_id):
                await self.send_message("❌ Только владелец может добавлять администраторов", chat_id)
                return
            
            parts = command.split()
            if len(parts) != 2:
                await self.send_message("❌ Использование: `/add-admin USER_ID`", chat_id)
                return
            
            try:
                new_admin_id = int(parts[1])
                success, message = self.admin_manager.add_admin(new_admin_id)
                if success:
                    await self.send_message(f"✅ {message}", chat_id)
                else:
                    await self.send_message(f"⚠️ {message}", chat_id)
            except ValueError:
                await self.send_message("❌ USER_ID должен быть числом", chat_id)
        
        elif command.startswith("/remove-admin"):
            if not self.is_owner(user_id):
                await self.send_message("❌ Только владелец может удалять администраторов", chat_id)
                return
            
            parts = command.split()
            if len(parts) != 2:
                await self.send_message("❌ Использование: `/remove-admin USER_ID`", chat_id)
                return
            
            try:
                admin_id = int(parts[1])
                if admin_id == self.owner_id:
                    await self.send_message("❌ Нельзя удалить владельца из администраторов", chat_id)
                    return
                
                success, message = self.admin_manager.remove_admin(admin_id)
                if success:
                    await self.send_message(f"✅ {message}", chat_id)
                else:
                    await self.send_message(f"⚠️ {message}", chat_id)
            except ValueError:
                await self.send_message("❌ USER_ID должен быть числом", chat_id)
        
        elif command == "/admin-list":
            if not self.is_admin(user_id):
                await self.send_message("❌ Доступ запрещен", chat_id)
                return
            
            admin_info = self.admin_manager.get_admin_info()
            await self.send_message(admin_info, chat_id)
        
        # Проверка доступа для критичных команд (теперь для всех администраторов)
        restricted_commands = ['/restart-tunnel', '/restart-server', '/status', '/log']
        if command in restricted_commands and not self.is_admin(user_id):
            await self.send_message("❌ Доступ запрещен.", chat_id)
            return

        if command == "/restart-tunnel":
            await self.send_message("✅ Принято! Инициирую перезапуск туннеля...", chat_id)
            self.manual_restart_event.set()

        elif command == "/restart-server":
            await self.send_message("⏳ Перезапускаю server.py...", chat_id)
            success, message = await self.restart_server()
            if success:
                await self.send_message(f"✅ {message}", chat_id)
            else:
                await self.send_message(f"❌ {message}", chat_id)

        elif command == "/status":
            if self.state.get('process_pid') and self.state.get('process_start_time'):
                import time
                uptime_seconds = int(time.time() - self.state['process_start_time'])

                # Исправляем: используем время последней активности процесса
                last_activity = self.state.get('last_health_check_time', self.state.get('process_start_time'))
                last_activity_seconds = int(time.time() - last_activity)

                status_text = (f"📊 *Статус менеджера vk-tunnel*\n\n"
                             f"PID процесса: `{self.state['process_pid']}`\n"
                             f"Время работы: `{uptime_seconds // 3600}ч {(uptime_seconds % 3600) // 60}м {uptime_seconds % 60}с`\n"
                             f"Последняя проверка здоровья: `{last_activity_seconds}с назад`\n")
                await self.send_message(status_text, chat_id)
            else:
                await self.send_message("ℹ️ Процесс vk-tunnel не запущен.", chat_id)

        elif command == "/log":
            try:
                with open('manager.log', 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                last_lines = lines[-20:]
                if not last_lines:
                    await self.send_message("ℹ️ Лог-файл пока пуст.", chat_id)
                    return

                log_output = "".join(last_lines)
                response_text = f"📄 *Последние 20 строк из лога:*\n\n```{log_output}```"
                await self.send_message(response_text, chat_id)

            except FileNotFoundError:
                await self.send_message("⚠️ Лог-файл еще не создан.", chat_id)
            except Exception as e:
                await self.send_message(f"❌ Не удалось прочитать лог-файл: {e}", chat_id)

        elif command == "/key":
            # Команда доступна всем в группе
            aes_key = await self.get_aes_key()
            if aes_key is not None:
                if aes_key:  # Если ключ не пустой
                    # Используем HTML для спойлера
                    message = f'🔐 <b>AES ключ:</b>\n\n<span class="tg-spoiler">{aes_key}</span>\n\n<i>Нажмите на затемненный текст, чтобы увидеть ключ</i>'

                    # Отправляем с HTML parse mode
                    url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}

                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.post(url, data=payload, timeout=10) as response:
                                if response.status == 200:
                                    log.info(f"AES ключ отправлен в чат {chat_id} (как спойлер)")
                                else:
                                    # Если не удалось со спойлером, отправляем обычным способом
                                    await self.send_message(f"🔐 *AES ключ:*\n`{aes_key}`", chat_id)
                    except Exception as e:
                        log.error(f"Ошибка при отправке спойлера: {e}")
                        # Fallback на обычную отправку
                        await self.send_message(f"🔐 *AES ключ:*\n`{aes_key}`", chat_id)
                else:
                    await self.send_message("ℹ️ AES ключ не установлен (пустое значение)", chat_id)
            else:
                await self.send_message("❌ Не удалось получить AES ключ из config_light.py", chat_id)

        elif command == "/help":
            # Команда помощи доступна всем
            help_text = """📋 *Доступные команды:*

/key - Получить AES ключ из конфигурации
/help - Показать это сообщение

*Команды администратора:*
/status - Статус vk-tunnel
/log - Последние 20 строк лога
/restart-tunnel - Перезапустить vk-tunnel
/restart-server - Перезапустить server.py
/admin-list - Список администраторов"""
            
            if self.is_owner(user_id):
                help_text += """

*Команды владельца:*
/add-admin USER_ID - Добавить администратора
/remove-admin USER_ID - Удалить администратора"""
            
            await self.send_message(help_text, chat_id)

        else:
            # Неизвестная команда - не отвечаем
            pass

    async def listen_for_commands(self):
        """Основной цикл прослушивания команд"""
        last_update_id = 0
        log.info("Запуск слушателя команд Telegram...")

        while True:
            try:
                async with asyncio.timeout(60):
                    url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                    params = {'offset': last_update_id + 1, 'timeout': 50}

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

                                if not (message and "text" in message):
                                    continue

                                user_id = message["from"]["id"]
                                chat_id = message["chat"]["id"]
                                command = message["text"].strip()

                                # Обрабатываем только команды (начинаются с /)
                                if command.startswith('/'):
                                    await self.handle_command(command, str(chat_id), user_id)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log.error(f"Критическая ошибка в слушателе Telegram: {e}. Перезапуск через 10с...")
                await asyncio.sleep(10)