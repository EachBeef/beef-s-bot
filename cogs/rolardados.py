import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import random
import asyncio
from datetime import datetime

DB_PATH = "bifinhos.db"

# ==========================================
#              FUNÇÕES DE BANCO
# ==========================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

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
    c.execute("SELECT balance, last_claim FROM bifinhos WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    
    if row:
        new_balance = max(0, row[0] + amount)
        c.execute("UPDATE bifinhos SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    else:
        new_balance = max(0, amount)
        c.execute("INSERT INTO bifinhos (user_id, balance, last_claim) VALUES (?, ?, 0)", (user_id, new_balance))
        
    conn.commit()
    conn.close()
    return new_balance

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

# ==========================================
#              VIEW DE DESAFIO
# ==========================================
class DadosAcceptView(discord.ui.View):
    def __init__(self, challenger: discord.Member, challenged: discord.Member, bet: int):
        super().__init__(timeout=60) # 1 minuto para aceitar
        self.challenger = challenger
        self.challenged = challenged
        self.bet = bet
        self.accepted = False

    @discord.ui.button(label="Aceitar Desafio", style=discord.ButtonStyle.success, emoji="🎲")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.challenged:
            return await interaction.response.send_message("❌ Esse desafio não é para você!", ephemeral=True)

        bal_challenger = get_balance(str(self.challenger.id))
        bal_challenged = get_balance(str(self.challenged.id))

        if bal_challenger < self.bet:
            return await interaction.response.send_message(f"❌ {self.challenger.display_name} gastou o dinheiro e não tem mais os {self.bet} bifinhos!", ephemeral=True)
        if bal_challenged < self.bet:
            return await interaction.response.send_message(f"❌ Você não tem {self.bet} bifinhos suficientes para entrar no desafio!", ephemeral=True)

        self.accepted = True
        for child in self.children:
            child.disabled = True

        # Desconta os valores de ambos
        change_balance(str(self.challenger.id), -self.bet)
        change_balance(str(self.challenged.id), -self.bet)

        # Atualiza a mensagem original para mostrar que começou
        await interaction.response.edit_message(content="🎲 **Desafio Aceito! Rolando os dados na mesa...**", embed=None, view=self)
        
        # Suspense dramático de 2 segundos
        await asyncio.sleep(2)

        # Rola os dados D20
        dado_challenger = random.randint(1, 20)
        dado_challenged = random.randint(1, 20)

        # Prepara a mensagem de resultado
        embed = discord.Embed(title="🎲 Duelo de Dados (D20)", color=0x2b2d31)
        embed.add_field(name=f"🎮 {self.challenger.display_name}", value=f"Tirou: **{dado_challenger}**", inline=True)
        embed.add_field(name=f"🎯 {self.challenged.display_name}", value=f"Tirou: **{dado_challenged}**", inline=True)

        if dado_challenger > dado_challenged:
            embed.description = f"🏆 {self.challenger.mention} venceu com o maior número!\n💰 Prêmio: **{self.bet * 2} Bifinhos**"
            embed.color = discord.Color.gold()
            change_balance(str(self.challenger.id), self.bet * 2)
            registrar_ganho_mensal(str(self.challenger.id), self.bet, "dados") # Lucro pro rank
            
        elif dado_challenged > dado_challenger:
            embed.description = f"🏆 {self.challenged.mention} venceu com o maior número!\n💰 Prêmio: **{self.bet * 2} Bifinhos**"
            embed.color = discord.Color.gold()
            change_balance(str(self.challenged.id), self.bet * 2)
            registrar_ganho_mensal(str(self.challenged.id), self.bet, "dados") # Lucro pro rank
            
        else:
            embed.description = f"🤝 **EMPATE!** Vocês tiraram o mesmo número. Os **{self.bet} Bifinhos** voltaram para as duas carteiras."
            embed.color = discord.Color.light_gray()
            change_balance(str(self.challenger.id), self.bet)
            change_balance(str(self.challenged.id), self.bet)

        # Envia o resultado final
        await interaction.followup.send(embed=embed)
        self.stop()

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.secondary, emoji="❌")
    async def btn_decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.challenged:
            return await interaction.response.send_message("❌ Esse desafio não é para você!", ephemeral=True)
            
        self.accepted = True
        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(content=f"💨 {self.challenged.mention} correu do desafio de dados do {self.challenger.mention}!", embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        if not self.accepted:
            for child in self.children:
                child.disabled = True
            pass

# ==========================================
#              COG DO BOT
# ==========================================
class RolarDados(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _handle_dados_logic(self, challenger: discord.Member, challenged: discord.Member, bet: int):
        if bet <= 0:
            return False, "❌ O valor do desafio deve ser maior que zero!"
        
        if challenged.bot:
            return False, "❌ Você não pode desafiar bots para jogar dados!"
            
        if challenged == challenger:
            return False, "❌ Você não pode desafiar a si mesmo!"

        bal_challenger = get_balance(str(challenger.id))
        bal_challenged = get_balance(str(challenged.id))

        if bal_challenger < bet:
            return False, f"❌ Você não tem bifinhos suficientes! Seu saldo: **{bal_challenger}**"
            
        if bal_challenged < bet:
            return False, f"❌ {challenged.display_name} não tem bifinhos suficientes para cobrir esse desafio! Saldo dele(a): **{bal_challenged}**"

        embed = discord.Embed(
            title="🎲 DESAFIO DE DADOS (D20)",
            description=f"{challenger.mention} desafiou {challenged.mention} para um rolar de dados!\n\nQuem tirar o maior número no D20 leva o prêmio.\n💰 **Prêmio em jogo:** {bet * 2} Bifinhos",
            color=discord.Color.blue()
        )
        embed.set_footer(text="O oponente tem 60 segundos para aceitar.")

        view = DadosAcceptView(challenger, challenged, bet)
        return True, (embed, view)

    # --- COMANDO DE PREFIXO (!) ---
    @commands.command(name="rolardados")
    async def prefix_rolardados(self, ctx, oponente: discord.Member, valor: int):
        success, result = await self._handle_dados_logic(ctx.author, oponente, valor)
        if not success:
            return await ctx.send(result)
        embed, view = result
        await ctx.send(content=oponente.mention, embed=embed, view=view)

    @prefix_rolardados.error
    async def rolardados_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument) or isinstance(error, commands.BadArgument):
            await ctx.send("❌ Como usar: `!rolardados @usuario <quantidade>`\nExemplo: `!rolardados @Impie 20`")

    # --- COMANDO DE SLASH (/) ---
    @app_commands.command(name="rolardados", description="Desafie um amigo nos dados (D20)! Quem tirar o maior número vence.")
    @app_commands.describe(oponente="Quem você quer desafiar?", valor="Quantos bifinhos vão colocar na mesa?")
    async def slash_rolardados(self, interaction: discord.Interaction, oponente: discord.Member, valor: int):
        success, result = await self._handle_dados_logic(interaction.user, oponente, valor)
        
        if not success:
            return await interaction.response.send_message(result, ephemeral=True)
            
        embed, view = result
        await interaction.response.send_message(content=oponente.mention, embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(RolarDados(bot))