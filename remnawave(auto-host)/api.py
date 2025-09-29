import logging
import aiohttp
from typing import Dict, Any

log = logging.getLogger("api")

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
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=full_data, timeout=10) as response:
                if response.status in [200, 201, 204]:
                    log.info(f"API успешно обновлен с новым host: {host}")
                    return True
                else:
                    error_text = await response.text()
                    log.error(f"Ошибка обновления API: {response.status}, {error_text}")
                    
                    # Попробуем минимальный набор данных
                    if response.status == 400:
                        log.info("Пробую с минимальным набором данных...")
                        minimal_data = {
                            "uuid": vpn_config.get("uuid"),
                            "host": host
                        }
                        
                        async with session.patch(url, headers=headers, json=minimal_data, timeout=10) as retry_response:
                            if retry_response.status in [200, 201, 204]:
                                log.info(f"API успешно обновлен с минимальными данными, host: {host}")
                                return True
                            else:
                                retry_error = await retry_response.text()
                                log.error(f"Ошибка с минимальными данными: {retry_response.status}, {retry_error}")
                    
                    return False
    except Exception as e:
        log.error(f"Исключение при обновлении API: {e}")
        return False