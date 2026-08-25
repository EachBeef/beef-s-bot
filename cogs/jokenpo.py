import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime
import asyncio

DB_PATH = "bifinhos.db"

# ==========================================
#              FUNÇÕES DE BANCO
# ==========================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

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
#        VIEWS DO JOKENPÔ
# ==========================================

class JokenpoReveal(discord.ui.View):
    """Fase 3: O botão de revelar o suspense"""
    def __init__(self, p1: discord.Member, p2: discord.Member, valor: int, p1_choice: str, p2_choice: str):
        super().__init__(timeout=60)
        self.p1 = p1
        self.p2 = p2
        self.valor = valor
        self.p1_choice = p1_choice
        self.p2_choice = p2_choice
        self.revelado = False

    @discord.ui.button(label="Revelar Resultado 🎲", style=discord.ButtonStyle.primary)
    async def btn_revelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Apenas os jogadores podem revelar
        if interaction.user not in [self.p1, self.p2]:
            return await interaction.response.send_message("❌ Apenas os jogadores do duelo podem revelar o resultado!", ephemeral=True)

        self.revelado = True
        for child in self.children: 
            child.disabled = True

        emojis = {"pedra": "🪨", "papel": "📄", "tesoura": "✂️"}
        resultado_msg = f"**{self.p1.display_name}** escolheu {emojis[self.p1_choice]}\n**{self.p2.display_name}** escolheu {emojis[self.p2_choice]}\n\n"

        # Lógica de quem ganha
        if self.p1_choice == self.p2_choice:
            resultado_msg += "🤝 **EMPATE!** Os Bifinhos foram devolvidos."
            change_balance(str(self.p1.id), self.valor)
            change_balance(str(self.p2.id), self.valor)
            cor = discord.Color.light_grey()
        else:
            vencedor = None
            if (self.p1_choice == "pedra" and self.p2_choice == "tesoura") or \
               (self.p1_choice == "papel" and self.p2_choice == "pedra") or \
               (self.p1_choice == "tesoura" and self.p2_choice == "papel"):
                vencedor = self.p1
                perdedor = self.p2
            else:
                vencedor = self.p2
                perdedor = self.p1

            premio_total = self.valor * 2
            resultado_msg += f"🏆 **{vencedor.mention} VENCEU E LEVOU {premio_total:,} 🥩!**"
            cor = discord.Color.green()
            
            # Paga o vencedor e registra pro ranking
            change_balance(str(vencedor.id), premio_total)
            registrar_ganho_mensal(str(vencedor.id), self.valor, "jokenpo")

        embed = discord.Embed(title="✂️ Resultado do Jokenpô", description=resultado_msg, color=cor)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        # Se ninguém clicar para revelar, revela automaticamente para o dinheiro não ficar preso
        if not self.revelado:
            # Reembolsa como segurança
            change_balance(str(self.p1.id), self.valor)
            change_balance(str(self.p2.id), self.valor)


