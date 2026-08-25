import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import asyncio
from datetime import datetime, timedelta
import yfinance as yf

DB_PATH = "bifinhos.db"

# ==========================================
#              LISTA DE ATIVOS
# ==========================================
ATIVOS = {
    # 🪙 Criptomoedas (Em USD, o bot converte para BRL em tempo real)
    "BITCOIN": {"ticker": "BTC-USD", "emoji": "₿", "tipo": "cripto"},
    "ETHEREUM": {"ticker": "ETH-USD", "emoji": "🪙", "tipo": "cripto"},
    
    # 🎮 Tech e Games
    "ROBLOX": {"ticker": "R2BL34.SA", "emoji": "🟦", "tipo": "b3"},
    "NVIDIA": {"ticker": "NVDC34.SA", "emoji": "🟩", "tipo": "b3"},
    "AMD": {"ticker": "A1MD34.SA", "emoji": "🟧", "tipo": "b3"},
    "APPLE": {"ticker": "AAPL34.SA", "emoji": "🍎", "tipo": "b3"},
    "MICROSOFT": {"ticker": "MSFT34.SA", "emoji": "🪟", "tipo": "b3"},
    "SONY": {"ticker": "SNEC34.SA", "emoji": "🎮", "tipo": "b3"},
    "GOOGLE": {"ticker": "GOGL34.SA", "emoji": "🔍", "tipo": "b3"},
    "META": {"ticker": "M1TA34.SA", "emoji": "♾️", "tipo": "b3"},
    "AMAZON": {"ticker": "AMZO34.SA", "emoji": "📦", "tipo": "b3"},
    "INTEL": {"ticker": "ITLC34.SA", "emoji": "💻", "tipo": "b3"},
    
    # 🍿 Entretenimento / Global
    "NETFLIX": {"ticker": "NFLX34.SA", "emoji": "🎬", "tipo": "b3"},
    "DISNEY": {"ticker": "DISB34.SA", "emoji": "🏰", "tipo": "b3"},
    "SPOTIFY": {"ticker": "S1PO34.SA", "emoji": "🎧", "tipo": "b3"},
    "TESLA": {"ticker": "TSLA34.SA", "emoji": "🚗", "tipo": "b3"},
    "COCA-COLA": {"ticker": "COCA34.SA", "emoji": "🥤", "tipo": "b3"},
    "MERCADOLIVRE": {"ticker": "MELI34.SA", "emoji": "🤝", "tipo": "b3"},
    
    # 🇧🇷 Gigantes Brasileiras
    "PETROBRAS": {"ticker": "PETR4.SA", "emoji": "⛽", "tipo": "b3"},
    "VALE": {"ticker": "VALE3.SA", "emoji": "⛏️", "tipo": "b3"},
    "NUBANK": {"ticker": "ROXO34.SA", "emoji": "🟪", "tipo": "b3"},
    "ITAU": {"ticker": "ITUB4.SA", "emoji": "🏦", "tipo": "b3"},
    "BANCODOBRASIL": {"ticker": "BBAS3.SA", "emoji": "🏧", "tipo": "b3"},
    "AMBEV": {"ticker": "ABEV3.SA", "emoji": "🍻", "tipo": "b3"},
    "MAGALU": {"ticker": "MGLU3.SA", "emoji": "🛍️", "tipo": "b3"},
    "WEG": {"ticker": "WEGE3.SA", "emoji": "⚡", "tipo": "b3"},
    "EMBRAER": {"ticker": "EMBR3.SA", "emoji": "✈️", "tipo": "b3"},
    "B3": {"ticker": "B3SA3.SA", "emoji": "📈", "tipo": "b3"},
    "LOCALIZA": {"ticker": "RENT3.SA", "emoji": "🚙", "tipo": "b3"},
    "SUZANO": {"ticker": "SUZB3.SA", "emoji": "🌲", "tipo": "b3"}
}

