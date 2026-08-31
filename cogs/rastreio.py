import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import json
import time
import re
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict

from cogs.criptografia import encriptar_dado, decriptar_dado

def get_db_rastreio():
    conn = sqlite3.connect("banco.db", timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_rastreio_db():
    conn = get_db_rastreio()
    with conn:
        # Tabela de encomendas monitoradas
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rastreios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL,
                nome_pacote TEXT,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                ultimo_status TEXT,
                ultimo_local TEXT,
                ultima_data TEXT,
                entregue INTEGER DEFAULT 0,
                origem TEXT,
                notificar_pv INTEGER DEFAULT 1,
                historico_json TEXT,
                criado_em INTEGER,
                UNIQUE(codigo, user_id)
            )
        """)
        
        # Tabela de chaves de API Ship24 criptografadas por usuário
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios_ship24 (
                user_id TEXT PRIMARY KEY,
                api_key_enc TEXT NOT NULL,
                criado_em INTEGER,
                atualizado_em INTEGER
            )
        """)

        # Adiciona colunas se já existia a tabela antiga
        try:
            conn.execute("ALTER TABLE rastreios ADD COLUMN notificar_pv INTEGER DEFAULT 1")
        except:
            pass
        try:
            conn.execute("ALTER TABLE rastreios ADD COLUMN historico_json TEXT")
        except:
            pass
        try:
            conn.execute("ALTER TABLE rastreios ADD COLUMN entregue_em INTEGER DEFAULT 0")
        except:
            pass
    conn.close()

init_rastreio_db()

# ===================================================
#  GERENCIAMENTO DE CHAVE SHIP24 CRIPTOGRAFADA
# ===================================================

def obter_ship24_key(user_id: str) -> Optional[str]:
    """ Busca e decripta a chave de API Ship24 exclusiva do usuário """
    conn = get_db_rastreio()
    row = conn.execute("SELECT api_key_enc FROM usuarios_ship24 WHERE user_id = ?", (str(user_id),)).fetchone()
    conn.close()
    if row and row['api_key_enc']:
        try:
            return decriptar_dado(row['api_key_enc'])
        except Exception as e:
            print(f"⚠️ Erro ao decriptar chave Ship24 do user {user_id}: {e}")
    return None

def salvar_ship24_key(user_id: str, api_key: str):
    """ Encripta e armazena a chave de API Ship24 no banco de dados """
    key_limpa = api_key.strip()
    key_enc = encriptar_dado(key_limpa)
    now = int(time.time())
    conn = get_db_rastreio()
    with conn:
        conn.execute("""
            INSERT INTO usuarios_ship24 (user_id, api_key_enc, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                api_key_enc = excluded.api_key_enc,
                atualizado_em = excluded.atualizado_em
        """, (str(user_id), key_enc, now, now))
    conn.close()

def remover_ship24_key(user_id: str) -> bool:
    """ Remove a chave de API Ship24 do usuário """
    conn = get_db_rastreio()
    with conn:
        c = conn.execute("DELETE FROM usuarios_ship24 WHERE user_id = ?", (str(user_id),))
        removido = c.rowcount > 0
    conn.close()
    return removido

def gerar_embed_tutorial_ship24() -> discord.Embed:
    """ Gera o embed com o tutorial passo a passo para obter a chave gratuita no Ship24 """
    embed = discord.Embed(
        title="🔑 Configuração Necessária: Chave API Ship24",
        description=(
            "Para rastrear seus pedidos internacionais e nacionais em tempo real diretamente no Discord e receber alertas no PV, "
            "você precisa configurar sua **chave gratuita do Ship24** (permite rastrear até **10 pedidos grátis por mês**).\n\n"
            "🔒 **Sua chave é criptografada e de uso exclusivo da sua conta!**"
        ),
        color=0xFF4646
    )
    embed.add_field(
        name="📖 Passo a Passo Simples (Leva menos de 1 minuto):",
        value=(
            "**1.** Acesse o site oficial: [ship24.com](https://www.ship24.com/)\n"
            "**2.** Clique em **Sign Up** (ou Get Started) e cadastre-se com seu **Gmail / E-mail**.\n"
            "**3.** No painel (Dashboard), acesse a aba **API** ou **API Management**.\n"
            "**4.** Copie o seu **API Key (Token de Acesso)**.\n"
            "**5.** Volte aqui no Discord e digite:\n"
            "```/api24ship api_key:SUA_CHAVE_AQUI```"
        ),
        inline=False
    )
    embed.set_footer(text="Bife's Bot • Rastreamento Seguro com Criptografia Ponta a Ponta")
    return embed

# ===================================================
#  DICIONÁRIO E MOTOR DE TRADUÇÃO CHINÊS -> PT-BR
# ===================================================