class JokenpoGame(discord.ui.View):
    """Fase 2: Escolha secreta de Pedra, Papel ou Tesoura"""
    def __init__(self, p1: discord.Member, p2: discord.Member, valor: int):
        super().__init__(timeout=60)
        self.p1 = p1
        self.p2 = p2
        self.valor = valor
        self.p1_choice = None
        self.p2_choice = None

    async def handle_choice(self, interaction: discord.Interaction, choice: str):
        if interaction.user not in [self.p1, self.p2]:
            return await interaction.response.send_message("❌ Você não está nesta partida!", ephemeral=True)

        if interaction.user == self.p1:
            if self.p1_choice: 
                return await interaction.response.send_message("Você já fez sua escolha!", ephemeral=True)
            self.p1_choice = choice
        else:
            if self.p2_choice: 
                return await interaction.response.send_message("Você já fez sua escolha!", ephemeral=True)
            self.p2_choice = choice

        await interaction.response.send_message(f"🤫 Você escolheu de forma secreta. Aguarde o oponente.", ephemeral=True)

        # Se os dois escolheram, muda para a View de Revelar
        if self.p1_choice and self.p2_choice:
            embed = discord.Embed(
                title="✂️ Duelo de Jokenpô - TENSÃO MÁXIMA!", 
                description=f"Aposta: **{self.valor:,} Bifinhos**\n\nOs dois jogadores já fizeram suas escolhas!\nClique no botão abaixo para descobrir quem ganhou.", 
                color=0xf1c40f
            )
            embed.add_field(name=self.p1.display_name, value="✅ Escolheu", inline=True)
            embed.add_field(name=self.p2.display_name, value="✅ Escolheu", inline=True)

            view_reveal = JokenpoReveal(self.p1, self.p2, self.valor, self.p1_choice, self.p2_choice)
            await interaction.message.edit(embed=embed, view=view_reveal)
        else:
            # Atualiza o status visual
            embed = discord.Embed(title="✂️ Duelo de Jokenpô", description=f"Aposta: **{self.valor:,} Bifinhos**\n\nFaçam suas escolhas de forma secreta!", color=0x2b2d31)
            embed.add_field(name=self.p1.display_name, value="✅ Escolheu" if self.p1_choice else "⏳ Pensando...", inline=True)
            embed.add_field(name=self.p2.display_name, value="✅ Escolheu" if self.p2_choice else "⏳ Pensando...", inline=True)
            await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Pedra", emoji="🪨", style=discord.ButtonStyle.secondary)
    async def btn_pedra(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "pedra")

    @discord.ui.button(label="Papel", emoji="📄", style=discord.ButtonStyle.secondary)
    async def btn_papel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "papel")

    @discord.ui.button(label="Tesoura", emoji="✂️", style=discord.ButtonStyle.secondary)
    async def btn_tesoura(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_choice(interaction, "tesoura")

    async def on_timeout(self):
        if not (self.p1_choice and self.p2_choice):
            # Devolve o dinheiro se alguém fugir sem jogar
            change_balance(str(self.p1.id), self.valor)
            change_balance(str(self.p2.id), self.valor)
            for child in self.children: child.disabled = True


class JokenpoAccept(discord.ui.View):
    """Fase 1: Aceitar o Desafio"""
    def __init__(self, challenger: discord.Member, challenged: discord.Member, valor: int):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.challenged = challenged
        self.valor = valor
        self.accepted = False

    @discord.ui.button(label="Aceitar Duelo", style=discord.ButtonStyle.success, emoji="⚔️")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.challenged:
            return await interaction.response.send_message("❌ Este desafio não é para você!", ephemeral=True)

        if get_balance(str(self.challenger.id)) < self.valor or get_balance(str(self.challenged.id)) < self.valor:
            return await interaction.response.send_message("❌ Alguém ficou sem saldo antes de aceitar!", ephemeral=True)

        self.accepted = True
        
        # Desconta o dinheiro de ambos (Cria o Pote)
        change_balance(str(self.challenger.id), -self.valor)
        change_balance(str(self.challenged.id), -self.valor)

        game_view = JokenpoGame(self.challenger, self.challenged, self.valor)
        embed = discord.Embed(title="✂️ Duelo de Jokenpô", description=f"Aposta: **{self.valor:,} Bifinhos**\n\nFaçam suas escolhas de forma secreta!", color=0x2b2d31)
        embed.add_field(name=self.challenger.display_name, value="⏳ Pensando...", inline=True)
        embed.add_field(name=self.challenged.display_name, value="⏳ Pensando...", inline=True)

        await interaction.response.edit_message(embed=embed, view=game_view)


# ==========================================
#              COG DO BOT
# ==========================================
class JokenpoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _logic_desafio(self, user, oponente, valor: int):
        if valor <= 0:
            return False, "❌ Aposta inválida. O valor deve ser maior que zero."
        if oponente.bot or oponente == user:
            return False, "❌ Você não pode desafiar bots ou a si mesmo."
        if get_balance(str(user.id)) < valor:
            return False, "❌ Você não tem saldo suficiente para essa aposta."
        return True, None

    # COMANDO SLASH
    @app_commands.command(name="jokenpo", description="✂️ Desafie alguém para Pedra, Papel ou Tesoura apostando Bifinhos!")
    @app_commands.describe(oponente="Quem você quer desafiar?", valor="Quantos bifinhos quer apostar?")
    async def slash_jokenpo(self, interaction: discord.Interaction, oponente: discord.Member, valor: int):
        sucesso, erro = self._logic_desafio(interaction.user, oponente, valor)
        if not sucesso:
            return await interaction.response.send_message(erro, ephemeral=True)

        embed = discord.Embed(
            title="✂️ DESAFIO DE JOKENPÔ",
            description=f"{interaction.user.mention} desafiou {oponente.mention} para uma partida de Pedra, Papel e Tesoura!\n\n💰 **Aposta:** {valor:,} Bifinhos.",
            color=0x3498db
        )
        view = JokenpoAccept(interaction.user, oponente, valor)
        await interaction.response.send_message(content=oponente.mention, embed=embed, view=view)

    # COMANDO PREFIXO
    @commands.command(name="jokenpo")
    async def prefix_jokenpo(self, ctx, oponente: discord.Member, valor: int):
        """Uso: !jokenpo @usuario 500"""
        sucesso, erro = self._logic_desafio(ctx.author, oponente, valor)
        if not sucesso:
            return await ctx.send(erro)

        embed = discord.Embed(
            title="✂️ DESAFIO DE JOKENPÔ",
            description=f"{ctx.author.mention} desafiou {oponente.mention} para uma partida de Pedra, Papel e Tesoura!\n\n💰 **Aposta:** {valor:,} Bifinhos.",
            color=0x3498db
        )
        view = JokenpoAccept(ctx.author, oponente, valor)
        await ctx.send(content=oponente.mention, embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(JokenpoCog(bot))