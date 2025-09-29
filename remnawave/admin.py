import json
import os
import logging
from typing import List, Optional

log = logging.getLogger("admin")

class AdminManager:
    def __init__(self, admin_file: str = "admins.json"):
        self.admin_file = admin_file
        self.admins = self.load_admins()
        
    def load_admins(self) -> List[int]:
        """Загрузка списка администраторов из файла"""
        if os.path.exists(self.admin_file):
            try:
                with open(self.admin_file, 'r') as f:
                    data = json.load(f)
                    admins = [int(admin_id) for admin_id in data.get('admins', [])]
                    log.info(f"Загружено {len(admins)} администраторов")
                    return admins
            except Exception as e:
                log.error(f"Ошибка при загрузке администраторов: {e}")
                return []
        else:
            log.info("Файл администраторов не найден, создаю новый")
            return []
    
    def save_admins(self):
        """Сохранение списка администраторов в файл"""
        try:
            with open(self.admin_file, 'w') as f:
                json.dump({'admins': self.admins}, f, indent=2)
            log.info(f"Список администраторов сохранен ({len(self.admins)} записей)")
        except Exception as e:
            log.error(f"Ошибка при сохранении администраторов: {e}")
    
    def add_admin(self, user_id: int) -> tuple[bool, str]:
        """Добавление администратора"""
        if user_id in self.admins:
            return False, f"Пользователь {user_id} уже является администратором"
        
        self.admins.append(user_id)
        self.save_admins()
        return True, f"Пользователь {user_id} добавлен в администраторы"
    
    def remove_admin(self, user_id: int) -> tuple[bool, str]:
        """Удаление администратора"""
        if user_id not in self.admins:
            return False, f"Пользователь {user_id} не является администратором"
        
        self.admins.remove(user_id)
        self.save_admins()
        return True, f"Пользователь {user_id} удален из администраторов"
    
    def is_admin(self, user_id: int) -> bool:
        """Проверка, является ли пользователь администратором"""
        return user_id in self.admins
    
    def get_admin_list(self) -> List[int]:
        """Получение списка всех администраторов"""
        return self.admins.copy()
    
    def get_admin_info(self) -> str:
        """Получение информации об администраторах для отображения"""
        if not self.admins:
            return "Список администраторов пуст"
        
        admin_list = "\n".join([f"• `{admin_id}`" for admin_id in self.admins])
        return f"👥 *Администраторы ({len(self.admins)}):*\n\n{admin_list}"