DICIONARIO_CHINES = {
    # Cidades e Províncias Principais de E-commerce
    "广州市": "Guangzhou",
    "广州": "Guangzhou",
    "阳江市": "Yangjiang",
    "阳江": "Yangjiang",
    "深圳市": "Shenzhen",
    "深圳": "Shenzhen",
    "义乌市": "Yiwu",
    "义乌": "Yiwu",
    "东莞市": "Dongguan",
    "东莞": "Dongguan",
    "杭州市": "Hangzhou",
    "杭州": "Hangzhou",
    "上海市": "Shanghai",
    "上海": "Shanghai",
    "北京市": "Beijing",
    "北京": "Beijing",
    "佛山市": "Foshan",
    "佛山": "Foshan",
    "厦门市": "Xiamen",
    "厦门": "Xiamen",
    "泉州市": "Quanzhou",
    "泉州": "Quanzhou",
    "香港": "Hong Kong",
    
    # Termos Técnicos Postais e Alfandegários (frases longas primeiro)
    "国际互换局": "Centro de Tratamento e Intercâmbio Internacional",
    "互换局": "Centro de Intercâmbio Postal",
    "包件车间": "Centro de Triagem de Encomendas",
    "投递部": "Departamento de Postagem/Coleta",
    "处理中心": "Centro de Processamento",
    "送交出口海关": "Encaminhado para a alfândega de exportação",
    "海关放行": "Liberado pela alfândega de exportação",
    "出口海关": "Alfândega de exportação",
    "海关": "Alfândega",
    "已出口直封": "Selado em mala postal para exportação direta",
    "已离开": "Saiu de ",
    "已到达": "Chegou a ",
    "正发往": "está sendo enviado para ",
    "交航运公司运输": "Entregue à companhia aérea transportadora",
    "航空公司接收": "Companhia aérea recebeu a carga",
    "航空起飞": "Voo internacional decolou",
    "飞机进港": "Voo internacional aterrissou",
    "到达目的地": "Chegou ao país de destino (Brasil)",
    "已妥投": "Objeto entregue ao destinatário",
    "安排投递": "Saiu para entrega",
    "邮件已在": "A encomenda foi classificada em",
    "收寄": "China Post recebeu a correspondência",
    "中国邮政": "China Post"
}

def traduzir_para_pt(texto: str) -> str:
    """ Traduz e normaliza expressões chinesas ou inglesas para Português """
    if not texto:
        return ""
    
    texto_traduzido = texto
    
    # 1. Normaliza pontuação chinesa para caracteres ocidentais seguros
    texto_traduzido = (
        texto_traduzido
        .replace("【", "[")
        .replace("】", "]")
        .replace("（", "(")
        .replace("）", ")")
        .replace("，", ", ")
        .replace("。", ". ")
        .replace("：", ": ")
    )
    
    # 2. Substitui termos conhecidos pelo dicionário especializado
    for zh, pt in DICIONARIO_CHINES.items():
        if zh in texto_traduzido:
            texto_traduzido = texto_traduzido.replace(zh, pt)

    # 3. Se ainda contiver caracteres chineses ou inglês técnico, usa Google Translate
    tem_chines = bool(re.search(r'[\u4e00-\u9fff]', texto_traduzido))
    termos_ingles = any(w in texto_traduzido.lower() for w in ["delivered", "transit", "customs", "dispatch", "cleared", "departed", "arrival", "item", "carrier", "sorting", "hub", "handed over"])
    
    if tem_chines or termos_ingles:
        try:
            url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode({
                "client": "gtx",
                "sl": "auto",
                "tl": "pt",
                "dt": "t",
                "q": texto_traduzido
            })
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            })
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode('utf-8'))
                traducao = "".join([part[0] for part in data[0] if part[0]])
                if traducao:
                    texto_traduzido = traducao.strip()
        except Exception as e:
            pass
    
    # Limpeza estética
    texto_traduzido = re.sub(r'\s+', ' ', texto_traduzido).strip()
    return texto_traduzido

# ===================================================
#  MOTOR DE RASTREAMENTO SHIP24 + FALLBACK MULTI-CARRIER
# ===================================================

