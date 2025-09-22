#!/usr/bin/env python3
# ws_gateway_light.py
import asyncio, json, socket, logging, os
import websockets

from config_light import CONFIG
from crypto_aead_light import aead_seal, aead_open

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [gw] %(message)s")
log = logging.getLogger("gw")

KEY = bytes.fromhex(CONFIG["aes_key_hex"])

async def pipe_tcp_to_ws(reader: asyncio.StreamReader, ws: websockets.WebSocketServerProtocol):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            enc = aead_seal(KEY, data)
            await ws.send(enc)
    except Exception:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass

async def pipe_ws_to_tcp(ws: websockets.WebSocketServerProtocol, writer: asyncio.StreamWriter):
    try:
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                try:
                    plain = aead_open(KEY, bytes(msg))
                except Exception:
                    continue
                writer.write(plain)
                await writer.drain()
            # текстовые кадры после OPEN игнорируем
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def handle_ws(ws: websockets.WebSocketServerProtocol):
    peer = getattr(ws, "remote_address", None)
    log.info(f"client connected: {peer}")
    # 1) ждём OPEN (текстом)
    try:
        first = await asyncio.wait_for(ws.recv(), timeout=10)
    except Exception:
        await ws.close()
        return

    if not isinstance(first, str):
        await ws.close()
        return

    try:
        obj = json.loads(first)
        addr, port = obj["addr"], int(obj["port"])
    except Exception:
        await ws.close()
        return

    # 2) TCP подключение
    try:
        reader, writer = await asyncio.open_connection(addr, port, family=socket.AF_UNSPEC)
    except Exception as e:
        log.info(f"connect to {addr}:{port} failed: {e}")
        await ws.close()
        return

    # 3) Трубы
    t1 = asyncio.create_task(pipe_tcp_to_ws(reader, ws))
    t2 = asyncio.create_task(pipe_ws_to_tcp(ws, writer))
    try:
        await asyncio.gather(t1, t2)
    finally:
        log.info(f"client disconnected: {peer}")

async def main():
    host = CONFIG["server"]["host"]
    port = CONFIG["server"]["port"]
    log.info(f"listening ws://{host}:{port}")
    async with websockets.serve(handle_ws, host, port, max_size=2**22, ping_interval=20, ping_timeout=20, compression=None):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
