import logging
import aiohttp
import traceback
from typing import Dict, Any

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("api")
# Включаем подробное логирование для aiohttp
logging.getLogger("aiohttp").setLevel(logging.DEBUG)

async def update_api_host(host: str, api_domain: str, api_token: str, vpn_config: Dict[str, Any]) -> bool:
    """Обновление host в API"""
    url = f"{api_domain}/api/hosts"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    # Создаем полный объект данных
    full_data = vpn_config.copy()
    full_data["host"] = host
    
    # Логируем входные данные (с маскированием токена)
    masked_token = api_token[:5] + "..." if len(api_token) > 8 else "***"
    log.debug(f"Параметры запроса: URL={url}, token={masked_token}, host={host}")
    log.debug(f"Данные конфигурации VPN: {vpn_config}")

    try:
        async with aiohttp.ClientSession() as session:
            log.debug(f"Отправка PATCH запроса на {url} с данными: {full_data}")
            
            async with session.patch(url, headers=headers, json=full_data, timeout=10) as response:
                log.debug(f"Получен ответ со статусом: {response.status}")
                log.debug(f"Заголовки ответа: {dict(response.headers)}")
                
                # Получаем полный текст ответа
                error_text = await response.text()
                
                # Пытаемся разобрать JSON
                error_json = None
                try:
                    error_json = await response.json()
                    log.debug(f"Ответ API в формате JSON: {error_json}")
                except:
                    log.debug(f"Ответ API не является JSON: {error_text}")
                
                if response.status in [200, 201, 204]:
                    log.info(f"API успешно обновлен с новым host: {host}")
                    return True
                else:
                    log.error(f"Ошибка обновления API: статус={response.status}")
                    log.error(f"Текст ответа: {error_text}")
                    if error_json:
                        log.error(f"JSON ответа: {error_json}")
                    
                    # Попробуем минимальный набор данных
                    if response.status == 400:
                        log.info("Пробую с минимальным набором данных...")
                        minimal_data = {
                            "uuid": vpn_config.get("uuid"),
                            "host": host
                        }
                        
                        log.debug(f"Повторная отправка с минимальными данными: {minimal_data}")
                        async with session.patch(url, headers=headers, json=minimal_data, timeout=10) as retry_response:
                            retry_status = retry_response.status
                            log.debug(f"Статус повторного ответа: {retry_status}")
                            
                            retry_text = await retry_response.text()
                            log.debug(f"Текст повторного ответа: {retry_text}")
                            
                            try:
                                retry_json = await retry_response.json()
                                log.debug(f"JSON повторного ответа: {retry_json}")
                            except:
                                log.debug("Повторный ответ не является JSON")
                            
                            if retry_status in [200, 201, 204]:
                                log.info(f"API успешно обновлен с минимальными данными, host: {host}")
                                return True
                            else:
                                log.error(f"Ошибка с минимальными данными: статус={retry_status}")
                                log.error(f"Текст ошибки: {retry_text}")
                    
                    return False
    except aiohttp.ClientError as ce:
        log.error(f"Ошибка клиента HTTP при обновлении API: {ce}")
        log.error(traceback.format_exc())
        return False
    except Exception as e:
        log.error(f"Неожиданное исключение при обновлении API: {e}")
        log.error(traceback.format_exc())
        return False