# ==========================================
#              FUNÇÕES DE BANCO
# ==========================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_acoes_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS carteira_acoes (
            user_id TEXT,
            ativo TEXT,
            quantidade INTEGER NOT NULL,
            preco_medio_bifinhos REAL NOT NULL,
            PRIMARY KEY (user_id, ativo)
        )
    ''')
    conn.commit()
    conn.close()

def get_balance(user_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT balance FROM bifinhos WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def change_balance(user_id: str, amount: int):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT balance FROM bifinhos WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE bifinhos SET balance = ? WHERE user_id = ?", (max(0, row[0] + amount), user_id))
    else:
        c.execute("INSERT INTO bifinhos (user_id, balance, last_claim) VALUES (?, ?, 0)", (user_id, max(0, amount)))
    conn.commit()
    conn.close()

def registrar_ganho_mensal(user_id: str, quantidade: int, tipo_ganho: str):
    now = datetime.now()
    mes_ano = now.strftime("%m/%Y")
    timestamp = int(now.timestamp())
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO historico_mensal (user_id, mes_ano, quantidade, tipo_ganho, data_timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, mes_ano, quantidade, tipo_ganho, timestamp))
    conn.commit()
    conn.close()

def get_user_ativo(user_id: str, ativo: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT quantidade, preco_medio_bifinhos FROM carteira_acoes WHERE user_id = ? AND ativo = ?", (user_id, ativo))
    row = c.fetchone()
    conn.close()
    return row if row else (0, 0.0)

def get_full_carteira(user_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT ativo, quantidade, preco_medio_bifinhos FROM carteira_acoes WHERE user_id = ? AND quantidade > 0", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def update_user_ativo(user_id: str, ativo: str, nova_qtd: int, novo_preco_medio: float):
    conn = get_db_connection()
    c = conn.cursor()
    if nova_qtd <= 0:
        c.execute("DELETE FROM carteira_acoes WHERE user_id = ? AND ativo = ?", (user_id, ativo))
    else:
        c.execute('''
            INSERT INTO carteira_acoes (user_id, ativo, quantidade, preco_medio_bifinhos)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, ativo) DO UPDATE SET
            quantidade=excluded.quantidade,
            preco_medio_bifinhos=excluded.preco_medio_bifinhos
        ''', (user_id, ativo, nova_qtd, novo_preco_medio))
    conn.commit()
    conn.close()


# ==========================================
#              LÓGICA DE MERCADO
# ==========================================
def is_market_open(tipo_ativo: str):
    if tipo_ativo == "cripto": return True 
    hora_brasilia = datetime.utcnow() - timedelta(hours=3)
    if hora_brasilia.weekday() <= 4 and 10 <= hora_brasilia.hour < 17: return True
    return False

def fetch_usd_brl_sync():
    """Busca a cotação exata do Dólar para Real em tempo real."""
    try:
        ativo = yf.Ticker("USDBRL=X")
        return float(ativo.fast_info['lastPrice'])
    except Exception:
        try:
            data = yf.Ticker("USDBRL=X").history(period="5d")
            if not data.empty:
                return float(data['Close'].iloc[-1])
        except:
            pass
        return 5.0 # Fallback de segurança

def fetch_price_sync(ticker: str):
    try:
        ativo = yf.Ticker(ticker)
        return float(ativo.fast_info['lastPrice'])
    except Exception:
        try:
            data = yf.Ticker(ticker).history(period="5d")
            if not data.empty:
                return float(data['Close'].iloc[-1])
        except:
            pass
        return None

async def obter_dados_ativo(nome_ativo: str):
    nome_ativo = nome_ativo.upper()
    if nome_ativo not in ATIVOS:
        return False, "❌ Ativo não encontrado! Use `/mercado lista` ou `!mercado lista` para ver as opções.", None, None

    info = ATIVOS[nome_ativo]
    preco_base = await asyncio.to_thread(fetch_price_sync, info["ticker"])
    
    if preco_base is None:
        return False, f"🟡 **{info['emoji']} {nome_ativo}**: O servidor financeiro não conseguiu obter o preço agora. Tente mais tarde.", None, None

    if info["tipo"] == "cripto":
        cotacao_dolar = await asyncio.to_thread(fetch_usd_brl_sync)
        preco_brl = preco_base * cotacao_dolar
    else:
        preco_brl = preco_base

    return True, info, preco_brl, int(preco_brl * 100), is_market_open(info["tipo"])


# ==========================================
#              COG DO BOT
# ==========================================
class MercadoAcoes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_acoes_db()

    # --- LÓGICA CENTRALIZADA ---
    def _build_lista_embed(self):
        embed = discord.Embed(title="📊 Bolsa de Valores de Bifinhos", description="Invista em ações do mundo real!\n*(R$ 1,00 = 100 Bifinhos)*", color=0x2b2d31)
        cripto, tech, pop, br = [], [], [], []

        for nome, info in ATIVOS.items():
            linha = f"{info['emoji']} `{nome}`"
            if info['tipo'] == "cripto": cripto.append(linha)
            elif "34.SA" in info['ticker'] and nome in ["ROBLOX", "NVIDIA", "AMD", "APPLE", "MICROSOFT", "SONY", "GOOGLE", "META", "AMAZON", "INTEL"]: tech.append(linha)
            elif "34.SA" in info['ticker']: pop.append(linha)
            else: br.append(linha)

        embed.add_field(name="🪙 Criptomoedas (24/7)", value="\n".join(cripto), inline=False)
        embed.add_field(name="💻 Tech & Games", value="\n".join(tech), inline=True)
        embed.add_field(name="🍿 Global & Entretenimento", value="\n".join(pop), inline=True)
        embed.add_field(name="🇧🇷 Gigantes Nacionais", value="\n".join(br), inline=False)
        embed.set_footer(text="Dica: Use /mercado preco <nome> ou !mercado preco <nome> para ver o valor!")
        return embed

    async def _logic_preco(self, ativo: str):
        sucesso, info_ou_erro, preco_brl, preco_bifinhos, aberto = await obter_dados_ativo(ativo)
        if not sucesso: return False, info_ou_erro

        status_emoji = "🟢 ABERTO" if aberto else "🔴 FECHADO"
        embed = discord.Embed(title=f"{info_ou_erro['emoji']} Cotação: {ativo.upper()}", color=discord.Color.green() if aberto else discord.Color.red())
        embed.add_field(name="Valor no Mundo Real", value=f"**R$ {preco_brl:,.2f}**", inline=True)
        embed.add_field(name="Valor no Bot", value=f"🥩 **{preco_bifinhos:,}** Bifinhos", inline=True)
        embed.add_field(name="Status do Mercado", value=status_emoji, inline=False)
        
        if not aberto:
            embed.set_footer(text="Ações da B3 só operam de Segunda a Sexta, das 10h às 17h.")
        return True, embed

    async def _logic_comprar(self, user: discord.User, ativo: str, quantidade: int):
        if quantidade <= 0: return False, "❌ A quantidade deve ser maior que zero."
        
        sucesso, info_ou_erro, preco_brl, preco_bifinhos, aberto = await obter_dados_ativo(ativo)
        if not sucesso: return False, info_ou_erro
        if not aberto: return False, f"🔴 O mercado para **{ativo.upper()}** está fechado agora! Volte em horário comercial."

        custo_total = preco_bifinhos * quantidade
        saldo = get_balance(str(user.id))
        
        if saldo < custo_total:
            return False, f"❌ Você não tem saldo suficiente! Custa **{custo_total:,}** bifinhos, mas você tem **{saldo:,}**."

        change_balance(str(user.id), -custo_total)
        
        qtd_atual, preco_medio_atual = get_user_ativo(str(user.id), ativo.upper())
        nova_qtd = qtd_atual + quantidade
        novo_preco_medio = ((qtd_atual * preco_medio_atual) + custo_total) / nova_qtd
        
        update_user_ativo(str(user.id), ativo.upper(), nova_qtd, novo_preco_medio)

        embed = discord.Embed(title="🧾 Recibo de Compra", color=0x2ecc71)
        embed.description = f"**Comprador:** {user.mention}\n**Ativo:** {info_ou_erro['emoji']} {ativo.upper()}\n**Quantidade:** {quantidade}"
        embed.add_field(name="Preço Pago (Unidade)", value=f"{preco_bifinhos:,} 🥩", inline=True)
        embed.add_field(name="Custo Total", value=f"**{custo_total:,} 🥩**", inline=True)
        embed.set_footer(text=f"Você agora possui {nova_qtd} cotas deste ativo.")
        return True, embed

    async def _logic_vender(self, user: discord.User, ativo: str, quantidade: int):
        if quantidade <= 0: return False, "❌ A quantidade deve ser maior que zero."
        
        qtd_atual, preco_medio = get_user_ativo(str(user.id), ativo.upper())
        if qtd_atual < quantidade:
            return False, f"❌ Você não possui {quantidade} ações de **{ativo.upper()}**. Você tem **{qtd_atual}**."

        sucesso, info_ou_erro, preco_brl, preco_bifinhos, aberto = await obter_dados_ativo(ativo)
        if not sucesso: return False, info_ou_erro
        if not aberto: return False, f"🔴 O mercado para **{ativo.upper()}** está fechado agora! Não é possível vender."

        valor_venda = preco_bifinhos * quantidade
        lucro_ou_prejuizo = valor_venda - int(preco_medio * quantidade)

        change_balance(str(user.id), valor_venda)
        update_user_ativo(str(user.id), ativo.upper(), qtd_atual - quantidade, preco_medio)
        
        if lucro_ou_prejuizo > 0:
            registrar_ganho_mensal(str(user.id), lucro_ou_prejuizo, "acoes")

        embed = discord.Embed(title="🧾 Recibo de Venda", color=0x3498db)
        embed.description = f"**Vendedor:** {user.mention}\n**Ativo:** {info_ou_erro['emoji']} {ativo.upper()}\n**Quantidade Vendida:** {quantidade}"
        embed.add_field(name="Valor Recebido", value=f"**{valor_venda:,} 🥩**", inline=True)
        
        if lucro_ou_prejuizo > 0:
            embed.add_field(name="Lucro Obtido 📈", value=f"+ {lucro_ou_prejuizo:,} 🥩", inline=False)
            embed.color = discord.Color.green()
        elif lucro_ou_prejuizo < 0:
            embed.add_field(name="Prejuízo 📉", value=f"{lucro_ou_prejuizo:,} 🥩", inline=False)
            embed.color = discord.Color.red()
        else:
            embed.add_field(name="Resultado ➖", value="Saiu no zero a zero", inline=False)
        return True, embed

    async def _logic_carteira(self, user: discord.User):
        acoes_usuario = get_full_carteira(str(user.id))
        if not acoes_usuario:
            return False, "💼 Sua carteira está vazia! Use `!mercado lista` e `!mercado comprar` para começar."

        embed = discord.Embed(title=f"💼 Carteira de Ações de {user.display_name}", color=0x2b2d31)
        valor_total_investido, valor_patrimonio_atual = 0, 0

        # Checa se existe alguma cripto na carteira para baixar o dólar uma vez só e economizar tempo
        precisa_dolar = any(ATIVOS.get(a, {}).get("tipo") == "cripto" for a, _, _ in acoes_usuario)
        cotacao_dolar = await asyncio.to_thread(fetch_usd_brl_sync) if precisa_dolar else 5.0

        for ativo, quantidade, preco_medio in acoes_usuario:
            info = ATIVOS.get(ativo, {"emoji": "📄"})
            try:
                preco_base = await asyncio.to_thread(fetch_price_sync, ATIVOS[ativo]["ticker"])
                if preco_base is None: raise Exception()
                
                if ATIVOS[ativo]["tipo"] == "cripto":
                    preco_brl = preco_base * cotacao_dolar
                else:
                    preco_brl = preco_base
                    
                preco_atual_bifinhos = int(preco_brl * 100)
            except:
                preco_atual_bifinhos = int(preco_medio)

            investido_neste = int(preco_medio * quantidade)
            patrimonio_neste = preco_atual_bifinhos * quantidade
            pnl = patrimonio_neste - investido_neste
            
            valor_total_investido += investido_neste
            valor_patrimonio_atual += patrimonio_neste
            
            sinal = "🟩" if pnl >= 0 else "🟥"
            texto_pnl = f"+{pnl:,}" if pnl >= 0 else f"{pnl:,}"
            
            embed.add_field(
                name=f"{info['emoji']} {ativo}", 
                value=f"**Qtd:** {quantidade}\n**Médio:** {int(preco_medio):,} 🥩\n**Atual:** {preco_atual_bifinhos:,} 🥩\n**L/P:** {sinal} `{texto_pnl}`", 
                inline=True
            )

        pnl_geral = valor_patrimonio_atual - valor_total_investido
        sinal_geral = "📈 Lucro" if pnl_geral >= 0 else "📉 Prejuízo"
        embed.set_footer(text=f"💰 Patrimônio Atual: {valor_patrimonio_atual:,} Bifinhos\n{sinal_geral} Total: {pnl_geral:,} Bifinhos")
        return True, embed

    # ==========================================
    #            COMANDOS DE PREFIXO (!)
    # ==========================================
    @commands.group(name="mercado", invoke_without_command=True)
    async def prefix_mercado(self, ctx):
        await ctx.send("📋 Como usar o mercado:\n`!mercado lista`\n`!mercado preco <ativo>`\n`!mercado comprar <ativo> <qtd>`\n`!mercado vender <ativo> <qtd>`")

    @prefix_mercado.command(name="lista")
    async def prefix_lista(self, ctx):
        await ctx.send(embed=self._build_lista_embed())

    @prefix_mercado.command(name="preco")
    async def prefix_preco(self, ctx, ativo: str):
        msg = await ctx.send("⏳ Consultando a bolsa de valores...")
        sucesso, resposta = await self._logic_preco(ativo)
        if sucesso: await msg.edit(content=None, embed=resposta)
        else: await msg.edit(content=resposta)

    @prefix_mercado.command(name="comprar")
    async def prefix_comprar(self, ctx, ativo: str, quantidade: int):
        msg = await ctx.send("⏳ Processando ordem de compra...")
        sucesso, resposta = await self._logic_comprar(ctx.author, ativo, quantidade)
        if sucesso: await msg.edit(content=None, embed=resposta)
        else: await msg.edit(content=resposta)

    @prefix_mercado.command(name="vender")
    async def prefix_vender(self, ctx, ativo: str, quantidade: int):
        msg = await ctx.send("⏳ Processando ordem de venda...")
        sucesso, resposta = await self._logic_vender(ctx.author, ativo, quantidade)
        if sucesso: await msg.edit(content=None, embed=resposta)
        else: await msg.edit(content=resposta)

    @commands.command(name="carteira")
    async def prefix_carteira(self, ctx):
        msg = await ctx.send("💼 Analisando sua carteira e buscando cotações em tempo real...")
        sucesso, resposta = await self._logic_carteira(ctx.author)
        if sucesso: await msg.edit(content=None, embed=resposta)
        else: await msg.edit(content=resposta)

    # ==========================================
    #            COMANDOS DE SLASH (/)
    # ==========================================
    mercado_group = app_commands.Group(name="mercado", description="Opere na Bolsa de Valores usando seus Bifinhos!")

    @mercado_group.command(name="lista", description="Mostra todas as ações e criptos disponíveis para investir.")
    async def slash_lista(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self._build_lista_embed())

    @mercado_group.command(name="preco", description="Consulta o preço atual de uma ação em Bifinhos.")
    @app_commands.describe(ativo="O nome da ação (Ex: ROBLOX, PETROBRAS, BITCOIN)")
    async def slash_preco(self, interaction: discord.Interaction, ativo: str):
        await interaction.response.defer(thinking=True)
        sucesso, resposta = await self._logic_preco(ativo)
        if sucesso: await interaction.followup.send(embed=resposta)
        else: await interaction.followup.send(resposta)

    @mercado_group.command(name="comprar", description="Compra uma quantidade de ações.")
    @app_commands.describe(ativo="Nome da ação", quantidade="Quantas você quer comprar?")
    async def slash_comprar(self, interaction: discord.Interaction, ativo: str, quantidade: int):
        await interaction.response.defer(thinking=True)
        sucesso, resposta = await self._logic_comprar(interaction.user, ativo, quantidade)
        if sucesso: await interaction.followup.send(embed=resposta)
        else: await interaction.followup.send(resposta)

    @mercado_group.command(name="vender", description="Vende suas ações e lucra (ou chora no prejuízo).")
    @app_commands.describe(ativo="Nome da ação", quantidade="Quantas você quer vender?")
    async def slash_vender(self, interaction: discord.Interaction, ativo: str, quantidade: int):
        await interaction.response.defer(thinking=True)
        sucesso, resposta = await self._logic_vender(interaction.user, ativo, quantidade)
        if sucesso: await interaction.followup.send(embed=resposta)
        else: await interaction.followup.send(resposta)

    @app_commands.command(name="carteira", description="Mostra todas as ações que você possui e seus lucros/prejuízos.")
    async def slash_carteira(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        sucesso, resposta = await self._logic_carteira(interaction.user)
        if sucesso: await interaction.followup.send(embed=resposta)
        else: await interaction.followup.send(resposta)

async def setup(bot: commands.Bot):
    await bot.add_cog(MercadoAcoes(bot))