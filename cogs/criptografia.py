import os
import hmac
import hashlib
import secrets
import base64
from dotenv import load_dotenv

load_dotenv()

# Chave mestra obtida do .env ou gerada de forma persistente
MASTER_SECRET = os.getenv("ENCRYPTION_SECRET_KEY", "bifes_secret_master_key_2026_encryption_seed_9842")

def _derivar_chaves(salt: bytes):
    """ Deriva uma chave de encriptação (32 bytes) e uma chave de HMAC (32 bytes) usando PBKDF2 """
    derivada = hashlib.pbkdf2_hmac('sha256', MASTER_SECRET.encode('utf-8'), salt, 50000, 64)
    return derivada[:32], derivada[32:]

def _gerar_keystream(enc_key: bytes, iv: bytes, tamanho: int) -> bytes:
    """ Gera fluxo de bytes pseudoaleatório com HMAC-SHA256 em modo contador """
    keystream = bytearray()
    counter = 0
    while len(keystream) < tamanho:
        bloco = hmac.new(enc_key, iv + counter.to_bytes(4, 'big'), hashlib.sha256).digest()
        keystream.extend(bloco)
        counter += 1
    return bytes(keystream[:tamanho])

def encriptar_dado(texto: str) -> str:
    """ Encripta um texto sensível (ex: chave de API do Twitter/Threads) com autenticação HMAC-SHA256 """
    if not texto:
        return ""
    
    texto_bytes = texto.encode('utf-8')
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(16)
    
    enc_key, hmac_key = _derivar_chaves(salt)
    keystream = _gerar_keystream(enc_key, iv, len(texto_bytes))
    
    ciphertext = bytes(a ^ b for a, b in zip(texto_bytes, keystream))
    tag = hmac.new(hmac_key, salt + iv + ciphertext, hashlib.sha256).digest()
    
    payload = salt + iv + tag + ciphertext
    return "enc_v1:" + base64.urlsafe_b64encode(payload).decode('ascii')

def decriptar_dado(texto_cifrado: str) -> str:
    """ Decripta e valida a integridade de uma credencial armazenada """
    if not texto_cifrado or not texto_cifrado.startswith("enc_v1:"):
        return texto_cifrado or ""
    
    try:
        raw_b64 = texto_cifrado[7:]
        payload = base64.urlsafe_b64decode(raw_b64.encode('ascii'))
        
        if len(payload) < 16 + 16 + 32:
            return ""
        
        salt = payload[:16]
        iv = payload[16:32]
        tag = payload[32:64]
        ciphertext = payload[64:]
        
        enc_key, hmac_key = _derivar_chaves(salt)
        
        expected_tag = hmac.new(hmac_key, salt + iv + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            print("⚠️ [Criptografia] Falha de integridade ao decriptar dado (tag inválida).")
            return ""
        
        keystream = _gerar_keystream(enc_key, iv, len(ciphertext))
        decrypted_bytes = bytes(a ^ b for a, b in zip(ciphertext, keystream))
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        print(f"⚠️ [Criptografia] Erro ao decriptar: {e}")
        return ""

def gerar_hash_senha(senha: str):
    """ Gera um salt seguro e o hash PBKDF2 da senha """
    salt = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt.encode('utf-8'), 100000)
    return hash_bytes.hex(), salt

def verificar_hash_senha(senha: str, hash_hex: str, salt: str) -> bool:
    """ Valida a senha contra o hash e salt armazenados em tempo constante """
    if not senha or not hash_hex or not salt:
        return False
    calc_hash = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return hmac.compare_digest(calc_hash, hash_hex)
