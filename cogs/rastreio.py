import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import requests
import json
import time
import re
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict

def get_db_rastreio():
    conn = sqlite3.connect("banco.db", timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_rastreio_db():
    conn = get_db_rastreio()
    with conn:
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
                criado_em INTEGER,
                UNIQUE(codigo, user_id)
            )
        """)
    conn.close()

init_rastreio_db()

# ===================================================
#  TRADUTOR CHINÊS / INGLÊS -> PT-BR
# ===================================================

def traduzir_para_pt(texto: str) -> str:
    """ Traduz texto em chinês ou inglês para Português usando a API do Google Translate """
    if not texto:
        return ""
    
    # Se não tiver caracteres chineses nem palavras comuns em inglês, retorna direto
    tem_chines = bool(re.search(r'[\u4e00-\u9fff]', texto))
    if not tem_chines and "delivered" not in texto.lower() and "transit" not in texto.lower() and "customs" not in texto.lower():
        return texto

    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "pt",
            "dt": "t",
            "q": texto
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        res = requests.get(url, params=params, headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json()
            traducao = "".join([part[0] for part in data[0] if part[0]])
            return traducao.strip()
    except Exception as e:
        print(f"⚠️ [Tradutor] Erro ao traduzir '{texto}': {e}")
    
    return texto

# ===================================================
#  APIS DE CONSULTA (CORREIOS + CHINA POST / CAINIAO)
# ===================================================

def consultar_codigo(codigo: str) -> Dict:
    """ Consulta o código nas APIs públicas de Correios e China Post / Cainiao """
    cod_limpo = codigo.strip().upper()
    
    # 1. Tenta API Pública Link & Track (Correios Brasil)
    try:
        url = f"https://api.linketrack.com/track/json?user=teste&token=1abcd00b2731640e886fb41a8a9671ad143c3d4b4f1682cc64c832a24cee11a2&codigo={cod_limpo}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            eventos = data.get("eventos", [])
            if eventos:
                ultimo = eventos[0]
                status_trad = traduzir_para_pt(ultimo.get("status", "Objeto em Trânsito"))
                local_trad = traduzir_para_pt(f"{ultimo.get('local', '')} {ultimo.get('origem', '')} {ultimo.get('destino', '')}".strip())
                data_hora = f"{ultimo.get('data', '')} {ultimo.get('hora', '')}".strip()
                
                lista_eventos = []
                for ev in eventos[:6]:
                    st = traduzir_para_pt(ev.get("status", ""))
                    loc = traduzir_para_pt(ev.get("local", "") or ev.get("origem", ""))
                    dt = f"{ev.get('data', '')} {ev.get('hora', '')}".strip()
                    lista_eventos.append({"status": st, "local": loc, "data": dt})
                
                is_entregue = "entregue" in status_trad.lower() or "delivered" in status_trad.lower()
                
                return {
                    "sucesso": True,
                    "codigo": cod_limpo,
                    "origem": "Correios Brasil",
                    "ultimo_status": status_trad,
                    "ultimo_local": local_trad,
                    "ultima_data": data_hora,
                    "entregue": is_entregue,
                    "historico": lista_eventos
                }
    except Exception as e:
        print(f"⚠️ [LinkTrack] Erro ao rastrear {cod_limpo}: {e}")

    # 2. Tenta API Rastreio Ninja / Correios Alternativo
    try:
        url = f"https://rastreio.ninja/api/track/{cod_limpo}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            events = data.get("events", []) or data.get("historico", [])
            if events:
                ultimo = events[0]
                status_raw = ultimo.get("status") or ultimo.get("description") or "Em trânsito"
                local_raw = ultimo.get("location") or ultimo.get("local") or ""
                data_raw = ultimo.get("date") or ultimo.get("data") or ""
                
                status_trad = traduzir_para_pt(status_raw)
                local_trad = traduzir_para_pt(local_raw)
                
                lista_eventos = []
                for ev in events[:6]:
                    st = traduzir_para_pt(ev.get("status") or ev.get("description") or "")
                    loc = traduzir_para_pt(ev.get("location") or ev.get("local") or "")
                    dt = ev.get("date") or ev.get("data") or ""
                    lista_eventos.append({"status": st, "local": loc, "data": dt})
                    
                is_entregue = "entregue" in status_trad.lower()
                return {
                    "sucesso": True,
                    "codigo": cod_limpo,
                    "origem": "Correios / Internacional",
                    "ultimo_status": status_trad,
                    "ultimo_local": local_trad,
                    "ultima_data": data_raw,
                    "entregue": is_entregue,
                    "historico": lista_eventos
                }
    except Exception as e:
        print(f"⚠️ [RastreioNinja] Erro: {e}")

    # 3. Tenta API Global Cainiao / China Post (AliExpress / China Post)
    try:
        url = f"https://global.cainiao.com/global/detail.json?mailNos={cod_limpo}&lang=zh-CN"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            module = data.get("module", [])
            if module and len(module) > 0:
                detail_list = module[0].get("detailList", [])
                if detail_list:
                    ultimo = detail_list[0]
                    desc_zh = ultimo.get("desc", "")
                    status_trad = traduzir_para_pt(desc_zh)
                    data_raw = ultimo.get("timeStr", "") or datetime.fromtimestamp(ultimo.get("time", time.time()*1000)/1000).strftime("%d/%m/%Y %H:%M")
                    
                    lista_eventos = []
                    for ev in detail_list[:6]:
                        st_ev = traduzir_para_pt(ev.get("desc", ""))
                        dt_ev = ev.get("timeStr", "") or datetime.fromtimestamp(ev.get("time", time.time()*1000)/1000).strftime("%d/%m/%Y %H:%M")
                        lista_eventos.append({"status": st_ev, "local": "China / Internacional", "data": dt_ev})
                        
                    is_entregue = "entregue" in status_trad.lower() or "签收" in desc_zh
                    
                    return {
                        "sucesso": True,
                        "codigo": cod_limpo,
                        "origem": "China Post / Cainiao Global",
                        "ultimo_status": status_trad,
                        "ultimo_local": "China / Trânsito Internacional",
                        "ultima_data": data_raw,
                        "entregue": is_entregue,
                        "historico": lista_eventos
                    }
    except Exception as e:
        print(f"⚠️ [Cainiao] Erro: {e}")

    return {
        "sucesso": False,
        "codigo": cod_limpo,
        "msg": "Código ainda não encontrado no sistema ou postado recentemente. Tente novamente mais tarde."
    }

def get_status_emoji(status: str) -> str:
    s = (status or "").lower()
    if "entregue" in s or "delivered" in s or "concluída" in s:
        return "✅"
    if "saiu para entrega" in s or "out for delivery" in s:
        return "🛵"
    if "aduaneira" in s or "fiscalização" in s or "curitiba" in s or "customs" in s:
        return "🛃"
    if "trânsito" in s or "encaminhado" in s or "transit" in s or "voo" in s:
        return "✈️"
    if "postado" in s or "recebido" in s or "posted" in s:
        return "📦"
    return "🚚"

# ===================================================
#  COG DE RASTREAMENTO DISCORD
# ===================================================

class RastreioCog(commands.Cog, name="Rastreio"):
    def __init__(self, bot):
        self.bot = bot
        self.verificar_rastreios_loop.start()

    def cog_unload(self):
        self.verificar_rastreios_loop.cancel()

    # --- COMANDO SLASH: /rastrear ---
    @app_commands.command(name="rastrear", description="Rastreia uma encomenda dos Correios, China Post ou Cainiao com tradução automática.")
    @app_commands.describe(
        codigo="Código de rastreio (ex: NL123456789BR, LP001234567890)",
        nome="Nome ou apelido para o pacote (ex: Fone Bluetooth, Teclado)"
    )
    async def slash_rastrear(self, interaction: discord.Interaction, codigo: str, nome: Optional[str] = "Minha Encomenda"):
        await interaction.response.defer(thinking=True)
        
        cod_limpo = codigo.strip().upper()
        res = consultar_codigo(cod_limpo)
        
        if not res.get("sucesso"):
            await interaction.followup.send(
                f"❌ Não foi possível encontrar informações para o código **`{cod_limpo}`**.\n"
                f"💡 *Verifique se digitou corretamente ou se o pacote foi postado recentemente.*",
                ephemeral=True
            )
            return

        # Salva ou atualiza no banco de dados para monitoramento
        conn = get_db_rastreio()
        now_ts = int(time.time())
        with conn:
            conn.execute("""
                INSERT INTO rastreios (codigo, nome_pacote, user_id, channel_id, ultimo_status, ultimo_local, ultima_data, entregue, origem, criado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, user_id) DO UPDATE SET 
                    nome_pacote=excluded.nome_pacote,
                    channel_id=excluded.channel_id,
                    ultimo_status=excluded.ultimo_status,
                    ultimo_local=excluded.ultimo_local,
                    ultima_data=excluded.ultima_data,
                    entregue=excluded.entregue
            """, (
                cod_limpo, nome, str(interaction.user.id), str(interaction.channel_id),
                res["ultimo_status"], res["ultimo_local"], res["ultima_data"],
                1 if res["entregue"] else 0, res["origem"], now_ts
            ))
        conn.close()

        emoji = get_status_emoji(res["ultimo_status"])
        embed = discord.Embed(
            title=f"{emoji} Rastreio: {nome}",
            description=f"**Código:** `{cod_limpo}`\n**Transportadora:** {res['origem']}",
            color=0xFF4646 if not res["entregue"] else 0x2ECC71,
            timestamp=datetime.now()
        )
        
        embed.add_field(name="📍 Status Atual", value=f"**{res['ultimo_status']}**", inline=False)
        if res.get("ultimo_local"):
            embed.add_field(name="🏙️ Localização", value=res["ultimo_local"], inline=True)
        if res.get("ultima_data"):
            embed.add_field(name="⏰ Data / Hora", value=res["ultima_data"], inline=True)

        # Histórico recente
        historico = res.get("historico", [])
        if len(historico) > 1:
            historico_txt = ""
            for h in historico[1:5]:
                historico_txt += f"• **{h['data']}** - {h['status']}"
                if h.get('local'): historico_txt += f" ({h['local']})"
                historico_txt += "\n"
            if historico_txt:
                embed.add_field(name="📜 Histórico Recente", value=historico_txt.strip(), inline=False)

        if not res["entregue"]:
            embed.set_footer(text="🔔 O bot avisará neste canal assim que houver qualquer nova movimentação!")
        else:
            embed.set_footer(text="✅ Encomenda entregue ao destinatário!")

        await interaction.followup.send(embed=embed)

    # --- COMANDO SLASH: /minhas_encomendas ---
    @app_commands.command(name="minhas_encomendas", description="Lista todas as suas encomendas salvas para monitoramento.")
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
            description=f"Total de pacotes: **{len(rows)}**",
            color=0xFF4646
        )

        for r in rows:
            emoji = get_status_emoji(r["ultimo_status"])
            status_badge = "✅ Entregue" if r["entregue"] else f"{emoji} {r['ultimo_status'] or 'Em trânsito'}"
            local_info = f"\n📍 {r['ultimo_local']}" if r['ultimo_local'] else ""
            data_info = f" • ⏰ {r['ultima_data']}" if r['ultima_data'] else ""
            
            embed.add_field(
                name=f"{r['nome_pacote']} (`{r['codigo']}`)",
                value=f"**Status:** {status_badge}{local_info}{data_info}",
                inline=False
            )

        embed.set_footer(text="Use /remover_rastreio <codigo> para parar de monitorar um pacote.")
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
            await interaction.response.send_message(f"🗑️ O pacote **`{cod_limpo}`** foi removido do seu monitoramento.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Pacote **`{cod_limpo}`** não encontrado na sua lista.", ephemeral=True)

    # ===================================================
    #  LOOP DE VERIFICAÇÃO AUTOMÁTICA EM SEGUNDO PLANO
    # ===================================================
    @tasks.loop(minutes=25)
    async def verificar_rastreios_loop(self):
        """ Percorre encomendas pendentes e notifica no Discord se houver atualização """
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
                
                # Consulta status atual
                res = consultar_codigo(cod)
                if not res.get("sucesso"):
                    continue

                novo_status = res["ultimo_status"]
                novo_local = res["ultimo_local"]
                nova_data = res["ultima_data"]
                is_entregue = 1 if res["entregue"] else 0

                # Se o status ou data mudaram, NOTIFICA O USUÁRIO!
                if novo_status != ultimo_status_antigo:
                    print(f"📦 [Rastreio] Nova movimentação para {cod}: {novo_status}")
                    
                    # Atualiza banco
                    conn_up = get_db_rastreio()
                    with conn_up:
                        conn_up.execute("""
                            UPDATE rastreios 
                            SET ultimo_status = ?, ultimo_local = ?, ultima_data = ?, entregue = ?
                            WHERE codigo = ? AND user_id = ?
                        """, (novo_status, novo_local, nova_data, is_entregue, cod, user_id))
                    conn_up.close()

                    # Envia notificação no canal do Discord com Menção
                    try:
                        channel = self.bot.get_channel(int(channel_id))
                        if channel:
                            emoji = get_status_emoji(novo_status)
                            embed = discord.Embed(
                                title=f"🔔 Atualização de Encomenda: {p['nome_pacote']}",
                                description=f"O pacote **`{cod}`** teve uma nova movimentação!",
                                color=0x2ECC71 if is_entregue else 0xFF4646,
                                timestamp=datetime.now()
                            )
                            embed.add_field(name=f"{emoji} Novo Status", value=f"**{novo_status}**", inline=False)
                            if novo_local:
                                embed.add_field(name="📍 Local", value=novo_local, inline=True)
                            if nova_data:
                                embed.add_field(name="⏰ Horário", value=nova_data, inline=True)
                                
                            if is_entregue:
                                embed.set_footer(text="🎉 Encomenda entregue! Monitoramento concluído.")
                            else:
                                embed.set_footer(text="📦 Bife's Bot • Monitoramento Automático")

                            await channel.send(content=f"🔔 <@{user_id}> Sua encomenda foi atualizada!", embed=embed)
                    except Exception as err_send:
                        print(f"⚠️ Erro ao enviar mensagem de rastreio no Discord: {err_send}")

            except Exception as err:
                print(f"⚠️ Erro no loop de rastreio para {p['codigo']}: {err}")

    @verificar_rastreios_loop.before_loop
    async def before_rastreio_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(RastreioCog(bot))
