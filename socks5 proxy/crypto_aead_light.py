# crypto_aead_light.py
import os
from Crypto.Cipher import AES

def aead_seal(key: bytes, plaintext: bytes) -> bytes:
    assert len(key) == 16  # AES-128
    nonce = os.urandom(12)
    c = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ct, tag = c.encrypt_and_digest(plaintext)
    return nonce + ct + tag  # 12 + len(ct) + 16

def aead_open(key: bytes, blob: bytes) -> bytes:
    assert len(key) == 16
    if len(blob) < 12 + 16:
        raise ValueError("aead blob too short")
    nonce, rest = blob[:12], blob[12:]
    ct, tag = rest[:-16], rest[-16:]
    c = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return c.decrypt_and_verify(ct, tag)
