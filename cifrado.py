"""Cifrado de los datos.

- Datos guardados (historial + sesión de Garmin): AES-256-GCM con una llave aleatoria
  de 32 bytes (secreto DATOS_KEY en GitHub, copia local en ~/.garminconnect/datos_key).
- Tablero web: AES-256-GCM con una llave derivada de tu contraseña (PBKDF2-SHA256).
  El navegador la descifra con WebCrypto; la contraseña nunca viaja ni se guarda en el repo.
"""
import base64
import gzip
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERACIONES = 600_000
b64 = lambda b: base64.b64encode(b).decode()


def llave_desde_texto(texto: str) -> bytes:
    llave = base64.b64decode(texto.strip())
    if len(llave) != 32:
        raise ValueError("DATOS_KEY debe ser 32 bytes en base64")
    return llave


def cifrar_objeto(obj, llave: bytes) -> bytes:
    nonce = os.urandom(12)
    plano = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())
    return b"SD1" + nonce + AESGCM(llave).encrypt(nonce, plano, b"salud-deporte")


def descifrar_objeto(blob: bytes, llave: bytes):
    if blob[:3] != b"SD1":
        raise ValueError("Formato desconocido")
    plano = AESGCM(llave).decrypt(blob[3:15], blob[15:], b"salud-deporte")
    return json.loads(gzip.decompress(plano))


def cifrar_para_web(texto: str, contrasena: str) -> dict:
    sal, iv = os.urandom(16), os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=ITERACIONES)
    llave = kdf.derive(contrasena.encode())
    ct = AESGCM(llave).encrypt(iv, gzip.compress(texto.encode()), None)
    return {"v": 1, "it": ITERACIONES, "s": b64(sal), "i": b64(iv), "c": b64(ct)}
