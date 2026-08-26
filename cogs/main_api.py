import discord
from discord.ext import commands
from fastapi import FastAPI, HTTPException, Request, Header, WebSocket, WebSocketDisconnect, Query, Depends
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from cogs.criptografia import encriptar_dado, decriptar_dado, gerar_hash_senha, verificar_hash_senha
import sqlite3
import uvicorn
import asyncio
import os
import secrets
import threading
import httpx
import tweepy
import requests 
import random 
import json
import math
import time
import mercadopago
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Dict, List

# --- CONFIGURAÇÕES ---
load_dotenv()

PORTA = 28052
SENHA_ADMIN = "EachBeef241"
TOKEN_ADMIN = secrets.token_hex(16)

# Bancos de Dados
DB_BIFINHOS = "bifinhos.db"
DB_PROMO = "bifes_links.db"
COOLDOWN_SECONDS = 8 * 60 * 60  # 8 horas

# Chaves API (Do seu .env)
TT_API_KEY = os.getenv('TT_API_KEY')
TT_API_SECRET = os.getenv('TT_API_SECRET')
TT_ACCESS_TOKEN = os.getenv('TT_ACCESS_TOKEN')
TT_ACCESS_SECRET = os.getenv('TT_ACCESS_SECRET')
THREADS_USER_ID = os.getenv('THREADS_USER_ID')
THREADS_ACCESS_TOKEN = os.getenv('THREADS_ACCESS_TOKEN')
ML_CHANNEL_ID = os.getenv('ML_CHANNEL_ID')
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "921518902138269746")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET") 

# SDK do Mercado Pago
mp_sdk = mercadopago.SDK(os.getenv("MP_ACCESS_TOKEN"))

# --- INICIALIZAÇÃO DO FASTAPI ---
app = FastAPI(title="Bifes Super API", version="4.6") # Versão Final (Guildas + Palavras Limpas)

# Configuração CORS ampla (permite qualquer origem http/https para evitar bloqueios no frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?:\/\/.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root_status():
    bot = getattr(app.state, "bot_instance", None)
    return {
        "status": "online",
        "api": "Bifes Super API",
        "version": "4.6",
        "bot_ready": bot.is_ready() if bot else False
    }

# --- FUNÇÕES DE BANCO DE DADOS ---

def get_db_bifinhos():
    conn = sqlite3.connect(DB_BIFINHOS, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;') 
    conn.row_factory = sqlite3.Row
    return conn

def get_db_promo():
    conn = sqlite3.connect(DB_PROMO, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;') 
    conn.row_factory = sqlite3.Row
    return conn

def init_dbs():
    with get_db_bifinhos() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS bifinhos (
                user_id TEXT PRIMARY KEY, 
                balance INTEGER NOT NULL, 
                last_claim INTEGER NOT NULL
            )
        ''')
        # Atualizações seguras (não apaga os dados de quem já tem bifinhos)
        try:
            conn.execute("ALTER TABLE bifinhos ADD COLUMN tier_vip INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE bifinhos ADD COLUMN expira_em INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass # As colunas já existem

        try:
            conn.execute("ALTER TABLE bifinhos ADD COLUMN lembrete_ativo INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
            
        try:
            conn.execute("ALTER TABLE bifinhos ADD COLUMN aviso_8h INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
            
        try:
            conn.execute("ALTER TABLE bifinhos ADD COLUMN aviso_20h INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        conn.execute('''
            CREATE TABLE IF NOT EXISTS partidas_xadrez (
                sala_id TEXT PRIMARY KEY,
                jogador1_id TEXT,
                senha1 TEXT,
                jogador2_id TEXT,
                senha2 TEXT,
                valor INTEGER,
                status TEXT,
                vencedor_id TEXT,
                fen TEXT DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
            )
        ''')
        
        # Migração automática para renomear a coluna se ela ainda existir com o nome antigo
        try:
            conn.execute("ALTER TABLE partidas_xadrez RENAME COLUMN aposta TO valor")
        except sqlite3.OperationalError:
            pass
            
        try:
            conn.execute("ALTER TABLE partidas_xadrez ADD COLUMN fen TEXT DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'")
        except sqlite3.OperationalError:
            pass

        # Nova Tabela para Boost de Servidores
        conn.execute('''
            CREATE TABLE IF NOT EXISTS servidores_boost (
                guild_id TEXT PRIMARY KEY,
                booster_user_id TEXT,
                multiplicador REAL,
                expira_em INTEGER
            )
        ''')

        # Nova Tabela para Relatório Mensal (Competição)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS historico_mensal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                mes_ano TEXT NOT NULL,
                quantidade INTEGER NOT NULL,
                tipo_ganho TEXT NOT NULL,
                data_timestamp INTEGER NOT NULL
            )
        ''')
        
        # --- TABELA NOVA: GUILDAS ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS guildas (
                owner_id TEXT PRIMARY KEY,
                text_channel_id TEXT,
                voice_channel_id TEXT
            )
        ''')

        # --- TABELA SAAS: LICENÇAS E AFILIADOS MULTI-TENANT ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS licencas_afiliados (
                chave_licenca TEXT PRIMARY KEY,
                discord_user_id TEXT,
                nome_usuario TEXT,
                guild_id TEXT,
                canal_discord_id TEXT,
                tag_amazon TEXT,
                tag_ml TEXT,
                tag_shopee TEXT,
                tag_magalu TEXT,
                twitter_api_key_enc TEXT,
                twitter_api_secret_enc TEXT,
                twitter_access_token_enc TEXT,
                twitter_access_secret_enc TEXT,
                threads_user_id_enc TEXT,
                threads_access_token_enc TEXT,
                status TEXT DEFAULT 'ativo',
                expira_em INTEGER,
                criado_em INTEGER
            )
        ''')

        # --- TABELA DE USUÁRIOS (LOGIN & SENHA) ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS usuarios_afiliados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                chave_licenca TEXT,
                nome TEXT,
                discord_user_id TEXT,
                canal_discord_id TEXT,
                tag_amazon TEXT,
                tag_ml TEXT,
                tag_shopee TEXT,
                tag_magalu TEXT,
                twitter_api_key_enc TEXT,
                twitter_api_secret_enc TEXT,
                twitter_access_token_enc TEXT,
                twitter_access_secret_enc TEXT,
                threads_user_id_enc TEXT,
                threads_access_token_enc TEXT,
                status TEXT DEFAULT 'trial',
                expira_em INTEGER DEFAULT 0,
                criado_em INTEGER
            )
        ''')

        # --- CRIA / ATUALIZA CONTAS DE SUPERADMIN VITALÍCIO ---
        admin_hash, admin_salt = gerar_hash_senha(SENHA_ADMIN)
        now_ts = int(time.time())
        exp_infinito = 253370764800 # Ano 9999 (Infinito)
        
        for super_user in ["admin", "eachbeef"]:
            conn.execute('''
                INSERT INTO usuarios_afiliados (username, email, password_hash, salt, chave_licenca, nome, status, expira_em, criado_em)
                VALUES (?, 'admin@bifes.com.br', ?, ?, 'BIFES_PRO_MASTER_INFINITO', 'SuperAdmin Master', 'superadmin', ?, ?)
                ON CONFLICT(username) DO UPDATE SET 
                    password_hash=excluded.password_hash, 
                    salt=excluded.salt, 
                    status='superadmin', 
                    expira_em=excluded.expira_em
            ''', (super_user, admin_hash, admin_salt, exp_infinito, now_ts))
            
        conn.execute('''
            INSERT INTO licencas_afiliados (chave_licenca, nome_usuario, status, expira_em, criado_em)
            VALUES ('BIFES_PRO_MASTER_INFINITO', 'SuperAdmin Master', 'superadmin', ?, ?)
            ON CONFLICT(chave_licenca) DO UPDATE SET status='superadmin', expira_em=excluded.expira_em
        ''', (exp_infinito, now_ts))

init_dbs()

# --- FUNÇÃO AUXILIAR PARA REGISTRAR GANHOS ---
def registrar_ganho_mensal(user_id: str, quantidade: int, tipo_ganho: str):
    now = datetime.now()
    mes_ano = now.strftime("%m/%Y") # Ex: "03/2026"
    timestamp = int(now.timestamp())
    
    conn = get_db_bifinhos()
    conn.execute('''
        INSERT INTO historico_mensal (user_id, mes_ano, quantidade, tipo_ganho, data_timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, mes_ano, quantidade, tipo_ganho, timestamp))
    conn.commit()
    conn.close()


# --- MODELOS DE DADOS ---
class ClaimRequest(BaseModel):
    userId: str
    username: str 

class LoginRequest(BaseModel):
    senha: str

class AprovarRequest(BaseModel):
    mlb_id: str
    novo_link: str
    descricao_extra: Optional[str] = ""
    novo_titulo: Optional[str] = ""
    nova_descricao: Optional[str] = ""
    cupom: Optional[str] = ""
    preco_de: Optional[str] = ""
    preco_por: Optional[str] = ""
    postar_discord: bool = True
    postar_twitter: bool = False
    postar_threads: bool = False

class PostarDiretoRequest(BaseModel):
    titulo: str
    link: str
    preco_de: Optional[str] = ""
    preco_por: Optional[str] = ""
    descricao_extra: Optional[str] = ""
    cupom: Optional[str] = ""
    loja: Optional[str] = "Mercado Livre"
    vendedor: Optional[str] = ""
    imagem_url: Optional[str] = ""
    postar_discord: bool = True
    postar_twitter: bool = False
    postar_threads: bool = False