def consultar_ship24(codigo: str, api_key: str) -> Dict:
    """ Consulta o status em tempo real na API oficial do Ship24 forçando China Post + Correios Brasil """
    cod_limpo = codigo.strip().upper()
    url = "https://api.ship24.com/public/v1/trackers/track"

    # Monta payload forçando China Post (Origem) e Correios (Destino) simultaneamente
    payload_dict = {
        "trackingNumber": cod_limpo,
        "destinationCountryCode": "BR"
    }
    
    if cod_limpo.endswith("CN") or cod_limpo.startswith("LP") or cod_limpo.startswith("LZ") or cod_limpo.startswith("LM"):
        payload_dict["originCountryCode"] = "CN"
        payload_dict["courierCode"] = ["china-post", "correios-brazil"]
    else:
        payload_dict["courierCode"] = ["correios-brazil"]

    payload = json.dumps(payload_dict).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "User-Agent": "BifesBot/1.0"
    })
    
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode('utf-8'))
            data_track = data.get("data", {}).get("trackings", [])
            if not data_track:
                data_track = data.get("trackings", [])
            
            if data_track:
                tracking_obj = data_track[0]
                events_raw = tracking_obj.get("events", [])
                shipment_info = tracking_obj.get("shipment", {})
                courier_code = shipment_info.get("courierCode", "") or "Internacional"
                
                eventos_unificados = []
                for ev in events_raw:
                    st_raw = ev.get("status", "") or ev.get("statusMilestone", "")
                    st_pt = traduzir_para_pt(st_raw)
                    loc_raw = ev.get("location", "")
                    loc_pt = traduzir_para_pt(loc_raw) if loc_raw else "Trânsito"
                    dt_raw = ev.get("datetime", "")
                    if dt_raw:
                        dt_clean = dt_raw.replace("T", " ")[:16]
                    else:
                        dt_clean = datetime.now().strftime("%Y-%m-%d %H:%M")
                        
                    eventos_unificados.append({
                        "fase": "China Post / Internacional" if ("china" in courier_code.lower() or "China" in loc_pt or cod_limpo.endswith("CN")) else "Correios / Destino",
                        "status": st_pt,
                        "local": loc_pt,
                        "data": dt_clean
                    })
                    
                is_entregue = shipment_info.get("statusMilestone") == "delivered" or any("entregue" in ev["status"].lower() or "já entregue" in ev["status"].lower() for ev in eventos_unificados)
                
                if eventos_unificados:
                    return {
                        "sucesso": True,
                        "codigo": cod_limpo,
                        "origem": f"Ship24 ({courier_code}) ➡️ Correios",
                        "ultimo_status": eventos_unificados[0]["status"],
                        "ultimo_local": eventos_unificados[0]["local"],
                        "ultima_data": eventos_unificados[0]["data"],
                        "entregue": is_entregue,
                        "total_eventos": len(eventos_unificados),
                        "historico": eventos_unificados
                    }
    except urllib.error.HTTPError as he:
        if he.code in (401, 403):
            return {
                "sucesso": False,
                "codigo": cod_limpo,
                "msg": "❌ Sua chave Ship24 é inválida ou atingiu o limite da cota mensal. Atualize-a com `/api24ship`."
            }
        elif he.code == 404:
            return {
                "sucesso": False,
                "codigo": cod_limpo,
                "msg": "❌ Código de rastreio não encontrado na Ship24. Verifique se o código está correto."
            }
        else:
            print(f"⚠️ [Ship24] Erro HTTP {he.code}: {he.reason}")
    except Exception as e:
        print(f"⚠️ [Ship24] Erro de conexão: {e}")
        
    # Se a Ship24 não retornou ou deu erro temporário, tenta o fallback local
    return consultar_codigo_duplo(cod_limpo)

def consultar_codigo_duplo(codigo: str) -> Dict:
    """ Consulta a jornada completa nas duas pontas (China Post + Correios Brasil) como fallback """
    cod_limpo = codigo.strip().upper()
    eventos_unificados = []
    transportadora_origem = "China Post" if cod_limpo.endswith("CN") else "Internacional"
    
    # --- 1. CONSULTA PONTA 1: CHINA POST / CAINIAO GLOBAL ---
    try:
        url_cainiao = f"https://global.cainiao.com/global/detail.json?mailNos={cod_limpo}&lang=zh-CN"
        req_cainiao = urllib.request.Request(url_cainiao, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req_cainiao, timeout=8) as r:
            data_cainiao = json.loads(r.read().decode('utf-8'))
            module = data_cainiao.get("module", [])
            if module and len(module) > 0:
                detail_list = module[0].get("detailList", [])
                for ev in detail_list:
                    desc_zh = ev.get("desc", "")
                    st_pt = traduzir_para_pt(desc_zh)
                    dt_str = ev.get("timeStr", "")
                    if not dt_str and ev.get("time"):
                        dt_str = datetime.fromtimestamp(ev["time"]/1000).strftime("%Y-%m-%d %H:%M")
                    
                    loc = "China / Internacional"
                    if "Guangzhou" in st_pt: loc = "Guangzhou (China)"
                    elif "Yangjiang" in st_pt: loc = "Yangjiang (China)"
                    elif "Shenzhen" in st_pt: loc = "Shenzhen (China)"
                    elif "Yiwu" in st_pt: loc = "Yiwu (China)"
                    elif "Brasil" in st_pt or "Curitiba" in st_pt: loc = "Brasil"
                    
                    eventos_unificados.append({
                        "fase": "China / Trânsito Internacional",
                        "status": st_pt,
                        "local": loc,
                        "data": dt_str,
                        "timestamp": ev.get("time", 0)
                    })
    except Exception as e:
        print(f"⚠️ [Cainiao] Erro na consulta de {cod_limpo}: {e}")

    # --- 2. SE NÃO ENCONTROU EVENTOS (PACOTE RECÉM-CRIADO) ---
    if not eventos_unificados:
        is_valido = re.match(r'^[A-Z]{2}\d{9}[A-Z]{2}$', cod_limpo) or cod_limpo.startswith("LP")
        if is_valido:
            data_agora = datetime.now().strftime("%Y-%m-%d %H:%M")
            try:
                conn_tmp = get_db_rastreio()
                row_tmp = conn_tmp.execute("SELECT ultima_data, criado_em FROM rastreios WHERE codigo = ?", (cod_limpo,)).fetchone()
                conn_tmp.close()
                if row_tmp and row_tmp['ultima_data']:
                    data_agora = row_tmp['ultima_data']
            except:
                pass

            return {
                "sucesso": True,
                "codigo": cod_limpo,
                "origem": transportadora_origem,
                "ultimo_status": "Aguardando postagem / Informações eletrônicas recebidas",
                "ultimo_local": "China (Origem / Transportadora)" if cod_limpo.endswith("CN") else "Origem / Transportadora",
                "ultima_data": data_agora,
                "entregue": False,
                "total_eventos": 1,
                "historico": [
                    {
                        "fase": "China / Origem" if cod_limpo.endswith("CN") else "Origem",
                        "status": "Etiqueta criada pelo vendedor. Aguardando coleta física pela transportadora.",
                        "local": "China (Origem)" if cod_limpo.endswith("CN") else "Origem",
                        "data": data_agora
                    }
                ]
            }
        else:
            return {
                "sucesso": False,
                "codigo": cod_limpo,
                "msg": "Código não encontrado ou inválido."
            }

    # --- 3. ORGANIZAÇÃO DO HISTÓRICO ---
    ultimo = eventos_unificados[0]
    status_final = ultimo["status"]
    local_final = ultimo["local"]
    data_final = ultimo["data"]
    is_entregue = any("entregue" in ev["status"].lower() or "já entregue" in ev["status"].lower() for ev in eventos_unificados)

    return {
        "sucesso": True,
        "codigo": cod_limpo,
        "origem": f"{transportadora_origem} ➡️ Correios Brasil",
        "ultimo_status": status_final,
        "ultimo_local": local_final,
        "ultima_data": data_final,
        "entregue": is_entregue,
        "total_eventos": len(eventos_unificados),
        "historico": eventos_unificados
    }

