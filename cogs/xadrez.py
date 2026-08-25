import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import asyncio
import random
import string

DB_PATH = "bifinhos.db"

# ==========================================
#              BANCO DE DADOS
# ==========================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_xadrez_db():
    """Cria a tabela de salas de xadrez no seu banco"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
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
        c.execute("ALTER TABLE partidas_xadrez ADD COLUMN fen TEXT DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'")
    except sqlite3.OperationalError:
        pass 
        
    conn.commit()
    conn.close()

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

def get_balance(user_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT balance FROM bifinhos WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

# ==========================================
#              MONITOR DA SALA
# ==========================================
async def monitor_bifes_chess(sala_id: str, channel: discord.TextChannel):
    """
    Fica olhando o banco de dados.
    Como a API agora faz o pagamento E o anúncio automaticamente na hora do Xeque-Mate,
    esse monitor serve APENAS para devolver os pontos se o jogo for abandonado (Timeout).
    """
    for _ in range(180): # Espera até 30 minutos (180 * 10s)
        await asyncio.sleep(10)
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT status, valor, jogador1_id, jogador2_id FROM partidas_xadrez WHERE sala_id = ?", (sala_id,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return # A sala não existe mais, encerra o monitor
            
        status, valor_partida, j1, j2 = row
        
        # Se a API já encerrou a partida e creditou o vencedor, nós apenas desligamos o monitor
        if status == "finalizada":
            return 
                
        elif status == "cancelada":
            return await channel.send(f"❌ O desafio na sala `{sala_id}` foi cancelado. Bifinhos devolvidos.")

    # Se passar 30 minutos e o status continuar "pendente", cancela por inatividade
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT status FROM partidas_xadrez WHERE sala_id = ?", (sala_id,))
    row = c.fetchone()
    
    if row and row[0] not in ["finalizada", "cancelada"]:
        c.execute("UPDATE partidas_xadrez SET status = 'cancelada_timeout' WHERE sala_id = ?", (sala_id,))
        conn.commit()
        conn.close()
        
        # Devolve os pontos cobrados na entrada para ambos os jogadores
        change_balance(j1, valor_partida)
        change_balance(j2, valor_partida)
        await channel.send(f"⏳ A sala `{sala_id}` expirou por inatividade de 30 minutos. Os Bifinhos do desafio foram devolvidos aos jogadores!")
    else:
        conn.close()


# ==========================================
#              VIEW DE ACEITE
# ==========================================
class BifeChessAccept(discord.ui.View):
    def __init__(self, challenger: discord.Member, challenged: discord.Member, bet_amount: int):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.challenged = challenged
        self.bet_amount = bet_amount
        self.accepted = False

    def generate_password(self):
        """Gera uma senha aleatória de 6 dígitos"""
        return ''.join(random.choices(string.digits, k=6))

    def generate_room_id(self):
        """Gera um ID de sala curto (ex: ABX92)"""
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

    @discord.ui.button(label="Aceitar Desafio", style=discord.ButtonStyle.success, emoji="🥩")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.challenged:
            return await interaction.response.send_message("❌ Não é para ti!", ephemeral=True)

        if get_balance(str(self.challenger.id)) < self.bet_amount or get_balance(str(self.challenged.id)) < self.bet_amount:
            return await interaction.response.send_message("❌ Alguém ficou sem saldo antes de aceitar!", ephemeral=True)

        self.accepted = True
        for child in self.children: child.disabled = True

        # 1. Tira os pontos (Valor inicial de ambos)
        change_balance(str(self.challenger.id), -self.bet_amount)
        change_balance(str(self.challenged.id), -self.bet_amount)

        # 2. Gera os dados da sala
        sala_id = self.generate_room_id()
        senha_p1 = self.generate_password()
        senha_p2 = self.generate_password()

        # 3. Salva no Banco de Dados
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO partidas_xadrez (sala_id, jogador1_id, senha1, jogador2_id, senha2, valor, status, vencedor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sala_id, str(self.challenger.id), senha_p1, str(self.challenged.id), senha_p2, self.bet_amount, "pendente", None)
        )
        conn.commit()
        conn.close()

        # 4. Envia as DMs
        link_base = f"https://www.bifes.com.br/xadrez?sala={sala_id}"
        
        embed_p1 = discord.Embed(title="♟️ Sala de Estratégia Criada!", description=f"O teu jogo começou.\n\n🔗 **Link:** {link_base}\n🔑 **A tua Chave:** `{senha_p1}`\n⚪ Jogas de **Brancas**.", color=discord.Color.blue())
        embed_p2 = discord.Embed(title="♟️ Sala de Estratégia Criada!", description=f"O teu jogo começou.\n\n🔗 **Link:** {link_base}\n🔑 **A tua Chave:** `{senha_p2}`\n⚫ Jogas de **Pretas**.", color=discord.Color.red())

        try:
            await self.challenger.send(embed=embed_p1)
            await self.challenged.send(embed=embed_p2)
            await interaction.response.edit_message(content=f"✅ A sala `{sala_id}` foi criada no site! Enviei os links e as chaves de 6 dígitos no PV de vocês.", embed=None, view=self)
        except discord.Forbidden:
            await interaction.response.edit_message(content="⚠️ Alguém está com a DM fechada! O desafio foi cancelado e os pontos devolvidos.", embed=None, view=self)
            # Reembolsa o valor já que a DM falhou
            change_balance(str(self.challenger.id), self.bet_amount)
            change_balance(str(self.challenged.id), self.bet_amount)
            conn = get_db_connection()
            conn.execute("UPDATE partidas_xadrez SET status = 'cancelada_dm_fechada' WHERE sala_id = ?", (sala_id,))
            conn.commit()
            conn.close()
            return

        # 5. Inicia o monitoramento de Timeout
        asyncio.create_task(monitor_bifes_chess(sala_id, interaction.channel))


# ==========================================
#              COG DO BOT
# ==========================================
class XadrezSite(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_xadrez_db() # Cria a tabela se não existir

    # --- LÓGICA CENTRAL DO COMANDO ---
    async def processar_comando_xadrez(self, user: discord.Member, oponente: discord.Member, valor: int, responder_func):
        """Lógica reutilizável para Slash e Prefix"""
        if valor <= 0 or oponente.bot or oponente == user:
            return await responder_func("❌ Valor de desafio inválido.", ephemeral=True)

        if get_balance(str(user.id)) < valor or get_balance(str(oponente.id)) < valor:
            return await responder_func("❌ Saldo insuficiente para iniciar este desafio.", ephemeral=True)

        embed = discord.Embed(
            title="♟️ DESAFIO DE ESTRATÉGIA - BIFES.COM.BR",
            description=f"{user.mention} desafiou {oponente.mention}!\n\n💰 **Bónus da Partida:** {valor} Bifinhos por jogador\n🌐 O jogo acontecerá numa sala privada no nosso site oficial.",
            color=0x2b2d31
        )
        
        view = BifeChessAccept(user, oponente, valor)
        
        # Envia a mensagem de acordo com a função que chamou (Context ou Interaction)
        try:
            await responder_func(content=oponente.mention, embed=embed, view=view)
        except TypeError: # Se for comando por prefixo (ctx.send não aceita ephemeral)
             await responder_func(content=oponente.mention, embed=embed, view=view)

    # --- COMANDO SLASH ---
    @app_commands.command(name="xadrez", description="Joga xadrez no site oficial bifes.com.br valendo Bifinhos!")
    async def slash_xadrez(self, interaction: discord.Interaction, oponente: discord.Member, valor: int):
        await self.processar_comando_xadrez(interaction.user, oponente, valor, interaction.response.send_message)

    # --- COMANDO PREFIXO ---
    @commands.command(name="xadrez")
    async def prefix_xadrez(self, ctx, oponente: discord.Member, valor: int):
        """Comando de texto. Exemplo: !xadrez @Joao 500"""
        await self.processar_comando_xadrez(ctx.author, oponente, valor, ctx.send)


async def setup(bot: commands.Bot):
    await bot.add_cog(XadrezSite(bot))