class CapturarRequest(BaseModel):
    titulo: str
    link_original: str
    link_afiliado: Optional[str] = ""
    preco_de: Optional[str] = ""
    preco_por: Optional[str] = ""
    descricao_extra: Optional[str] = ""
    cupom: Optional[str] = ""
    loja: Optional[str] = "Mercado Livre"
    vendedor: Optional[str] = ""
    imagem_url: Optional[str] = ""

class XadrezLoginRequest(BaseModel):
    sala_id: str
    senha: str

class XadrezTerminarRequest(BaseModel):
    sala_id: str
    senha: str  
    vencedor_id: str  
    motivo: Optional[str] = "xeque-mate" 

class PagamentoRequest(BaseModel):
    discord_id: str
    item_id: str
    titulo: str
    preco: float

class ToggleLembreteRequest(BaseModel):
    user_id: str
    ativo: int

# --- MODELOS SAAS: LICENÇAS E CONFIGURAÇÕES MULTI-TENANT ---

class SalvarConfigLicencaRequest(BaseModel):
    chave_licenca: str
    nome_usuario: Optional[str] = ""
    guild_id: Optional[str] = ""
    canal_discord_id: Optional[str] = ""
    tag_amazon: Optional[str] = ""
    tag_ml: Optional[str] = ""
    tag_shopee: Optional[str] = ""
    tag_magalu: Optional[str] = ""
    # Credenciais do Twitter (serão encriptadas antes de salvar)
    twitter_api_key: Optional[str] = ""
    twitter_api_secret: Optional[str] = ""
    twitter_access_token: Optional[str] = ""
    twitter_access_secret: Optional[str] = ""
    # Credenciais do Threads (serão encriptadas antes de salvar)
    threads_user_id: Optional[str] = ""
    threads_access_token: Optional[str] = ""

class CheckoutLicencaRequest(BaseModel):
    chave_licenca: Optional[str] = ""
    discord_user_id: Optional[str] = "anonimo"
    nome_usuario: Optional[str] = ""

class GerarTrialRequest(BaseModel):
    discord_user_id: str
    nome_usuario: Optional[str] = ""
    canal_discord_id: Optional[str] = ""
    guild_id: Optional[str] = ""

class PostarLicencaRequest(BaseModel):
    chave_licenca: str
    titulo: str
    link: str
    preco_de: Optional[str] = ""
    preco_por: Optional[str] = ""
    descricao_extra: Optional[str] = ""
    cupom: Optional[str] = ""
    loja: Optional[str] = "Mercado Livre"
    vendedor: Optional[str] = ""
    imagem_url: Optional[str] = ""
    postar_discord: bool = True
    postar_twitter: bool = False
    postar_threads: bool = False

# --- MODELOS DE AUTENTICAÇÃO COM USUÁRIO E SENHA ---

class CadastroUsuarioRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = ""
    nome: Optional[str] = ""

class LoginContaRequest(BaseModel):
    username: str
    password: str

class ResgatarCodigoCompraRequest(BaseModel):
    codigo: str

class GerarCodigosAdminRequest(BaseModel):
    quantidade: int = 1
    dias: int = 30

# ==========================================
#  ROTAS: MERCADO PAGO E SISTEMA VIP
# ==========================================

@app.post("/api/pagamento/gerar")
def gerar_pagamento(data: PagamentoRequest):
    preference_data = {
        "items": [
            {
                "id": data.item_id,
                "title": f"Bifes Bot - {data.titulo}",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": data.preco
            }
        ],
        "external_reference": data.discord_id,
        "notification_url": "https://api.bifes.com.br/api/pagamento/webhook",
        "back_urls": {
            "success": "https://bifes.com.br/loja",
            "failure": "https://bifes.com.br/loja",
            "pending": "https://bifes.com.br/loja"
        },
        "auto_return": "approved"
    }

    preference_response = mp_sdk.preference().create(preference_data)
    return {"link_pagamento": preference_response["response"]["init_point"]}


@app.post("/api/pagamento/webhook")
async def webhook_mercadopago(request: Request):
    data = await request.json()
    
    if data.get("type") == "payment" or data.get("action") == "payment.created":
        try:
            payment_id = data.get("data", {}).get("id")
            payment_info = mp_sdk.payment().get(payment_id)
            payment = payment_info["response"]
            
            if payment.get("status") == "approved":
                ext_ref = payment.get("external_reference")
                itens = payment.get("additional_info", {}).get("items", [])
                
                if ext_ref and itens:
                    item_comprado = itens[0].get("id")
                    
                    # 1. RENOVAÇÃO DE LICENÇA SAAS DE AFILIADOS (R$ 20/MÊS)
                    if ext_ref.startswith("BIFES_PRO_") or item_comprado == "plano_pro_afiliados":
                        processar_renovacao_licenca(ext_ref)
                    else:
                        # 2. SISTEMA VIP CONVENCIONAL
                        bot = app.state.bot_instance
                        if bot:
                            asyncio.run_coroutine_threadsafe(
                                processar_entrega_vip(bot, ext_ref, item_comprado),
                                bot.loop
                            )
        except Exception as e:
            print(f"Erro no Webhook: {e}")

    return {"status": "ok"}

def processar_renovacao_licenca(chave_licenca: str):
    """ Adiciona +30 dias na licença do cliente ao confirmar o pagamento """
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT expira_em FROM licencas_afiliados WHERE chave_licenca = ?", (chave_licenca,))
    row = c.fetchone()
    
    now_ts = int(time.time())
    base_ts = now_ts
    if row and row['expira_em'] and row['expira_em'] > now_ts:
        base_ts = row['expira_em'] # Se ainda estava ativa, acumula +30 dias a partir da data futura
        
    novo_expira_em = base_ts + (30 * 24 * 60 * 60)
    
    if row:
        c.execute("UPDATE licencas_afiliados SET expira_em = ?, status = 'ativo' WHERE chave_licenca = ?", (novo_expira_em, chave_licenca))
    else:
        c.execute("""
            INSERT INTO licencas_afiliados (chave_licenca, status, expira_em, criado_em)
            VALUES (?, 'ativo', ?, ?)
        """, (chave_licenca, novo_expira_em, now_ts))
        
    conn.commit()
    conn.close()
    print(f"💎 [SaaS] Licença renovada com sucesso por +30 dias: {chave_licenca}")


async def processar_entrega_vip(bot, discord_id: str, item_id: str):
    # !!! ATENÇÃO: COLOQUE SEU GUILD_ID REAL AQUI !!!
    GUILD_ID = 123456789012345678 # ID do seu servidor oficial
    
    CARGOS = {
        "vip_1": 1478010799183368202,
        "vip_2": 1478011479457402982,
        "vip_3": 1478011439397736498,
        "donate_1": 44444444444444444,
        "donate_2": 44444444444444444,
        "donate_3": 44444444444444444,
        "donate_4": 44444444444444444,
        "donate_5": 44444444444444444,
        "donate_6": 44444444444444444 
    }
    
    TIERS = {"vip_1": 1, "vip_2": 2, "vip_3": 3}
    BIFINHOS_POR_DOACAO = {
        "donate_1": 25000,
        "donate_2": 90000,
        "donate_3": 300000,
        "donate_4": 850000,
        "donate_5": 1900000,
        "donate_6": 4000000
    }
    
    try:
        guild = bot.get_guild(GUILD_ID)
        member = guild.get_member(int(discord_id)) or await guild.fetch_member(int(discord_id)) if guild else None
        
        if item_id in TIERS:
            tier = TIERS[item_id]
            expira_em = int(time.time()) + (30 * 24 * 60 * 60)
            
            conn = get_db_bifinhos()
            conn.execute('''
                INSERT INTO bifinhos (user_id, balance, last_claim, tier_vip, expira_em) 
                VALUES (?, 0, 0, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                tier_vip=excluded.tier_vip, expira_em=excluded.expira_em
            ''', (discord_id, tier, expira_em))
            conn.commit()
            conn.close()
            
            if member and item_id in CARGOS:
                cargo = guild.get_role(CARGOS[item_id])
                if cargo: await member.add_roles(cargo)
                
                embed = discord.Embed(title="💎 Título Nobre Ativado!", description="Seu plano VIP foi ativado com sucesso! Aproveite seus multiplicadores.", color=0x2ecc71)
                await member.send(embed=embed)
                
                if item_id == "vip_3":
                    try:
                        from cogs.guildas import GuildaPanel
                        conn = get_db_bifinhos()
                        guilda_existe = conn.execute("SELECT * FROM guildas WHERE owner_id = ?", (str(member.id),)).fetchone()
                        
                        if not guilda_existe:
                            categoria = discord.utils.get(guild.categories, name="👑 GUILDAS")
                            if not categoria:
                                categoria = await guild.create_category("👑 GUILDAS")

                            overwrites = {
                                guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
                                member: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, move_members=True)
                            }

                            txt_channel = await categoria.create_text_channel(f"💬・guilda-do-{member.name.lower()}", overwrites=overwrites)
                            voc_channel = await categoria.create_voice_channel(f"🔊・Call do {member.display_name}", overwrites=overwrites, user_limit=20)

                            conn.execute("INSERT INTO guildas (owner_id, text_channel_id, voice_channel_id) VALUES (?, ?, ?)", 
                                         (str(member.id), str(txt_channel.id), str(voc_channel.id)))
                            conn.commit()

                            embed_painel = discord.Embed(
                                title="👑 Painel do Imperador",
                                description="Esta é a sua Base de Operações!\n\nUse os botões abaixo para gerenciar seus amigos, escolher quem entra, e como sua sala de voz vai se chamar.",
                                color=0xffd700
                            )
                            embed_painel.set_footer(text="Sua Guilda tem um limite de 20 vagas na sala de voz.")
                            
                            msg = await txt_channel.send(content=member.mention, embed=embed_painel, view=GuildaPanel())
                            await msg.pin()
                        conn.close()
                    except Exception as eg:
                        print(f"Erro ao criar guilda para {discord_id}: {eg}")

        elif item_id.startswith("donate_"):
            if member:
                cargo = guild.get_role(CARGOS.get(item_id))
                if cargo: await member.add_roles(cargo)
                
                embed = discord.Embed(title="🥩 Doação Recebida!", description="Muito obrigado pelo seu apoio! Seu cargo exclusivo já foi entregue.", color=0xff9900)
                await member.send(embed=embed)
            
            if item_id in BIFINHOS_POR_DOACAO:
                qtd_bifinhos = BIFINHOS_POR_DOACAO[item_id]
                conn = get_db_bifinhos()
                conn.execute('''
                    INSERT INTO bifinhos (user_id, balance, last_claim) 
                    VALUES (?, ?, 0)
                    ON CONFLICT(user_id) DO UPDATE SET 
                    balance = balance + ?
                ''', (discord_id, qtd_bifinhos, qtd_bifinhos))
                conn.commit()
                conn.close()
                registrar_ganho_mensal(discord_id, qtd_bifinhos, "comprado")
            
    except Exception as e:
        print(f"Erro ao entregar recompensa Discord: {e}")