def mascarar_codigo(codigo: str) -> str:
    """ Mascara os dígitos centrais do código para total privacidade e segurança (Ex: AA123456789BR -> AA12****789BR) """
    if not codigo:
        return ""
    cod = codigo.strip().upper()
    if len(cod) >= 11:
        return f"{cod[:4]}****{cod[-5:]}"
    elif len(cod) > 6:
        return f"{cod[:2]}****{cod[-2:]}"
    return cod

def get_status_emoji(status: str) -> str:
    s = (status or "").lower()
    if "entregue" in s or "delivered" in s or "concluída" in s or "já entregue" in s:
        return "✅"
    if "saiu para entrega" in s or "providenciar entrega" in s or "out for delivery" in s:
        return "🛵"
    if "aduaneira" in s or "fiscalização" in s or "curitiba" in s or "imposto" in s or "pagamento" in s or "customs" in s:
        return "🛃"
    if "trânsito" in s or "transit" in s or "encaminhado" in s or "transferência" in s or "avião" in s or "voo" in s or "aérea" in s or "flight" in s:
        return "✈️"
    if "postado" in s or "recebido" in s or "posted" in s or "classificada" in s or "info_received" in s or "etiqueta criada" in s:
        return "📦"
    return "🚚"

# ===================================================
#  COG DE RASTREAMENTO DISCORD COM AUTENTICAÇÃO SHIP24
# ===================================================

