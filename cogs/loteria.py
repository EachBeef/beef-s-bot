import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import random
import datetime

DB_PATH = "bifinhos.db"

# ==========================================
#              CONFIGURAÇÕES
# ==========================================
PRECO_BILHETE = 500
PREMIO_BASE = 8000

# ⚠️ COLOQUE AQUI O ID DO CANAL DO SEU SERVIDOR OFICIAL ONDE O BOT ANUNCIARÁ O GANHADOR GLOBAL
CANAL_LOTERIA_ID = 1479252821688848499 

# ==========================================
#              FUNÇÕES DE BANCO
# ==========================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_loteria_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS loteria (
            user_id TEXT PRIMARY KEY,
            bilhetes INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

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

def get_balance(user_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT balance FROM bifinhos WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def registrar_ganho_mensal(user_id: str, quantidade: int, tipo_ganho: str):
    now = datetime.datetime.now()
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
#              COG DA LOTERIA
# ==========================================
class Loteria(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_loteria_db()
        self.sorteio_loteria.start() # Inicia o relógio do sorteio automático

    def cog_unload(self):
        self.sorteio_loteria.cancel()

    # --- LÓGICA CENTRAL (Reutilizada por Prefix e Slash) ---
    def get_info_loteria(self):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT SUM(bilhetes), COUNT(DISTINCT user_id) FROM loteria")
        row = c.fetchone()
        conn.close()
        
        total_bilhetes = row[0] if row and row[0] else 0
        total_pessoas = row[1] if row and row[1] else 0
        premio_acumulado = PREMIO_BASE + (total_bilhetes * PRECO_BILHETE)
        
        return total_bilhetes, total_pessoas, premio_acumulado

    def _build_info_embed(self, user_id: str):
        total_bilhetes, total_pessoas, premio = self.get_info_loteria()
        
        conn = get_db_connection()
        row = conn.execute("SELECT bilhetes FROM loteria WHERE user_id = ?", (user_id,)).fetchone()
        meus_bilhetes = row[0] if row else 0
        conn.close()

        chance = (meus_bilhetes / total_bilhetes * 100) if total_bilhetes > 0 else 0.0

        embed = discord.Embed(title="🎟️ Loteria Semanal dos Bifinhos", color=0xf1c40f)
        embed.description = "Os sorteios ocorrem automaticamente toda **Quinta-feira** e **Domingo** às **20:00** (Horário de Brasília)!"
        
        embed.add_field(name="💰 Prêmio Acumulado", value=f"**{premio:,} 🥩**", inline=False)
        
        status_global = f"**{total_bilhetes}** bilhetes vendidos\n**{total_pessoas}** participantes na disputa"
        embed.add_field(name="🌐 Status Global", value=status_global, inline=True)
        
        status_pessoal = f"Você tem **{meus_bilhetes}** bilhetes\n*(Sua chance: {chance:.1f}%)*"
        embed.add_field(name="🎫 Seus Bilhetes", value=status_pessoal, inline=True)
        
        embed.set_footer(text=f"Preço por bilhete: {PRECO_BILHETE} Bifinhos")
        return embed

    def _logic_comprar(self, user: discord.Member | discord.User, quantidade: int):
        if quantidade <= 0:
            return False, discord.Embed(description="❌ Você precisa comprar pelo menos 1 bilhete.", color=discord.Color.red())

        custo_total = quantidade * PRECO_BILHETE
        saldo = get_balance(str(user.id))

        if saldo < custo_total:
            return False, discord.Embed(description=f"❌ Saldo insuficiente.\n{quantidade} bilhetes custam **{custo_total:,} 🥩**, mas você só tem **{saldo:,} 🥩**.", color=discord.Color.red())

        # Desconta o dinheiro e adiciona os bilhetes
        change_balance(str(user.id), -custo_total)
        
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO loteria (user_id, bilhetes) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET bilhetes = bilhetes + ?
        ''', (str(user.id), quantidade, quantidade))
        conn.commit()
        conn.close()

        _, _, novo_premio = self.get_info_loteria()

        embed = discord.Embed(title="🎟️ Compra Aprovada!", color=0x2ecc71)
        embed.description = f"Você comprou **{quantidade}** bilhetes por **{custo_total:,} 🥩**.\n\n📈 O prêmio acumulado subiu para **{novo_premio:,} Bifinhos**!\nUse `/loteria info` para ver sua chance de ganhar."
        return True, embed

    # ==========================================
    #            COMANDOS DE PREFIXO (!)
    # ==========================================
    @commands.group(name="loteria", invoke_without_command=True)
    async def prefix_loteria(self, ctx):
        await ctx.send("📋 **Como jogar na Loteria:**\n`!loteria info` - Veja o prêmio e seus bilhetes.\n`!loteria comprar <quantidade>` - Compre bilhetes para o sorteio.")

    @prefix_loteria.command(name="info")
    async def prefix_info(self, ctx):
        await ctx.send(embed=self._build_info_embed(str(ctx.author.id)))

    @prefix_loteria.command(name="comprar")
    async def prefix_comprar(self, ctx, quantidade: int):
        sucesso, embed = self._logic_comprar(ctx.author, quantidade)
        await ctx.send(embed=embed)

    # ==========================================
    #            COMANDOS DE SLASH (/)
    # ==========================================
    loteria_group = app_commands.Group(name="loteria", description="Participe da Loteria Global dos Bifinhos!")

    @loteria_group.command(name="info", description="Veja o prêmio acumulado e quantos bilhetes você tem.")
    async def slash_info(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self._build_info_embed(str(interaction.user.id)))

    @loteria_group.command(name="comprar", description="Compre bilhetes para tentar a sorte grande!")
    @app_commands.describe(quantidade="Quantos bilhetes você quer comprar?")
    async def slash_comprar(self, interaction: discord.Interaction, quantidade: int):
        sucesso, embed = self._logic_comprar(interaction.user, quantidade)
        await interaction.response.send_message(embed=embed, ephemeral=not sucesso)


    # ==========================================
    #         MOTOR DE SORTEIO AUTOMÁTICO
    # ==========================================
    # Horário de Brasília (BRT) é UTC-3. Portanto, 20:00 BRT = 23:00 UTC.
    hora_programada = datetime.time(hour=23, minute=0, tzinfo=datetime.timezone.utc)

    @tasks.loop(time=hora_programada)
    async def sorteio_loteria(self):
        # Verifica se hoje é Quinta (3) ou Domingo (6)
        agora_brt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)
        if agora_brt.weekday() not in [3, 6]:
            return 

        await self._executar_sorteio()

    async def _executar_sorteio(self):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, bilhetes FROM loteria")
        participantes = c.fetchall()

        canal = self.bot.get_channel(CANAL_LOTERIA_ID)
        if not canal:
            conn.close()
            print("❌ ERRO: Canal da loteria não encontrado. Verifique o CANAL_LOTERIA_ID.")
            return

        if not participantes:
            embed_vazio = discord.Embed(title="🎟️ Sorteio da Loteria Global", description="Chegou a hora do sorteio, mas **ninguém comprou bilhetes** esta semana!\nO prêmio de 8.000 🥩 continua acumulado.", color=discord.Color.light_grey())
            conn.close()
            return await canal.send(embed=embed_vazio)

        total_bilhetes = sum(qtd for _, qtd in participantes)
        premio_final = PREMIO_BASE + (total_bilhetes * PRECO_BILHETE)

        # Cria a Urna (Ex: se comprou 3 bilhetes, o ID aparece 3 vezes na lista)
        urna = []
        for user_id, qtd in participantes:
            urna.extend([user_id] * qtd)

        # Roda a Roleta!
        vencedor_id = random.choice(urna)

        # Paga o vencedor e registra no ranking
        change_balance(vencedor_id, premio_final)
        registrar_ganho_mensal(vencedor_id, premio_final, "loteria")

        # Zera a loteria
        c.execute("DELETE FROM loteria")
        conn.commit()
        conn.close()

        # O Grande Anúncio (Sem @everyone)
        vencedor_user = self.bot.get_user(int(vencedor_id))
        mencao = vencedor_user.mention if vencedor_user else f"<@{vencedor_id}>"
        
        embed = discord.Embed(
            title="🚨 RESULTADO DA LOTERIA GLOBAL 🚨", 
            description=f"A roleta parou de girar! Tivemos **{total_bilhetes} bilhetes** vendidos nesta edição em todos os servidores.\n\n🎉 Parabéns {mencao}!!!\n💰 **Você tirou a sorte grande e ganhou {premio_final:,} Bifinhos!**",
            color=0xf1c40f
        )
        embed.set_thumbnail(url="https://raw.githubusercontent.com/jdecked/twemoji/master/assets/72x72/1f39f.png")
        embed.set_footer(text="A próxima loteria global já começou! Use /loteria comprar para participar.")
        
        # Envia apenas a embed, sem ping
        await canal.send(embed=embed)

    @sorteio_loteria.before_loop
    async def before_sorteio(self):
        await self.bot.wait_until_ready()

    # --- COMANDO SECRETO PARA TESTES (BLINDADO) ---
    @commands.command(name="loteria_forcar", hidden=True)
    async def forcar_sorteio(self, ctx):
        """Força o sorteio da loteria agora mesmo (Apenas o Dono)"""
        
        # Trava de segurança: Apenas você pode executar
        if ctx.author.id != 385747293845979138:
            return await ctx.send("❌ Você não tem permissão para usar este comando secreto.", delete_after=5)
            
        await ctx.send("⚙️ Iniciando sorteio global forçado...")
        await self._executar_sorteio()


async def setup(bot: commands.Bot):
    await bot.add_cog(Loteria(bot))