# ==========================================
#  LÓGICA MATEMÁTICA DOS BIFINHOS
# ==========================================

def calcular_multiplicador(tier_vip: int, max_server_boost: float):
    multiplicador_pessoal = 1.0
    if tier_vip == 1: multiplicador_pessoal = 1.5
    elif tier_vip == 2: multiplicador_pessoal = 2.0
    elif tier_vip == 3: multiplicador_pessoal = 3.0

    if tier_vip == 0:
        return max_server_boost
    else:
        bonus_extra_servidor = max_server_boost - 1.0
        return multiplicador_pessoal + (bonus_extra_servidor / 2.0)

# ==========================================
#  ROTAS: BIFINHOS E LEMBRETES
# ==========================================

@app.post("/claim")
def claim_bifinhos(data: ClaimRequest):
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT balance, last_claim, tier_vip, expira_em FROM bifinhos WHERE user_id = ?", (data.userId,))
    row = c.fetchone()
    
    current_balance = row['balance'] if row else 0
    last_claim_ts = row['last_claim'] if row else 0
    tier_vip = row['tier_vip'] if row and 'tier_vip' in row.keys() else 0
    expira_em = row['expira_em'] if row and 'expira_em' in row.keys() else 0
    
    now = datetime.now()
    now_ts = int(now.timestamp())
    
    if expira_em > 0 and now_ts > expira_em:
        tier_vip = 0
        expira_em = 0
        c.execute("UPDATE bifinhos SET tier_vip = 0, expira_em = 0 WHERE user_id = ?", (data.userId,))
        conn.commit()

    cd_atual = COOLDOWN_SECONDS

    if last_claim_ts > 0:
        last_claim_date = datetime.fromtimestamp(last_claim_ts)
        diff = (now - last_claim_date).total_seconds()
        
        if diff < (cd_atual - 2):
            conn.close()
            return {
                "status": "error", 
                "error": "Cooldown", 
                "message": "⏳ Você ainda precisa esperar!", 
                "seconds_left": cd_atual - diff
            }

    max_server_boost = 1.0
    booster_id = None 
    
    bot = app.state.bot_instance
    if bot:
        boosts = c.execute("SELECT guild_id, multiplicador, booster_user_id FROM servidores_boost WHERE expira_em > ?", (now_ts,)).fetchall()
        for b in boosts:
            guild = bot.get_guild(int(b['guild_id']))
            if guild and guild.get_member(int(data.userId)):
                if b['multiplicador'] > max_server_boost:
                    max_server_boost = b['multiplicador']
                    booster_id = b['booster_user_id'] 

    multiplicador_final = calcular_multiplicador(tier_vip, max_server_boost)
    recompensa_base = random.randint(250, 1000)
    
    msg_extra = ""
    is_raro = False
    if random.random() < 0.05:
        recompensa_base += 500
        is_raro = True
        msg_extra = "🎉 BÔNUS MÁXIMO! Recompensa Rara de +500 bifinhos base!"

    reward = math.floor(recompensa_base * multiplicador_final)
    new_balance = current_balance + reward
    
    c.execute('''
        INSERT INTO bifinhos (user_id, balance, last_claim, tier_vip, expira_em, aviso_8h) 
        VALUES (?, ?, ?, ?, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET 
        balance=excluded.balance, last_claim=excluded.last_claim, aviso_8h=0
    ''', (data.userId, new_balance, now_ts, tier_vip, expira_em))
    conn.commit()
    conn.close() 

    registrar_ganho_mensal(data.userId, reward, "diario")
    
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT user_id FROM bifinhos ORDER BY balance DESC")
    rows = c.fetchall()
    rank = next((i + 1 for i, r in enumerate(rows) if r['user_id'] == data.userId), None)
    conn.close()

    if max_server_boost > 1.0 and tier_vip == 0:
        msg_extra += f" 🚀 Você ganhou um bônus de {max_server_boost}x por estar em um servidor upado!"

    return {
        "status": "success",
        "reward": reward,
        "new_balance": new_balance,
        "rank": rank,
        "message_extra": msg_extra.strip(),
        "details": {
            "base": recompensa_base,
            "is_raro": is_raro,
            "tier_vip": tier_vip,
            "server_boost": max_server_boost,
            "booster_id": booster_id,
            "multiplicador_final": multiplicador_final
        }
    }


@app.get("/balance/{user_id}")
def get_balance(user_id: str):
    conn = get_db_bifinhos()
    row = conn.execute("SELECT balance, last_claim FROM bifinhos WHERE user_id = ?", (user_id,)).fetchone()
    
    rows = conn.execute("SELECT user_id FROM bifinhos ORDER BY balance DESC").fetchall()
    rank = next((i + 1 for i, r in enumerate(rows) if r['user_id'] == user_id), None)
    conn.close()
    
    bal = row['balance'] if row else 0
    lc = row['last_claim'] if row else 0
    return {"balance": bal, "last_claim": lc, "rank": rank}


@app.get("/api/lembrete/{user_id}")
def get_lembrete_status(user_id: str):
    conn = get_db_bifinhos()
    try:
        row = conn.execute("SELECT lembrete_ativo FROM bifinhos WHERE user_id = ?", (user_id,)).fetchone()
        status = row['lembrete_ativo'] if row and 'lembrete_ativo' in row.keys() else 0
    except Exception as e:
        print(f"Erro ao buscar status do lembrete: {e}")
        status = 0
    finally:
        conn.close()
        
    return {"lembrete_ativo": status}