class RastreioCog(commands.Cog, name="Rastreio"):
    def __init__(self, bot):
        self.bot = bot
        self.verificar_rastreios_loop.start()

    def cog_unload(self):
        self.verificar_rastreios_loop.cancel()

    # --- COMANDO SLASH: /api24ship ---
    @app_commands.command(name="api24ship", description="Configura sua chave de API exclusiva e gratuita do Ship24 (com criptografia).")
    @app_commands.describe(api_key="Sua chave de API do Ship24 (pegue grátis em ship24.com)")
    async def slash_api24ship(self, interaction: discord.Interaction, api_key: str):
        key_limpa = api_key.strip()
        if len(key_limpa) < 10:
            await interaction.response.send_message(
                "❌ Chave de API inválida! Ela deve ser uma chave válida fornecida no painel do [ship24.com](https://www.ship24.com/).",
                ephemeral=True
            )
            return

        salvar_ship24_key(str(interaction.user.id), key_limpa)
        key_mascarada = key_limpa[:4] + "****" + key_limpa[-4:] if len(key_limpa) >= 8 else "****"

        embed = discord.Embed(
            title="🔒 Chave API Ship24 Configurada com Sucesso!",
            description=(
                f"Sua chave **`{key_mascarada}`** foi **criptografada com segurança** e vinculada exclusivamente à sua conta.\n\n"
                "✨ **Você já pode usar:**\n"
                "• `/rastrear <codigo> [nome]` — Rastrear novas encomendas com alertas no PV.\n"
                "• `/historico_rastreio <codigo>` — Ver a linha do tempo completa passo a passo."
            ),
            color=0x2ECC71
        )
        embed.set_footer(text="Bife's Bot • Segurança e Privacidade Garantidas")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- COMANDO SLASH: /minha_api24ship ---
    @app_commands.command(name="minha_api24ship", description="Verifica se você possui uma chave API do Ship24 cadastrada.")
    async def slash_minha_api24ship(self, interaction: discord.Interaction):
        key = obter_ship24_key(str(interaction.user.id))
        if not key:
            embed = gerar_embed_tutorial_ship24()
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        key_mascarada = key[:4] + "****" + key[-4:] if len(key) >= 8 else "****"
        embed = discord.Embed(
            title="🔑 Sua Chave API Ship24",
            description=f"Status: ✅ **Ativa e Criptografada**\nChave: `{key_mascarada}`",
            color=0x2ECC71
        )
        embed.set_footer(text="Para alterar, use /api24ship. Para remover, use /remover_api24ship.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- COMANDO SLASH: /remover_api24ship ---
    @app_commands.command(name="remover_api24ship", description="Remove sua chave API do Ship24 salva no bot.")
    async def slash_remover_api24ship(self, interaction: discord.Interaction):
        removido = remover_ship24_key(str(interaction.user.id))
        if removido:
            await interaction.response.send_message("🗑️ Sua chave API Ship24 foi removida com sucesso.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Você não tinha nenhuma chave Ship24 cadastrada.", ephemeral=True)

    # --- COMANDO SLASH: /rastrear ---
    @app_commands.command(name="rastrear", description="Rastreia encomendas da China e Correios com privacidade e alertas no PV.")
    @app_commands.describe(
        codigo="Código de rastreio (ex: AA123456789BR, NL987654321BR)",
        nome="Nome ou apelido para o pacote (ex: Fone Bluetooth, Teclado Mecânico)",
        notificar_no_pv="Receber atualizações automáticas na sua Mensagem Direta (PV / DM)?",
        privado="Manter a visualização anônima e invisível para os outros no servidor?"
    )
    async def slash_rastrear(self, interaction: discord.Interaction, codigo: str, nome: Optional[str] = "Minha Encomenda", notificar_no_pv: Optional[bool] = True, privado: Optional[bool] = True):
        # 1. Verifica se o usuário possui a chave Ship24 configurada
        user_key = obter_ship24_key(str(interaction.user.id))
        if not user_key:
            embed_tutorial = gerar_embed_tutorial_ship24()
            await interaction.response.send_message(embed=embed_tutorial, ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=privado)
        
        cod_limpo = codigo.strip().upper()
        res = consultar_ship24(cod_limpo, user_key)
        
        if not res.get("sucesso"):
            msg_erro = res.get("msg", f"Não foi possível encontrar informações para `{mascarar_codigo(cod_limpo)}`.")
            await interaction.followup.send(f"❌ {msg_erro}", ephemeral=True)
            return

        # Salva no banco de dados SQLite com histórico completo
        conn = get_db_rastreio()
        now_ts = int(time.time())
        pv_flag = 1 if notificar_no_pv else 0
        hist_json = json.dumps(res.get("historico", []), ensure_ascii=False)
        entregue_val = 1 if res["entregue"] else 0
        entregue_em_val = now_ts if res["entregue"] else 0

        with conn:
            conn.execute("""
                INSERT INTO rastreios (codigo, nome_pacote, user_id, channel_id, ultimo_status, ultimo_local, ultima_data, entregue, origem, notificar_pv, historico_json, entregue_em, criado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, user_id) DO UPDATE SET 
                    nome_pacote=excluded.nome_pacote,
                    channel_id=excluded.channel_id,
                    ultimo_status=excluded.ultimo_status,
                    ultimo_local=excluded.ultimo_local,
                    ultima_data=excluded.ultima_data,
                    notificar_pv=excluded.notificar_pv,
                    historico_json=excluded.historico_json,
                    entregue_em=CASE WHEN excluded.entregue = 1 AND rastreios.entregue_em = 0 THEN excluded.entregue_em ELSE rastreios.entregue_em END,
                    entregue=excluded.entregue
            """, (
                cod_limpo, nome, str(interaction.user.id), str(interaction.channel_id),
                res["ultimo_status"], res["ultimo_local"], res["ultima_data"],
                entregue_val, res["origem"], pv_flag, hist_json, entregue_em_val, now_ts
            ))
        conn.close()

        cod_mascarado = mascarar_codigo(cod_limpo)
        emoji = get_status_emoji(res["ultimo_status"])
        cor = 0x2ECC71 if res["entregue"] else (0xF1C40F if "aduaneira" in res["ultimo_status"].lower() or "pagamento" in res["ultimo_status"].lower() or "customs" in res["ultimo_status"].lower() else 0xFF4646)
        
        embed = discord.Embed(
            title=f"{emoji} Rastreio: {nome}",
            description=f"🔒 **Código:** `{cod_mascarado}` *(Código protegido)*\n**Rota:** {res['origem']}",
            color=cor,
            timestamp=datetime.now()
        )
        
        embed.add_field(name="📍 Status Atual", value=f"**{res['ultimo_status']}**", inline=False)
        if res.get("ultimo_local"):
            embed.add_field(name="🏙️ Localização", value=res["ultimo_local"], inline=True)
        if res.get("ultima_data"):
            embed.add_field(name="⏰ Data / Hora", value=res["ultima_data"], inline=True)

        # Exibe os marcos mais recentes
        historico = res.get("historico", [])
        if len(historico) > 1:
            historico_txt = ""
            for h in historico[:5]:
                dt = h.get('data', '')
                st = h.get('status', '')
                loc = f" ({h['local']})" if h.get('local') and h['local'] != "China / Internacional" else ""
                historico_txt += f"• **{dt}** - {st}{loc}\n"
            if historico_txt:
                embed.add_field(name="📜 Últimas Movimentações (Traduzidas)", value=historico_txt.strip(), inline=False)

        if not res["entregue"]:
            if notificar_no_pv:
                embed.set_footer(text="🔔 Monitoramento ativo! Você receberá atualizações no seu PV (DM).")
            else:
                embed.set_footer(text="🔔 Monitoramento ativo neste canal!")
        else:
            embed.set_footer(text="🎉 Encomenda entregue ao destinatário!")

        await interaction.followup.send(embed=embed, ephemeral=privado)

    # --- COMANDO SLASH: /historico_rastreio ---
    @app_commands.command(name="historico_rastreio", description="Exibe a linha do tempo completa e protegida de uma encomenda.")
    @app_commands.describe(codigo="Código de rastreio", privado="Manter visualização invisível para os outros no servidor?")
    async def slash_historico_rastreio(self, interaction: discord.Interaction, codigo: str, privado: Optional[bool] = True):
        # 1. Verifica se o usuário possui a chave Ship24 configurada
        user_key = obter_ship24_key(str(interaction.user.id))
        if not user_key:
            embed_tutorial = gerar_embed_tutorial_ship24()
            await interaction.response.send_message(embed=embed_tutorial, ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=privado)
        cod_limpo = codigo.strip().upper()
        
        # 2. Busca no banco de dados local primeiro
        conn = get_db_rastreio()
        row = conn.execute("SELECT * FROM rastreios WHERE codigo = ? AND user_id = ?", (cod_limpo, str(interaction.user.id))).fetchone()
        if not row:
            row = conn.execute("SELECT * FROM rastreios WHERE codigo = ?", (cod_limpo,)).fetchone()
        conn.close()

        historico_db = []
        if row and row['historico_json']:
            try:
                historico_db = json.loads(row['historico_json'])
            except:
                pass

        # 3. Consulta a API Ship24 com a chave do usuário
        res = consultar_ship24(cod_limpo, user_key)
        historico_live = res.get("historico", []) if res.get("sucesso") else []

        # 4. Mescla eventos evitando duplicatas
        eventos_finais = []
        chaves_vistas = set()

        for ev in (historico_live + historico_db):
            st_limpo = ev.get('status', '').strip()
            if "etiqueta criada" in st_limpo.lower():
                if "etiqueta_criada_vista" in chaves_vistas:
                    continue
                chaves_vistas.add("etiqueta_criada_vista")
                eventos_finais.append(ev)
                continue

            chave = f"{ev.get('data', '')}_{st_limpo}".strip()
            if chave and chave not in chaves_vistas:
                chaves_vistas.add(chave)
                eventos_finais.append(ev)

        if not eventos_finais:
            await interaction.followup.send(f"📦 Nenhum histórico disponível ainda para **`{mascarar_codigo(cod_limpo)}`**.", ephemeral=True)
            return

        # 5. Atualiza o banco com o histórico mesclado
        conn_up = get_db_rastreio()
        with conn_up:
            conn_up.execute("""
                UPDATE rastreios 
                SET historico_json = ?, ultimo_status = ?, ultima_data = ?
                WHERE codigo = ?
            """, (json.dumps(eventos_finais, ensure_ascii=False), eventos_finais[0]['status'], eventos_finais[0]['data'], cod_limpo))
        conn_up.close()

        cod_mascarado = mascarar_codigo(cod_limpo)
        nome_display = row['nome_pacote'] if (row and row['nome_pacote']) else "Encomenda"
        is_entregue = any("entregue" in ev.get("status", "").lower() or "já entregue" in ev.get("status", "").lower() for ev in eventos_finais)

        embed = discord.Embed(
            title=f"📜 Histórico Completo: {nome_display}",
            description=f"🔒 **Código:** `{cod_mascarado}` *(Protegido)*\n**Total de Eventos:** {len(eventos_finais)} marco(s) registrado(s)",
            color=0x2ECC71 if is_entregue else 0xFF4646,
            timestamp=datetime.now()
        )

        # Separa os eventos por blocos (China/Origem vs Brasil/Destino)
        eventos_china = [
            ev for ev in eventos_finais 
            if "China" in ev.get("local", "") or "China" in ev.get("fase", "") or "Origem" in ev.get("local", "") or "Origem" in ev.get("fase", "")
            or "Guangzhou" in ev.get("status", "") or "Hangzhou" in ev.get("status", "") or "Yangjiang" in ev.get("status", "") or "Shenzhen" in ev.get("status", "")
            or "voo" in ev.get("status", "").lower() or "aérea" in ev.get("status", "").lower() or "etiqueta criada" in ev.get("status", "").lower()
            or "510400" in ev.get("status", "") or "5299" in ev.get("status", "")
        ]
        eventos_brasil = [ev for ev in eventos_finais if ev not in eventos_china]

        if eventos_china:
            txt_china = ""
            for h in eventos_china[:10]:
                emoji_step = get_status_emoji(h.get('status', ''))
                dt = h.get('data', '')
                st = h.get('status', '')
                loc = f" ({h['local']})" if h.get('local') and h['local'] != "China / Internacional" else ""
                txt_china += f"{emoji_step} **{dt}** — {st}{loc}\n"
            if txt_china:
                embed.add_field(name="🇨🇳 Origem (China Post & Voo Internacional)", value=txt_china[:1024], inline=False)

        if eventos_brasil:
            txt_br = ""
            for h in eventos_brasil[:10]:
                emoji_step = get_status_emoji(h.get('status', ''))
                dt = h.get('data', '')
                st = h.get('status', '')
                loc = f" ({h['local']})" if h.get('local') and h['local'] != "Correios Brasil" else ""
                txt_br += f"{emoji_step} **{dt}** — {st}{loc}\n"
            if txt_br:
                embed.add_field(name="🇧🇷 Destino (Correios Brasil & Entrega)", value=txt_br[:1024], inline=False)

        if not eventos_china and not eventos_brasil:
            txt_geral = ""
            for h in eventos_finais[:12]:
                emoji_step = get_status_emoji(h.get('status', ''))
                txt_geral += f"{emoji_step} **{h.get('data','')}** — {h.get('status','')}\n"
            embed.add_field(name="🗺️ Linha do Tempo", value=txt_geral[:1024], inline=False)

        embed.set_footer(text="Bife's Bot • Rastreamento com Privacidade Garantida")
        await interaction.followup.send(embed=embed, ephemeral=privado)

    # --- COMANDO SLASH: /minhas_encomendas ---
    @app_commands.command(name="minhas_encomendas", description="Lista todas as suas encomendas salvas de forma anônima e individual.")
    async def slash_minhas_encomendas(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        conn = get_db_rastreio()
        c = conn.cursor()
        c.execute("SELECT * FROM rastreios WHERE user_id = ? ORDER BY entregue ASC, criado_em DESC", (str(interaction.user.id),))
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            await interaction.followup.send("📦 Você ainda não tem nenhuma encomenda sendo monitorada. Use `/rastrear <codigo> [nome]` para cadastrar!", ephemeral=True)
            return

        embed = discord.Embed(
            title="📦 Suas Encomendas Monitoradas",
            description=f"Total de pacotes: **{len(rows)}**\n🔒 *Apenas você pode ver esta lista.*",
            color=0xFF4646
        )

        for r in rows:
            emoji = get_status_emoji(r["ultimo_status"])
            status_badge = "✅ Entregue" if r["entregue"] else f"{emoji} {r['ultimo_status'] or 'Em trânsito'}"
            local_info = f"\n📍 {r['ultimo_local']}" if r['ultimo_local'] else ""
            data_info = f" • ⏰ {r['ultima_data']}" if r['ultima_data'] else ""
            pv_badge = " • 📩 PV" if (r['notificar_pv'] if 'notificar_pv' in r.keys() else 1) else " • 📢 Canal"
            cod_masc = mascarar_codigo(r['codigo'])
            
            embed.add_field(
                name=f"{r['nome_pacote']} (`{cod_masc}`)",
                value=f"**Status:** {status_badge}{local_info}{data_info}{pv_badge}",
                inline=False
            )

        embed.set_footer(text="Use /historico_rastreio <codigo> para ver todos os passos.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # --- COMANDO SLASH: /remover_rastreio ---
    @app_commands.command(name="remover_rastreio", description="Remove um código da sua lista de monitoramento.")
    @app_commands.describe(codigo="Código que deseja remover")
    async def slash_remover_rastreio(self, interaction: discord.Interaction, codigo: str):
        cod_limpo = codigo.strip().upper()
        conn = get_db_rastreio()
        with conn:
            c = conn.execute("DELETE FROM rastreios WHERE codigo = ? AND user_id = ?", (cod_limpo, str(interaction.user.id)))
            removidos = c.rowcount
        conn.close()

        if removidos > 0:
            await interaction.response.send_message(f"🗑️ O pacote **`{mascarar_codigo(cod_limpo)}`** foi removido do seu monitoramento.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Pacote **`{mascarar_codigo(cod_limpo)}`** não encontrado na sua lista.", ephemeral=True)

    # ===================================================
    #  LOOP DE VERIFICAÇÃO AUTOMÁTICA EM SEGUNDO PLANO
    # ===================================================
    @tasks.loop(minutes=25)
    async def verificar_rastreios_loop(self):
        """ Percorre encomendas pendentes, notifica no PV/Canal e faz a limpeza automática após 5 dias da entrega """
        now_ts = int(time.time())
        CINCO_DIAS = 5 * 86400  # 5 dias em segundos (432.000s)

        # --- 1. LIMPEZA AUTOMÁTICA: Remove pacotes entregues há mais de 5 dias para liberar cota ---
        try:
            conn_clean = get_db_rastreio()
            with conn_clean:
                c_del = conn_clean.execute(
                    "SELECT id, codigo, nome_pacote, user_id, notificar_pv FROM rastreios WHERE entregue = 1 AND entregue_em > 0 AND (? - entregue_em) >= ?",
                    (now_ts, CINCO_DIAS)
                )
                expirados = c_del.fetchall()
                if expirados:
                    for exp in expirados:
                        conn_clean.execute("DELETE FROM rastreios WHERE id = ?", (exp['id'],))
                        print(f"🧹 [Auto-Cleanup] Pacote {exp['codigo']} ({exp['nome_pacote']}) removido após 5 dias da entrega.")
                        
                        # Notifica o usuário no PV avisando que foi arquivado
                        if exp['notificar_pv']:
                            try:
                                u = await self.bot.fetch_user(int(exp['user_id']))
                                if u:
                                    cod_masc = mascarar_codigo(exp['codigo'])
                                    await u.send(
                                        f"📦 **Seu pacote `{exp['nome_pacote']}` (`{cod_masc}`) foi arquivado com sucesso!**\n"
                                        f"*(Já se passaram 5 dias desde a entrega, então ele foi removido do monitoramento para liberar sua cota do Ship24).* ✨"
                                    )
                            except Exception as e_warn:
                                pass
            conn_clean.close()
        except Exception as e_clean:
            print(f"⚠️ Erro no auto-cleanup de 5 dias: {e_clean}")

        # --- 2. VERIFICAÇÃO DE ENCOMENDAS ATIVAS ---
        conn = get_db_rastreio()
        c = conn.cursor()
        c.execute("SELECT * FROM rastreios WHERE entregue = 0")
        pendentes = c.fetchall()
        conn.close()

        if not pendentes:
            return

        for p in pendentes:
            try:
                cod = p["codigo"]
                user_id = p["user_id"]
                channel_id = p["channel_id"]
                ultimo_status_antigo = p["ultimo_status"] or ""
                notificar_pv = p["notificar_pv"] if "notificar_pv" in p.keys() else 1
                
                # Busca chave Ship24 do usuário
                user_key = obter_ship24_key(user_id)
                if user_key:
                    res = consultar_ship24(cod, user_key)
                else:
                    res = consultar_codigo_duplo(cod)

                if not res.get("sucesso"):
                    continue

                novo_status = res["ultimo_status"]
                novo_local = res["ultimo_local"]
                nova_data = res["ultima_data"]
                is_entregue = 1 if res["entregue"] else 0
                entregue_em_val = now_ts if res["entregue"] else 0
                hist_json = json.dumps(res.get("historico", []), ensure_ascii=False)

                # Se o status ou data mudaram, NOTIFICA!
                if novo_status != ultimo_status_antigo:
                    print(f"📦 [Rastreio] Nova movimentação para {cod}: {novo_status}")
                    
                    # Atualiza banco
                    conn_up = get_db_rastreio()
                    with conn_up:
                        conn_up.execute("""
                            UPDATE rastreios 
                            SET ultimo_status = ?, ultimo_local = ?, ultima_data = ?, historico_json = ?, entregue = ?,
                                entregue_em = CASE WHEN ? = 1 AND (entregue_em IS NULL OR entregue_em = 0) THEN ? ELSE entregue_em END
                            WHERE codigo = ? AND user_id = ?
                        """, (novo_status, novo_local, nova_data, hist_json, is_entregue, is_entregue, entregue_em_val, cod, user_id))
                    conn_up.close()

                    cod_masc = mascarar_codigo(cod)
                    emoji = get_status_emoji(novo_status)
                    cor = 0x2ECC71 if is_entregue else (0xF1C40F if "aduaneira" in novo_status.lower() or "pagamento" in novo_status.lower() or "customs" in novo_status.lower() else 0xFF4646)

                    embed = discord.Embed(
                        title=f"🔔 Atualização: {p['nome_pacote']}",
                        description=f"📦 **Pacote:** {p['nome_pacote']}\n🔒 **Código:** `{cod_masc}`\n🚚 **Rota:** {res.get('origem', 'Ship24 / Correios')}",
                        color=cor,
                        timestamp=datetime.now()
                    )
                    embed.add_field(name=f"{emoji} Novo Status", value=f"**{novo_status}**", inline=False)
                    if novo_local:
                        embed.add_field(name="📍 Local", value=novo_local, inline=True)
                    if nova_data:
                        embed.add_field(name="⏰ Horário", value=nova_data, inline=True)

                    if ultimo_status_antigo:
                        embed.add_field(name="📜 Status Anterior", value=ultimo_status_antigo, inline=False)
                        
                    if is_entregue:
                        embed.set_footer(text="🎉 Encomenda entregue! Monitoramento concluído com sucesso.")
                    else:
                        embed.set_footer(text="Bife's Bot • Monitoramento Automático em Tempo Real")

                    enviou_pv = False
                    # 1. Tenta enviar no PV (Mensagem Direta)
                    if notificar_pv:
                        try:
                            user = await self.bot.fetch_user(int(user_id))
                            if user:
                                await user.send(content=f"🔔 **Atualização no pacote `{p['nome_pacote']}` (`{cod_masc}`)!**", embed=embed)
                                enviou_pv = True
                        except Exception as e_pv:
                            print(f"⚠️ [Rastreio] Falha ao enviar DM para {user_id}: {e_pv}")

                    # 2. Se não era para PV ou falhou envio no PV, envia no canal com menção
                    if not enviou_pv:
                        try:
                            channel = self.bot.get_channel(int(channel_id))
                            if channel:
                                await channel.send(content=f"🔔 <@{user_id}> O seu pacote **`{p['nome_pacote']}`** (`{cod_masc}`) foi atualizado!", embed=embed)
                        except Exception as err_send:
                            print(f"⚠️ Erro ao enviar mensagem no canal: {err_send}")

            except Exception as err:
                print(f"⚠️ Erro no loop de rastreio para {p['codigo']}: {err}")

    @verificar_rastreios_loop.before_loop
    async def before_rastreio_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(RastreioCog(bot))
