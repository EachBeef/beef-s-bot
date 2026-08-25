from telethon.sync import TelegramClient
import os
from dotenv import load_dotenv

# Carrega as variáveis do .env
load_dotenv()

# Configurações iguais ao seu telegram.py
api_id = os.getenv('TELEGRAM_API_ID')
api_hash = os.getenv('TELEGRAM_API_HASH')
session_name = 'sessao_bifes_bot'  # TEM QUE SER O MESMO NOME DO SEU CÓDIGO

if not api_id or not api_hash:
    print("❌ ERRO: Não encontrei TELEGRAM_API_ID ou HASH no arquivo .env")
    exit()

print("===================================================")
print("   GERADOR DE SESSÃO TELEGRAM - BIFES BOT")
print("===================================================")

# Funções para interagir com o Console da BlazeHost
def pegar_codigo():
    print("\n👇 DIGITE O CÓDIGO QUE CHEGOU NO TELEGRAM E DÊ ENTER:")
    return input()

def pegar_senha():
    print("\n👇 (Se tiver senha 2FA) DIGITE A SENHA E DÊ ENTER:")
    return input()

def pegar_telefone():
    print("\n👇 DIGITE SEU NÚMERO (Ex: +5511999999999) E DÊ ENTER:")
    return input()

# Conecta forçando a interação
with TelegramClient(session_name, int(api_id), api_hash) as client:
    client.start(
        phone=pegar_telefone, 
        code_callback=pegar_codigo,
        password=pegar_senha
    )
    
    me = client.get_me()
    print(f"\n✅ SUCESSO! Conectado como: {me.first_name}")
    print(f"📁 Arquivo '{session_name}.session' foi criado.")
    print("🛑 AGORA VOCÊ PODE VOLTAR O STARTUP PARA O BOT.PY!")