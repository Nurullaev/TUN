# config_light.py
CONFIG = {
    "aes_key_hex": "",  # 32 hex, заменить! Ичпользуйте openssl rand -hex 16 и создайте свой ключ!
    "server": {
        "host": "127.0.0.1",
        "port": 8080
    },
    "client": {
        "socks_host": "127.0.0.1",
        "socks_port": 9443
    },
}
