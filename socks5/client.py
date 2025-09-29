#!/usr/bin/env python3
import asyncio, json, socket, ssl, argparse, logging, os
from urllib.parse import urlparse
import websockets

from config_light import CONFIG
from crypto_aead_light import aead_seal, aead_open

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [cli] %(message)s")
log = logging.getLogger("cli")

KEY = bytes.fromhex(CONFIG["aes_key_hex"])

async def forward_tcp_to_ws(reader: asyncio.StreamReader, ws: websockets.WebSocketClientProtocol):
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

async def forward_ws_to_tcp(ws: websockets.WebSocketClientProtocol, writer: asyncio.StreamWriter):
    try:
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                try:
                    plain = aead_open(KEY, bytes(msg))
                except Exception:
                    continue
                try:
                    writer.write(plain)
                    await writer.drain()
                except Exception:
                    break
            # текст после OPEN игнорируем
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def handle_socks(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, remote_wss: str, origin: str):
    cid = None
    try:
        # SOCKS5 greeting
        ver_nm = await reader.readexactly(2)
        ver, nmethods = ver_nm[0], ver_nm[1]
        _ = await reader.readexactly(nmethods)
        writer.write(b"\x05\x00"); await writer.drain()

        # request
        req = await reader.readexactly(4)
        ver, cmd, _, atyp = req
        if ver != 0x05 or cmd != 0x01:
            writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00"); await writer.drain(); writer.close(); return

        if atyp == 0x01:
            addr = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
        elif atyp == 0x03:
            ln = (await reader.readexactly(1))[0]
            addr = (await reader.readexactly(ln)).decode('utf-8','ignore')
        elif atyp == 0x04:
            addr = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
        else:
            writer.write(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00"); await writer.drain(); writer.close(); return
        port = int.from_bytes(await reader.readexactly(2), 'big')

        # WS connect
        u = urlparse(remote_wss)
        ws_kwargs = dict(max_size=2**22, ping_interval=20, ping_timeout=20, compression=None, origin=origin)
        if u.scheme == "wss":
            ws_kwargs["ssl"] = ssl.create_default_context()
        else:
            ws_kwargs["ssl"] = None

        async with websockets.connect(remote_wss, **ws_kwargs) as ws:
            # OPEN (текстом)
            open_obj = {"addr": addr, "port": port}
            await ws.send(json.dumps(open_obj, separators=(",",":")))

            # ответ SOCKS OK
            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00"); await writer.drain()

            t1 = asyncio.create_task(forward_tcp_to_ws(reader, ws))
            t2 = asyncio.create_task(forward_ws_to_tcp(ws, writer))
            await asyncio.gather(t1, t2)

    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        log.warning(f"SOCKS error: {e}")
    finally:
        try:
            writer.close()
        except Exception:
            pass

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wss", required=True, help="WSS URL от vk-tunnel (например wss://<host>/)")
    ap.add_argument("--origin", default=None, help="Origin заголовок; по умолчанию https://<host>")
    args = ap.parse_args()

    remote_wss = args.wss
    u = urlparse(remote_wss)
    if not u.scheme.startswith("ws") or not u.hostname:
        raise SystemExit("--wss должен быть ws:// или wss:// с хостом")

    origin = args.origin or f"https://{u.hostname}"
    host, port = CONFIG["client"]["socks_host"], CONFIG["client"]["socks_port"]
    log.info(f"SOCKS5 listening on socks5://{host}:{port} -> {remote_wss} (Origin={origin})")

    srv = await asyncio.start_server(lambda r,w: handle_socks(r,w,remote_wss,origin), host, port)
    async with srv:
        await srv.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