@app.post("/api/lembrete/toggle")
def toggle_lembrete(data: ToggleLembreteRequest):
    conn = get_db_bifinhos()
    c = conn.cursor()
    
    c.execute("SELECT balance FROM bifinhos WHERE user_id = ?", (data.user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO bifinhos (user_id, balance, last_claim, lembrete_ativo) VALUES (?, 0, 0, ?)", (data.user_id, data.ativo))
    else:
        c.execute("UPDATE bifinhos SET lembrete_ativo = ? WHERE user_id = ?", (data.ativo, data.user_id))
        
    conn.commit()
    conn.close()
    return {"status": "success", "lembrete_ativo": data.ativo}

@app.post("/auth/discord/callback")
async def discord_auth(request: Request):
    data = await request.json()
    code = data.get("code")
    if not code: raise HTTPException(400, "Código faltando")
    
    if not DISCORD_CLIENT_SECRET:
        print("❌ ERRO CRÍTICO: Adicione DISCORD_CLIENT_SECRET no .env")
        raise HTTPException(500, "Erro interno de configuração")

    REDIRECT_URI = "https://www.bifes.com.br/bifinhos"

    async with httpx.AsyncClient() as client:
        payload = {
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "scope": "identify guilds guilds.join email"
        }
        
        try:
            token_res = await client.post("https://discord.com/api/oauth2/token", data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
            
            if token_res.status_code != 200:
                print(f"Erro Token Discord: {token_res.text}")
                raise HTTPException(400, "Falha na autenticação com Discord")
                
            access_token = token_res.json().get("access_token")
            user_res = await client.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"})
            
            if user_res.status_code != 200:
                raise HTTPException(400, "Falha ao pegar dados do usuário")
                
            return {"user": user_res.json()}
            
        except Exception as e:
            print(f"Exceção Auth: {e}")
            raise HTTPException(500, "Erro interno na autenticação")


# ==========================================
#  ROTAS: XADREZ VIP (Site) & WEBSOCKETS
# ==========================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, sala_id: str):
        await websocket.accept()
        if sala_id not in self.active_connections:
            self.active_connections[sala_id] = []
        self.active_connections[sala_id].append(websocket)

    def disconnect(self, websocket: WebSocket, sala_id: str):
        if sala_id in self.active_connections:
            self.active_connections[sala_id].remove(websocket)
            if not self.active_connections[sala_id]:
                del self.active_connections[sala_id]

    async def broadcast_to_room(self, sala_id: str, message: dict):
        if sala_id in self.active_connections:
            for connection in self.active_connections[sala_id]:
                await connection.send_text(json.dumps(message))

manager = ConnectionManager()

@app.websocket("/ws/xadrez/{sala_id}")
async def websocket_xadrez(websocket: WebSocket, sala_id: str):
    await manager.connect(websocket, sala_id)
    try:
        while True:
            data = await websocket.receive_text()
            jogada = json.loads(data)
            
            if "fen" in jogada:
                conn = get_db_bifinhos()
                conn.execute("UPDATE partidas_xadrez SET fen = ? WHERE sala_id = ?", (jogada["fen"], sala_id))
                conn.commit()
                conn.close()
            
            await manager.broadcast_to_room(sala_id, jogada)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, sala_id)


@app.post("/api/xadrez/login")
def xadrez_login(data: XadrezLoginRequest):
    conn = get_db_bifinhos()
    row = conn.execute("SELECT * FROM partidas_xadrez WHERE sala_id = ?", (data.sala_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, "Sala não encontrada.")

    if row['status'] != 'pendente':
        raise HTTPException(400, f"Esta partida já foi encerrada ou expirou (Status: {row['status']}).")

    fen_atual = row['fen'] if 'fen' in row.keys() else 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

    if data.senha == row['senha1']:
        return {
            "status": "success", "cor": "brancas", "jogador_id": row['jogador1_id'], 
            "oponente_id": row['jogador2_id'], "valor": row['valor'], "fen": fen_atual
        }
    elif data.senha == row['senha2']:
        return {
            "status": "success", "cor": "pretas", "jogador_id": row['jogador2_id'], 
            "oponente_id": row['jogador1_id'], "valor": row['valor'], "fen": fen_atual
        }
    else:
        raise HTTPException(401, "Senha de 6 dígitos incorreta.")

@app.post("/api/xadrez/terminar")
def xadrez_terminar(data: XadrezTerminarRequest):
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT * FROM partidas_xadrez WHERE sala_id = ?", (data.sala_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        raise HTTPException(404, "Sala não encontrada.")

    if row['status'] != 'pendente':
        conn.close()
        raise HTTPException(400, "A partida já foi finalizada pelo outro jogador.")

    if data.senha != row['senha1'] and data.senha != row['senha2']:
        conn.close()
        raise HTTPException(401, "Não autorizado. Falha de segurança na senha.")

    c.execute("UPDATE partidas_xadrez SET status = 'finalizada', vencedor_id = ? WHERE sala_id = ?", (data.vencedor_id, data.sala_id))
    
    valor_individual = row['valor']
    jogador1 = row['jogador1_id']
    jogador2 = row['jogador2_id']
    anuncio_msg = ""
    
    if data.vencedor_id == 'empate':
        c.execute("UPDATE bifinhos SET balance = balance + ? WHERE user_id = ?", (valor_individual, jogador1))
        c.execute("UPDATE bifinhos SET balance = balance + ? WHERE user_id = ?", (valor_individual, jogador2))
        anuncio_msg = f"🤝 O Desafio de Estratégia entre <@{jogador1}> e <@{jogador2}> terminou em **Empate**! Os {valor_individual} 🥩 de cada um foram devolvidos."
    else:
        pote_total = valor_individual * 2
        perdedor = jogador2 if data.vencedor_id == jogador1 else jogador1
        c.execute("UPDATE bifinhos SET balance = balance + ? WHERE user_id = ?", (pote_total, data.vencedor_id))
        
        conn.commit()
        conn.close()
        registrar_ganho_mensal(data.vencedor_id, valor_individual, "xadrez")
        
        if data.motivo == 'tempo':
            anuncio_msg = f"⏳ **VITÓRIA POR ABANDONO!** O jogador <@{perdedor}> demorou demais ou fugiu da partida! <@{data.vencedor_id}> venceu por tempo e levou o bônus de **{pote_total} Bifinhos**! 🥩"
        else:
            anuncio_msg = f"🏆 **XEQUE-MATE!** O jogador <@{data.vencedor_id}> humilhou <@{perdedor}> no Desafio de Estratégia e levou o bônus de **{pote_total} Bifinhos**! 🥩"

    if 'conn' in locals() and conn:
        try: conn.close()
        except: pass

    bot = app.state.bot_instance
    if bot:
        canal_xadrez_id = 123456789012345678 
        channel = bot.get_channel(canal_xadrez_id)
        if channel:
            asyncio.run_coroutine_threadsafe(channel.send(anuncio_msg), bot.loop)

    return {"status": "success", "message": "Partida encerrada com sucesso! Pontos na conta."}

# ==========================================
#  ROTAS: PROMOÇÕES (Admin & Multi-Usuário)
# ==========================================

@app.post("/api/admin/login")
def admin_login(data: LoginRequest):
    senha_limpa = data.senha.strip()
    
    # 1. Master Admin Global
    if senha_limpa == SENHA_ADMIN:
        return {
            "token": TOKEN_ADMIN,
            "role": "admin",
            "nome": "Administrador Master",
            "valido": True,
            "msg": "Login Master realizado com sucesso!"
        }
        
    # 2. Login de Afiliado por Chave de Licença
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT * FROM licencas_afiliados WHERE chave_licenca = ?", (senha_limpa,))
    row = c.fetchone()
    conn.close()
    
    if row:
        now_ts = int(time.time())
        expira_em = row['expira_em'] or 0
        dias_restantes = max(0, int((expira_em - now_ts) / (24 * 60 * 60)))
        is_valido = now_ts <= expira_em
        
        return {
            "token": senha_limpa,
            "role": "cliente",
            "licenca": senha_limpa,
            "nome": row['nome_usuario'] or "Afiliado Pro",
            "dias_restantes": dias_restantes,
            "expira_em": datetime.fromtimestamp(expira_em).strftime("%d/%m/%Y") if expira_em > 0 else "Nunca",
            "valido": is_valido,
            "canal_discord_id": row['canal_discord_id'] or "",
            "tags": {
                "amazon": row['tag_amazon'] or "",
                "ml": row['tag_ml'] or "",
                "shopee": row['tag_shopee'] or "",
                "magalu": row['tag_magalu'] or ""
            },
            "msg": "Login de Afiliado realizado com sucesso!"
        }
        
    raise HTTPException(401, "Senha de Administrador ou Chave de Licença inválida.")

@app.get("/api/admin/pendencias")
def get_pendencias(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "Não autorizado")
        
    is_master = (authorization == TOKEN_ADMIN or authorization == SENHA_ADMIN)
    licenca_row = None
    
    if not is_master:
        conn_lic = get_db_bifinhos()
        c = conn_lic.cursor()
        c.execute("SELECT * FROM licencas_afiliados WHERE chave_licenca = ?", (authorization.strip(),))
        licenca_row = c.fetchone()
        conn_lic.close()
        if not licenca_row:
            raise HTTPException(401, "Licença não autorizada")
            
    conn = get_db_promo()
    try:
        rows = conn.execute('''
            SELECT mlb_id, nome, meu_link, ultima_notificacao, vendedor, url_original, titulo_ia, descricao_oferta, loja_origem 
            FROM produtos ORDER BY ultima_notificacao DESC LIMIT 40
        ''').fetchall()
    except Exception as e:
        conn.close()
        raise HTTPException(500, f"Erro DB Promo: {str(e)}")
        
    conn.close()
    
    lista = []
    for row in rows:
        link_final = row['url_original'] if row['url_original'] else f"https://mercadolivre.com.br/p/{row['mlb_id']}"
        meu_link_custom = row['meu_link'] or ""
        
        # Se for um cliente com tags salvas, pré-aplica a tag de afiliado dele
        if licenca_row and not meu_link_custom:
            loja = (row['loja_origem'] or "").lower()
            if "amazon" in loja and licenca_row['tag_amazon']:
                meu_link_custom = f"{link_final.split('?')[0]}?tag={licenca_row['tag_amazon']}"
            elif "mercado" in loja and licenca_row['tag_ml']:
                sep = "&" if "?" in link_final else "?"
                meu_link_custom = f"{link_final}{sep}tag={licenca_row['tag_ml']}"
                
        lista.append({
            "mlb_id": row['mlb_id'],
            "nome": row['nome'],
            "meu_link": meu_link_custom,
            "link_original": link_final,
            "ultima_notificacao": row['ultima_notificacao'],
            "vendedor": row['vendedor'] or "Desconhecido",
            "titulo_ia": row['titulo_ia'],
            "descricao": row['descricao_oferta'],
            "loja": row['loja_origem'] or "Mercado Livre"
        })
    return lista

@app.get("/api/admin/todas_licencas")
def get_todas_licencas(authorization: str = Header(None)):
    """ Endpoint exclusivo do Master Admin para gerenciar todas as licenças """
    if authorization != TOKEN_ADMIN and authorization != SENHA_ADMIN:
        raise HTTPException(401, "Acesso restrito ao Master Admin")
        
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT chave_licenca, discord_user_id, nome_usuario, canal_discord_id, status, expira_em, criado_em FROM licencas_afiliados ORDER BY criado_em DESC")
    rows = c.fetchall()
    conn.close()
    
    now_ts = int(time.time())
    res = []
    for r in rows:
        exp = r['expira_em'] or 0
        dias = max(0, int((exp - now_ts) / (24 * 60 * 60)))
        res.append({
            "chave_licenca": r['chave_licenca'],
            "discord_user_id": r['discord_user_id'] or "Não informado",
            "nome_usuario": r['nome_usuario'] or "Afiliado",
            "canal_discord_id": r['canal_discord_id'] or "",
            "status": "ativo" if now_ts <= exp else "expirado",
            "dias_restantes": dias,
            "expira_em": datetime.fromtimestamp(exp).strftime("%d/%m/%Y") if exp > 0 else "Nunca",
            "criado_em": datetime.fromtimestamp(r['criado_em']).strftime("%d/%m/%Y") if r['criado_em'] else ""
        })
    return res

class AdicionarDiasRequest(BaseModel):
    chave_licenca: str
    dias: int

@app.post("/api/admin/licenca/adicionar_dias")
def adicionar_dias_licenca(data: AdicionarDiasRequest, authorization: str = Header(None)):
    if authorization != TOKEN_ADMIN and authorization != SENHA_ADMIN:
        raise HTTPException(401, "Acesso restrito ao Master Admin")
        
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT expira_em FROM licencas_afiliados WHERE chave_licenca = ?", (data.chave_licenca.strip(),))
    row = c.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(404, "Licença não encontrada")
        
    now_ts = int(time.time())
    base_ts = max(now_ts, row['expira_em'] or now_ts)
    novo_exp = base_ts + (data.dias * 24 * 60 * 60)
    
    c.execute("UPDATE licencas_afiliados SET expira_em = ?, status = 'ativo' WHERE chave_licenca = ?", (novo_exp, data.chave_licenca.strip()))
    conn.commit()
    conn.close()
    
    return {"status": "success", "msg": f"Adicionados +{data.dias} dias à licença {data.chave_licenca}!"}

def baixar_imagem_url(url: str, mlb_id: str):
    if not url: return None
    try:
        if not os.path.exists("imagens_temp"):
            os.makedirs("imagens_temp")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            caminho = f"imagens_temp/{mlb_id}.jpg"
            with open(caminho, "wb") as f:
                f.write(res.content)
            return caminho
    except Exception as e:
        print(f"Erro ao baixar imagem da URL ({url}): {e}")
    return None

@app.get("/api/admin/imagem/{mlb_id}")
def get_imagem_promo(mlb_id: str):
    caminho = f"imagens_temp/{mlb_id}.jpg"
    if os.path.exists(caminho):
        return FileResponse(caminho, media_type="image/jpeg")
    raise HTTPException(404, "Imagem não encontrada")

@app.post("/api/admin/postar_direto")
def postar_direto(data: PostarDiretoRequest, authorization: str = Header(None)):
    if authorization != TOKEN_ADMIN and authorization != SENHA_ADMIN:
        raise HTTPException(401, "Não autorizado")
    
    mlb_id = f"ext_{int(time.time())}_{random.randint(100, 999)}"
    
    # Baixa imagem se fornecida
    if data.imagem_url:
        baixar_imagem_url(data.imagem_url, mlb_id)
        
    # Salva no banco de dados
    conn = get_db_promo()
    try:
        descricao_completa = data.preco_por or ""
        if data.preco_de and data.preco_por:
            descricao_completa = f"De: {data.preco_de} Por: {data.preco_por}"
        if data.cupom:
            descricao_completa += f" (Cupom: {data.cupom})"
            
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute('''
            INSERT INTO produtos (mlb_id, nome, meu_link, ultima_notificacao, vendedor, url_original, loja_origem, descricao_oferta, titulo_ia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mlb_id) DO UPDATE SET meu_link=excluded.meu_link, titulo_ia=excluded.titulo_ia
        ''', (mlb_id, data.titulo, data.link, now_str, data.vendedor or "Loja Oficial", data.link, data.loja or "Mercado Livre", descricao_completa, data.titulo))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar no banco: {e}")
    finally:
        conn.close()

    bot = app.state.bot_instance
    if bot:
        row_dict = {
            "mlb_id": mlb_id,
            "vendedor": data.vendedor or "Loja Oficial",
            "loja_origem": data.loja or "Mercado Livre"
        }
        if data.postar_discord:
            asyncio.run_coroutine_threadsafe(postar_discord(bot, row_dict, data), bot.loop)
        if data.postar_twitter:
            threading.Thread(target=executar_post_twitter, args=(data,)).start()
        if data.postar_threads:
            threading.Thread(target=executar_post_threads, args=(data,)).start()

    return {"status": "success", "mlb_id": mlb_id, "msg": "Oferta postada com sucesso!"}

@app.post("/api/admin/capturar")
def capturar_oferta(data: CapturarRequest, authorization: str = Header(None)):
    if authorization != TOKEN_ADMIN and authorization != SENHA_ADMIN:
        raise HTTPException(401, "Não autorizado")
        
    mlb_id = f"ext_{int(time.time())}_{random.randint(100, 999)}"
    
    if data.imagem_url:
        baixar_imagem_url(data.imagem_url, mlb_id)
        
    conn = get_db_promo()
    try:
        descricao_completa = data.preco_por or ""
        if data.preco_de and data.preco_por:
            descricao_completa = f"De: {data.preco_de} Por: {data.preco_por}"
        if data.cupom:
            descricao_completa += f" (Cupom: {data.cupom})"
            
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute('''
            INSERT INTO produtos (mlb_id, nome, meu_link, ultima_notificacao, vendedor, url_original, loja_origem, descricao_oferta, titulo_ia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (mlb_id, data.titulo, data.link_afiliado or "", now_str, data.vendedor or "Loja Oficial", data.link_original, data.loja or "Mercado Livre", descricao_completa, data.titulo))
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(500, f"Erro ao salvar: {str(e)}")
    conn.close()
    
    return {"status": "success", "mlb_id": mlb_id, "msg": "Oferta capturada e salva na fila!"}

@app.post("/api/admin/aprovar")
def aprovar_oferta(data: AprovarRequest, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "Não autorizado")
        
    is_master = (authorization == TOKEN_ADMIN or authorization == SENHA_ADMIN)
    licenca_row = None
    
    if not is_master:
        conn_lic = get_db_bifinhos()
        c = conn_lic.cursor()
        c.execute("SELECT * FROM licencas_afiliados WHERE chave_licenca = ?", (authorization.strip(),))
        licenca_row = c.fetchone()
        conn_lic.close()
        if not licenca_row:
            raise HTTPException(401, "Não autorizado")
            
        now_ts = int(time.time())
        if not licenca_row['expira_em'] or now_ts > licenca_row['expira_em']:
            raise HTTPException(403, "Licença expirada.")
    
    conn = get_db_promo()
    try:
        conn.execute("UPDATE produtos SET meu_link = ?, titulo_ia = ?, descricao_oferta = ? WHERE mlb_id = ?", 
                     (data.novo_link, data.novo_titulo, data.nova_descricao, data.mlb_id))
        conn.commit()
        row = conn.execute("SELECT vendedor, loja_origem FROM produtos WHERE mlb_id = ?", (data.mlb_id,)).fetchone()
        conn.close()
    except Exception as e:
        conn.close()
        raise HTTPException(500, f"Erro Banco: {str(e)}")

    bot = app.state.bot_instance
    if bot:
        if is_master:
            if data.postar_discord:
                asyncio.run_coroutine_threadsafe(postar_discord(bot, row, data), bot.loop)
            if data.postar_twitter:
                threading.Thread(target=executar_post_twitter, args=(data,)).start()
            if data.postar_threads:
                threading.Thread(target=executar_post_threads, args=(data,)).start()
        else:
            # Posta no canal e redes do cliente
            canal_dest = int(licenca_row['canal_discord_id']) if licenca_row['canal_discord_id'] else int(ML_CHANNEL_ID)
            if data.postar_discord:
                asyncio.run_coroutine_threadsafe(postar_discord_cliente(bot, canal_dest, licenca_row, data, data.mlb_id), bot.loop)
            if data.postar_twitter and licenca_row['twitter_api_key_enc']:
                threading.Thread(target=executar_post_twitter_cliente, args=(licenca_row, data, data.mlb_id)).start()
            if data.postar_threads and licenca_row['threads_access_token_enc']:
                threading.Thread(target=executar_post_threads_cliente, args=(licenca_row, data)).start()

    return {"msg": "Processado com sucesso"}

# ==========================================
#  LÓGICA DE POSTAGEM E EMBEDS
# ==========================================

CORES_LOJAS = {
    "Amazon": 0xFF9900,
    "Mercado Livre": 0xFFE600,
    "Shopee": 0xEE4D2D,
    "Magalu": 0x0086FF,
    "Magazine Luiza": 0x0086FF,
    "Kabum": 0xFF6500,
    "AliExpress": 0xE62E04,
    "Geral": 0x5865F2
}

class LinkView(discord.ui.View):
    def __init__(self, url: str, label: str = "🛒 Comprar com Desconto"):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))

def get_twitter_api():
    if not all([TT_API_KEY, TT_API_SECRET, TT_ACCESS_TOKEN, TT_ACCESS_SECRET]): return None, None
    try:
        auth = tweepy.OAuth1UserHandler(TT_API_KEY, TT_API_SECRET, TT_ACCESS_TOKEN, TT_ACCESS_SECRET)
        return tweepy.API(auth), tweepy.Client(consumer_key=TT_API_KEY, consumer_secret=TT_API_SECRET, access_token=TT_ACCESS_TOKEN, access_token_secret=TT_ACCESS_SECRET)
    except: return None, None

async def postar_discord(bot, row, data):
    channel = bot.get_channel(int(ML_CHANNEL_ID))
    if not channel: 
        print(f"⚠️ [Discord] Canal ML_CHANNEL_ID ({ML_CHANNEL_ID}) não encontrado.")
        return
    
    loja = (row['loja_origem'] if isinstance(row, sqlite3.Row) or isinstance(row, dict) and 'loja_origem' in row else getattr(data, 'loja', None)) or "Mercado Livre"
    vendedor = (row['vendedor'] if isinstance(row, sqlite3.Row) or isinstance(row, dict) and 'vendedor' in row else getattr(data, 'vendedor', None)) or "Loja Verificada"
    mlb_id = getattr(data, 'mlb_id', None) or (row['mlb_id'] if isinstance(row, dict) and 'mlb_id' in row else 'oferta')

    titulo = getattr(data, 'novo_titulo', None) or getattr(data, 'titulo', '🔥 Grande Oferta!')
    link = getattr(data, 'novo_link', None) or getattr(data, 'link', '')
    desc_extra = getattr(data, 'descricao_extra', '')
    nova_desc = getattr(data, 'nova_descricao', '')
    cupom = getattr(data, 'cupom', '')
    preco_de = getattr(data, 'preco_de', '')
    preco_por = getattr(data, 'preco_por', '')

    cor_embed = CORES_LOJAS.get(loja, 0xFFDB15)
    
    linhas = []
    if desc_extra:
        linhas.append(f"⚡ **{desc_extra}**\n")
    
    if preco_de and preco_por:
        linhas.append(f"❌ De: ~~{preco_de}~~\n💰 **Por: {preco_por}**")
    elif preco_por:
        linhas.append(f"💰 **Preço: {preco_por}**")
    elif nova_desc:
        linhas.append(f"💰 **{nova_desc}**")
        
    if cupom:
        linhas.append(f"\n🎟️ Use o cupom: `{cupom}`")
        
    if link:
        linhas.append(f"\n🛒 **Link:** [Clique aqui para comprar]({link})")
        
    embed = discord.Embed(
        title=titulo,
        description="\n".join(linhas),
        color=cor_embed,
        timestamp=datetime.now()
    )
    embed.set_footer(text=f"Loja: {loja} • Vendedor: {vendedor} | Bifes Bot")
    
    img_path = f"imagens_temp/{mlb_id}.jpg"
    view = LinkView(url=link) if link else None
    
    if os.path.exists(img_path):
        file = discord.File(img_path, filename="oferta.jpg")
        embed.set_image(url="attachment://oferta.jpg")
        if view:
            await channel.send(file=file, embed=embed, view=view)
        else:
            await channel.send(file=file, embed=embed)
    else:
        img_url = getattr(data, 'imagem_url', None)
        if img_url:
            embed.set_image(url=img_url)
        if view:
            await channel.send(embed=embed, view=view)
        else:
            await channel.send(embed=embed)

def executar_post_twitter(data):
    api_v1, client_v2 = get_twitter_api()
    if not api_v1: return
    
    titulo = getattr(data, 'novo_titulo', None) or getattr(data, 'titulo', '🔥 Grande Oferta!')
    link = getattr(data, 'novo_link', None) or getattr(data, 'link', '')
    desc_extra = getattr(data, 'descricao_extra', '')
    nova_desc = getattr(data, 'nova_descricao', '') or getattr(data, 'preco_por', '')
    cupom = getattr(data, 'cupom', '')
    mlb_id = getattr(data, 'mlb_id', 'oferta')
    
    txt = f"🔥 {titulo}\n\n"
    if desc_extra: txt += f"{desc_extra}\n"
    if nova_desc: txt += f"{nova_desc.replace('**','')}\n"
    if cupom: txt += f"🎟️ Cupom: {cupom}\n"
    txt += f"\n🛒 {link}"
    
    if len(txt) > 275: txt = txt[:270] + "..."
    
    media_id = None
    img_path = f"imagens_temp/{mlb_id}.jpg"
    if os.path.exists(img_path):
        try: media_id = api_v1.media_upload(img_path).media_id
        except: pass
    
    try: client_v2.create_tweet(text=txt, media_ids=[media_id] if media_id else None)
    except Exception as e: print(f"Erro Twitter: {e}")

def executar_post_threads(data):
    if not THREADS_USER_ID or not THREADS_ACCESS_TOKEN: return
    titulo = getattr(data, 'novo_titulo', None) or getattr(data, 'titulo', '🔥 Grande Oferta!')
    link = getattr(data, 'novo_link', None) or getattr(data, 'link', '')
    desc_extra = getattr(data, 'descricao_extra', '')
    nova_desc = getattr(data, 'nova_descricao', '') or getattr(data, 'preco_por', '')
    cupom = getattr(data, 'cupom', '')
    
    txt = f"{titulo}\n\n"
    if desc_extra: txt += f"{desc_extra}\n"
    if nova_desc: txt += f"{nova_desc}\n"
    if cupom: txt += f"🎟️ Cupom: {cupom}\n"
    txt += f"\nConfira: {link}"
    
    try:
        url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
        res = requests.post(url, params={'media_type': 'TEXT', 'text': txt, 'access_token': THREADS_ACCESS_TOKEN})
        if res.status_code == 200:
            requests.post(f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish", 
                          params={'creation_id': res.json()['id'], 'access_token': THREADS_ACCESS_TOKEN})
    except Exception as e: print(f"Erro Threads: {e}")

# ===================================================
#  ROTAS DE AUTENTICAÇÃO COM USUÁRIO, SENHA E CÓDIGOS
# ===================================================

SESSOES_ATIVAS: Dict[str, dict] = {}

@app.post("/api/auth/cadastro")
def cadastrar_usuario(data: CadastroUsuarioRequest):
    user_limpo = data.username.strip().lower()
    if len(user_limpo) < 3:
        raise HTTPException(400, "O nome de usuário deve ter pelo menos 3 caracteres.")
    if len(data.password) < 4:
        raise HTTPException(400, "A senha deve ter pelo menos 4 caracteres.")
        
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT id FROM usuarios_afiliados WHERE username = ?", (user_limpo,))
    if c.fetchone():
        conn.close()
        raise HTTPException(400, "Este nome de usuário já está em uso.")
        
    pw_hash, salt = gerar_hash_senha(data.password)
    now_ts = int(time.time())
    chave_pessoal = f"BIFES_PRO_{secrets.token_hex(6).upper()}"
    expira_em = now_ts + (3 * 24 * 60 * 60) # 3 Dias de Trial Grátis automático
    
    c.execute("""
        INSERT INTO usuarios_afiliados (username, email, password_hash, salt, chave_licenca, nome, status, expira_em, criado_em)
        VALUES (?, ?, ?, ?, ?, ?, 'trial', ?, ?)
    """, (user_limpo, data.email.strip() if data.email else "", pw_hash, salt, chave_pessoal, data.nome or data.username, expira_em, now_ts))
    
    # Cria também na tabela de licenças para compatibilidade com a extensão
    c.execute("""
        INSERT INTO licencas_afiliados (chave_licenca, nome_usuario, status, expira_em, criado_em)
        VALUES (?, ?, 'trial', ?, ?)
        ON CONFLICT(chave_licenca) DO NOTHING
    """, (chave_pessoal, data.nome or data.username, expira_em, now_ts))
    
    conn.commit()
    conn.close()
    
    token = f"usr_{secrets.token_hex(20)}"
    SESSOES_ATIVAS[token] = {
        "username": user_limpo,
        "chave_licenca": chave_pessoal,
        "role": "cliente",
        "nome": data.nome or data.username
    }
    
    return {
        "status": "success",
        "token": token,
        "username": user_limpo,
        "nome": data.nome or data.username,
        "chave_licenca": chave_pessoal,
        "role": "cliente",
        "dias_restantes": 3,
        "expira_em": datetime.fromtimestamp(expira_em).strftime("%d/%m/%Y"),
        "valido": True,
        "msg": "Cadastro realizado com sucesso! Você ganhou 3 dias de Teste Grátis."
    }

@app.post("/api/auth/login")
def login_usuario(data: LoginContaRequest):
    user_limpo = data.username.strip().lower()
    senha_limpa = data.password.strip()
    
    # 1. Login Master Admin Direto
    if (user_limpo in ["admin", "eachbeef"] and senha_limpa == SENHA_ADMIN) or (senha_limpa == SENHA_ADMIN and not user_limpo):
        token = TOKEN_ADMIN
        return {
            "status": "success",
            "token": token,
            "username": "admin",
            "role": "admin",
            "nome": "SuperAdmin Master",
            "chave_licenca": "BIFES_PRO_MASTER_INFINITO",
            "dias_restantes": "Vitalício",
            "expira_em": "Infinito",
            "valido": True,
            "msg": "Login SuperAdmin realizado com sucesso!"
        }
        
    # 2. Login por Usuário / Senha no Banco
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT * FROM usuarios_afiliados WHERE username = ? OR email = ?", (user_limpo, user_limpo))
    row = c.fetchone()
    
    if row:
        if verificar_hash_senha(senha_limpa, row['password_hash'], row['salt']) or senha_limpa == SENHA_ADMIN:
            is_super = (row['status'] == 'superadmin' or user_limpo in ["admin", "eachbeef"])
            now_ts = int(time.time())
            expira_em = row['expira_em'] or 0
            dias_restantes = "Vitalício" if is_super else max(0, int((expira_em - now_ts) / (24 * 60 * 60)))
            is_valido = True if is_super else (now_ts <= expira_em)
            
            token = TOKEN_ADMIN if is_super else f"usr_{secrets.token_hex(20)}"
            SESSOES_ATIVAS[token] = {
                "username": row['username'],
                "chave_licenca": row['chave_licenca'],
                "role": "admin" if is_super else "cliente",
                "nome": "SuperAdmin Master" if is_super else (row['nome'] or row['username'])
            }
            conn.close()
            
            return {
                "status": "success",
                "token": token,
                "username": row['username'],
                "nome": "SuperAdmin Master" if is_super else (row['nome'] or row['username']),
                "chave_licenca": row['chave_licenca'] or "",
                "role": "admin" if is_super else "cliente",
                "dias_restantes": dias_restantes,
                "expira_em": "Infinito" if is_super else (datetime.fromtimestamp(expira_em).strftime("%d/%m/%Y") if expira_em > 0 else "Expirado"),
                "valido": is_valido,
                "canal_discord_id": row['canal_discord_id'] or "",
                "tags": {
                    "amazon": row['tag_amazon'] or "",
                    "ml": row['tag_ml'] or "",
                    "shopee": row['tag_shopee'] or "",
                    "magalu": row['tag_magalu'] or ""
                },
                "msg": "Login realizado com sucesso!"
            }
            
    conn.close()
    raise HTTPException(401, "Usuário ou senha incorretos.")

@app.post("/api/licenca/resgatar_codigo")
def resgatar_codigo_compra(data: ResgatarCodigoCompraRequest, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "Faça login para resgatar seu código.")
        
    codigo_limpo = data.codigo.strip().upper()
    sessao = SESSOES_ATIVAS.get(authorization)
    username = sessao["username"] if sessao else None
    
    conn = get_db_bifinhos()
    c = conn.cursor()
    
    # 1. Procura na tabela de códigos de compra
    c.execute("SELECT * FROM codigos_compra WHERE codigo = ? AND status = 'disponivel'", (codigo_limpo,))
    cod_row = c.fetchone()
    
    dias_adicionar = 30
    
    if cod_row:
        dias_adicionar = cod_row['dias'] or 30
        c.execute("UPDATE codigos_compra SET status = 'resgatado', usado_por = ?, usado_em = ? WHERE codigo = ?", 
                  (username or "cliente", int(time.time()), codigo_limpo))
    else:
        # 2. Caso seja uma chave gerada pelo Mercado Pago (BIFES_PRO_...)
        c.execute("SELECT * FROM licencas_afiliados WHERE chave_licenca = ?", (codigo_limpo,))
        lic_row = c.fetchone()
        if not lic_row:
            conn.close()
            raise HTTPException(404, "Código de ativação inválido ou já resgatado.")
            
    now_ts = int(time.time())
    
    # Atualiza o usuário
    if username:
        c.execute("SELECT expira_em, chave_licenca FROM usuarios_afiliados WHERE username = ?", (username,))
        u_row = c.fetchone()
        if u_row:
            base_ts = max(now_ts, u_row['expira_em'] or now_ts)
            novo_exp = base_ts + (dias_adicionar * 24 * 60 * 60)
            c.execute("UPDATE usuarios_afiliados SET expira_em = ?, status = 'pro' WHERE username = ?", (novo_exp, username))
            if u_row['chave_licenca']:
                c.execute("UPDATE licencas_afiliados SET expira_em = ?, status = 'ativo' WHERE chave_licenca = ?", (novo_exp, u_row['chave_licenca']))
                
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "dias_adicionados": dias_adicionar,
        "msg": f"🎉 Parabéns! Código ativado com sucesso. Foram adicionados +{dias_adicionar} dias de Plano Pro à sua conta!"
    }

@app.post("/api/admin/gerar_codigos")
def gerar_codigos_admin(data: GerarCodigosAdminRequest, authorization: str = Header(None)):
    if authorization != TOKEN_ADMIN and authorization != SENHA_ADMIN:
        raise HTTPException(401, "Acesso restrito ao Master Admin.")
        
    conn = get_db_bifinhos()
    c = conn.cursor()
    novos = []
    now_ts = int(time.time())
    
    for _ in range(max(1, min(data.quantidade, 50))):
        code = f"BIFES_PRO_{secrets.token_hex(4).upper()}"
        c.execute("INSERT INTO codigos_compra (codigo, dias, status, criado_em) VALUES (?, ?, 'disponivel', ?)", 
                  (code, data.dias, now_ts))
        novos.append(code)
        
    conn.commit()
    conn.close()
    return {"status": "success", "codigos": novos, "dias_cada": data.dias}

@app.get("/api/licenca/verificar")
def verificar_licenca(chave: str = Query(...)):
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT * FROM licencas_afiliados WHERE chave_licenca = ?", (chave.strip(),))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return {
            "status": "invalido",
            "valido": False,
            "mensagem": "Chave de licença não encontrada."
        }
        
    now_ts = int(time.time())
    expira_em = row['expira_em'] or 0
    dias_restantes = max(0, int((expira_em - now_ts) / (24 * 60 * 60)))
    
    is_ativo = now_ts <= expira_em
    status_label = "ativo" if is_ativo else "expirado"
    
    data_expira_str = datetime.fromtimestamp(expira_em).strftime("%d/%m/%Y") if expira_em > 0 else "Nunca"
    
    has_twitter = bool(row['twitter_api_key_enc'] and row['twitter_access_token_enc'])
    has_threads = bool(row['threads_user_id_enc'] and row['threads_access_token_enc'])
    
    return {
        "status": status_label,
        "valido": is_ativo,
        "dias_restantes": dias_restantes,
        "expira_em": data_expira_str,
        "plano": "PRO",
        "canal_discord_id": row['canal_discord_id'] or "",
        "tags": {
            "amazon": row['tag_amazon'] or "",
            "ml": row['tag_ml'] or "",
            "shopee": row['tag_shopee'] or "",
            "magalu": row['tag_magalu'] or ""
        },
        "integracoes": {
            "twitter_conectado": has_twitter,
            "threads_conectado": has_threads
        }
    }

@app.post("/api/licenca/salvar_configuracoes")
def salvar_configuracoes_licenca(data: SalvarConfigLicencaRequest):
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT * FROM licencas_afiliados WHERE chave_licenca = ?", (data.chave_licenca.strip(),))
    row = c.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(404, "Licença não encontrada.")
        
    # Criptografa credenciais sensíveis antes de persistir
    tw_key_enc = encriptar_dado(data.twitter_api_key) if data.twitter_api_key else row['twitter_api_key_enc']
    tw_sec_enc = encriptar_dado(data.twitter_api_secret) if data.twitter_api_secret else row['twitter_api_secret_enc']
    tw_tok_enc = encriptar_dado(data.twitter_access_token) if data.twitter_access_token else row['twitter_access_token_enc']
    tw_toksec_enc = encriptar_dado(data.twitter_access_secret) if data.twitter_access_secret else row['twitter_access_secret_enc']
    
    th_uid_enc = encriptar_dado(data.threads_user_id) if data.threads_user_id else row['threads_user_id_enc']
    th_tok_enc = encriptar_dado(data.threads_access_token) if data.threads_access_token else row['threads_access_token_enc']
    
    c.execute("""
        UPDATE licencas_afiliados SET
            nome_usuario = coalesce(nullif(?, ''), nome_usuario),
            guild_id = coalesce(nullif(?, ''), guild_id),
            canal_discord_id = coalesce(nullif(?, ''), canal_discord_id),
            tag_amazon = ?,
            tag_ml = ?,
            tag_shopee = ?,
            tag_magalu = ?,
            twitter_api_key_enc = ?,
            twitter_api_secret_enc = ?,
            twitter_access_token_enc = ?,
            twitter_access_secret_enc = ?,
            threads_user_id_enc = ?,
            threads_access_token_enc = ?
        WHERE chave_licenca = ?
    """, (
        data.nome_usuario, data.guild_id, data.canal_discord_id,
        data.tag_amazon, data.tag_ml, data.tag_shopee, data.tag_magalu,
        tw_key_enc, tw_sec_enc, tw_tok_enc, tw_toksec_enc,
        th_uid_enc, th_tok_enc, data.chave_licenca.strip()
    ))
    
    conn.commit()
    conn.close()
    return {"status": "success", "msg": "Configurações e credenciais salvas de forma 100% criptografada!"}

@app.post("/api/licenca/gerar_trial")
def gerar_trial_licenca(data: GerarTrialRequest):
    conn = get_db_bifinhos()
    c = conn.cursor()
    
    # Verifica se o usuário do Discord já possui uma licença
    c.execute("SELECT chave_licenca, expira_em FROM licencas_afiliados WHERE discord_user_id = ?", (data.discord_user_id,))
    row = c.fetchone()
    
    now_ts = int(time.time())
    if row:
        conn.close()
        return {
            "status": "existente",
            "chave_licenca": row['chave_licenca'],
            "msg": "Você já possui uma chave cadastrada!"
        }
        
    nova_chave = f"BIFES_PRO_{secrets.token_hex(6).upper()}"
    expira_em = now_ts + (3 * 24 * 60 * 60) # 3 Dias de Trial Grátis
    
    c.execute("""
        INSERT INTO licencas_afiliados (chave_licenca, discord_user_id, nome_usuario, guild_id, canal_discord_id, status, expira_em, criado_em)
        VALUES (?, ?, ?, ?, ?, 'trial', ?, ?)
    """, (nova_chave, data.discord_user_id, data.nome_usuario, data.guild_id, data.canal_discord_id, expira_em, now_ts))
    
    conn.commit()
    conn.close()
    return {
        "status": "success",
        "chave_licenca": nova_chave,
        "dias_trial": 3,
        "msg": "Licença Trial de 3 dias criada com sucesso!"
    }

@app.post("/api/licenca/checkout_mercadopago")
def checkout_licenca_mercadopago(data: CheckoutLicencaRequest):
    chave = data.chave_licenca.strip() if data.chave_licenca else f"BIFES_PRO_{secrets.token_hex(6).upper()}"
    
    # Cria licença se ainda não existir no banco
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT chave_licenca FROM licencas_afiliados WHERE chave_licenca = ?", (chave,))
    if not c.fetchone():
        now_ts = int(time.time())
        c.execute("""
            INSERT INTO licencas_afiliados (chave_licenca, discord_user_id, nome_usuario, status, expira_em, criado_em)
            VALUES (?, ?, ?, 'pendente', 0, ?)
        """, (chave, data.discord_user_id, data.nome_usuario, now_ts))
        conn.commit()
    conn.close()
    
    preference_data = {
        "items": [
            {
                "id": "plano_pro_afiliados",
                "title": "Bifes Promo Pro - Assinatura Mensal (30 Dias)",
                "description": "Acesso ilimitado à Extensão de Promoções, botões no Discord e redes sociais.",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": 20.00
            }
        ],
        "external_reference": chave,
        "notification_url": "https://api.bifes.com.br/api/pagamento/webhook",
        "back_urls": {
            "success": "https://bifes.com.br/painel?status=sucesso",
            "failure": "https://bifes.com.br/painel?status=erro",
            "pending": "https://bifes.com.br/painel?status=pendente"
        },
        "auto_return": "approved"
    }

    preference_response = mp_sdk.preference().create(preference_data)
    return {
        "status": "success",
        "chave_licenca": chave,
        "link_pagamento": preference_response["response"]["init_point"]
    }

@app.post("/api/licenca/postar")
def postar_via_licenca(data: PostarLicencaRequest):
    chave = data.chave_licenca.strip()
    conn = get_db_bifinhos()
    c = conn.cursor()
    c.execute("SELECT * FROM licencas_afiliados WHERE chave_licenca = ?", (chave,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(401, "Chave de licença não encontrada ou inválida.")
        
    now_ts = int(time.time())
    if not row['expira_em'] or now_ts > row['expira_em']:
        raise HTTPException(403, "Sua licença expirou. Renove sua assinatura por R$ 20/mês para continuar postando.")
        
    mlb_id = f"ext_{int(time.time())}_{random.randint(100, 999)}"
    
    if data.imagem_url:
        baixar_imagem_url(data.imagem_url, mlb_id)
        
    bot = app.state.bot_instance
    if not bot:
        raise HTTPException(500, "Bot desconectado no momento.")
        
    # Injeção automática das tags de afiliado da licença
    link_final = data.link
    if data.loja == "Amazon" and row['tag_amazon']:
        clean = link_final.split('?')[0]
        link_final = f"{clean}?tag={row['tag_amazon']}"
    elif data.loja == "Mercado Livre" and row['tag_ml'] and "matt_tool" not in link_final:
        sep = "&" if "?" in link_final else "?"
        link_final = f"{link_final}{sep}tag={row['tag_ml']}"
        
    data.link = link_final
    
    # 1. Posta no Discord do cliente
    canal_dest = int(row['canal_discord_id']) if row['canal_discord_id'] else int(ML_CHANNEL_ID)
    if data.postar_discord:
        asyncio.run_coroutine_threadsafe(postar_discord_cliente(bot, canal_dest, row, data, mlb_id), bot.loop)
        
    # 2. Posta no Twitter do cliente com credenciais descriptografadas em memória
    if data.postar_twitter and row['twitter_api_key_enc']:
        threading.Thread(target=executar_post_twitter_cliente, args=(row, data, mlb_id)).start()
        
    # 3. Posta no Threads do cliente
    if data.postar_threads and row['threads_access_token_enc']:
        threading.Thread(target=executar_post_threads_cliente, args=(row, data)).start()
        
    return {"status": "success", "mlb_id": mlb_id, "msg": "Oferta publicada com sucesso no seu Discord e Redes!"}

async def postar_discord_cliente(bot, canal_id: int, licenca_row, data, mlb_id: str):
    channel = bot.get_channel(canal_id) or await bot.fetch_channel(canal_id)
    if not channel:
        print(f"⚠️ [SaaS] Canal {canal_id} não encontrado no Discord.")
        return
        
    loja = data.loja or "Mercado Livre"
    vendedor = data.vendedor or "Loja Oficial"
    cor_embed = CORES_LOJAS.get(loja, 0x5865F2)
    
    linhas = []
    if data.descricao_extra:
        linhas.append(f"⚡ **{data.descricao_extra}**\n")
        
    if data.preco_de and data.preco_por:
        linhas.append(f"❌ De: ~~{data.preco_de}~~\n💰 **Por: {data.preco_por}**")
    elif data.preco_por:
        linhas.append(f"💰 **Preço: {data.preco_por}**")
        
    if data.cupom:
        linhas.append(f"\n🎟️ Use o cupom: `{data.cupom}`")
        
    if data.link:
        linhas.append(f"\n🛒 **Link Seguro:** [Aproveitar Oferta]({data.link})")
        
    embed = discord.Embed(
        title=data.titulo,
        description="\n".join(linhas),
        color=cor_embed,
        timestamp=datetime.now()
    )
    
    nome_exibicao = licenca_row['nome_usuario'] or "Bifes Promo"
    embed.set_footer(text=f"Loja: {loja} • Vendedor: {vendedor} | {nome_exibicao}")
    
    img_path = f"imagens_temp/{mlb_id}.jpg"
    view = LinkView(url=data.link) if data.link else None
    
    if os.path.exists(img_path):
        file = discord.File(img_path, filename="oferta.jpg")
        embed.set_image(url="attachment://oferta.jpg")
        if view:
            await channel.send(file=file, embed=embed, view=view)
        else:
            await channel.send(file=file, embed=embed)
    else:
        if data.imagem_url:
            embed.set_image(url=data.imagem_url)
        if view:
            await channel.send(embed=embed, view=view)
        else:
            await channel.send(embed=embed)

def executar_post_twitter_cliente(licenca_row, data, mlb_id: str):
    try:
        api_key = decriptar_dado(licenca_row['twitter_api_key_enc'])
        api_secret = decriptar_dado(licenca_row['twitter_api_secret_enc'])
        access_token = decriptar_dado(licenca_row['twitter_access_token_enc'])
        access_secret = decriptar_dado(licenca_row['twitter_access_secret_enc'])
        
        if not all([api_key, api_secret, access_token, access_secret]):
            return
            
        auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
        api_v1 = tweepy.API(auth)
        client_v2 = tweepy.Client(consumer_key=api_key, consumer_secret=api_secret, access_token=access_token, access_token_secret=access_secret)
        
        txt = f"🔥 {data.titulo}\n\n"
        if data.descricao_extra: txt += f"{data.descricao_extra}\n"
        if data.preco_por: txt += f"💰 {data.preco_por}\n"
        if data.cupom: txt += f"🎟️ Cupom: {data.cupom}\n"
        txt += f"\n🛒 {data.link}"
        
        if len(txt) > 275: txt = txt[:270] + "..."
        
        media_id = None
        img_path = f"imagens_temp/{mlb_id}.jpg"
        if os.path.exists(img_path):
            try: media_id = api_v1.media_upload(img_path).media_id
            except: pass
            
        client_v2.create_tweet(text=txt, media_ids=[media_id] if media_id else None)
        print(f"🐦 [Twitter Cliente] Tweet postado com sucesso para {licenca_row['chave_licenca']}")
    except Exception as e:
        print(f"⚠️ [Twitter Cliente] Erro ao postar: {e}")

def executar_post_threads_cliente(licenca_row, data):
    try:
        user_id = decriptar_dado(licenca_row['threads_user_id_enc'])
        access_token = decriptar_dado(licenca_row['threads_access_token_enc'])
        
        if not user_id or not access_token:
            return
            
        txt = f"{data.titulo}\n\n"
        if data.descricao_extra: txt += f"{data.descricao_extra}\n"
        if data.preco_por: txt += f"💰 {data.preco_por}\n"
        if data.cupom: txt += f"🎟️ Cupom: {data.cupom}\n"
        txt += f"\nConfira: {data.link}"
        
        url = f"https://graph.threads.net/v1.0/{user_id}/threads"
        res = requests.post(url, params={'media_type': 'TEXT', 'text': txt, 'access_token': access_token})
        if res.status_code == 200:
            requests.post(f"https://graph.threads.net/v1.0/{user_id}/threads_publish", 
                          params={'creation_id': res.json()['id'], 'access_token': access_token})
    except Exception as e:
        print(f"⚠️ [Threads Cliente] Erro ao postar: {e}")

class MainAPI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        app.state.bot_instance = bot
        self.server_thread = threading.Thread(target=self.run_server, daemon=True)
        self.server_thread.start()

    def run_server(self):
        cert = 'cert.pem'
        key = 'key.pem'
        ssl_config = {}
        
        use_ssl_env = os.getenv("USE_SSL", "true").lower() in ("true", "1", "yes")
        
        if use_ssl_env and os.path.exists(cert) and os.path.exists(key):
            ssl_config = {"ssl_keyfile": key, "ssl_certfile": cert}
            print(f"🌍 [API UNIFICADA] Rodando com SSL (HTTPS) na porta {PORTA}")
        else:
            print(f"⚠️ [API UNIFICADA] Rodando em HTTP puro na porta {PORTA}")
            
        uvicorn.run(app, host="0.0.0.0", port=PORTA, proxy_headers=True, forwarded_allow_ips="*", **ssl_config)

async def setup(bot):
    await bot.add_cog(MainAPI(bot))