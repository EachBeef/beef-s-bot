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
    """Adiciona ou remove saldo. Cria o usuário se não existir."""
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
#              LÓGICA DO 21 (BLACKJACK)
# ==========================================
def create_deck():
    suits = ['♠️', '♥️', '♦️', '♣️']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    deck = [{'rank': r, 'suit': s} for s in suits for r in ranks]
    random.shuffle(deck)
    return deck

def calculate_score(hand):
    score = 0
    aces = 0
    for card in hand:
        if card['rank'] in ['J', 'Q', 'K']:
            score += 10
        elif card['rank'] == 'A':
            score += 11
            aces += 1
        else:
            score += int(card['rank'])
    
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

def format_hand(hand, hide_second=False):
    """Formata a mão de cartas para texto (ex: `10♠️` `A♥️`)"""
    if not hand: return "Nenhuma carta"
    
    cards_str = []
    for i, card in enumerate(hand):
        if i == 1 and hide_second:
            cards_str.append("`❓`")
        else:
            cards_str.append(f"`{card['rank']}{card['suit']}`")
    return " ".join(cards_str)

# ==========================================
#              INTERFACE DO JOGO (VIEWS)
# ==========================================
class BlackjackView(discord.ui.View):
    def __init__(self, challenger: discord.Member, challenged: discord.Member, bet: int):
        super().__init__(timeout=120) # 2 minutos para jogar
        self.challenger = challenger
        self.challenged = challenged
        self.bet = bet
        
        self.deck = create_deck()
        self.hand_p1 = [self.deck.pop(), self.deck.pop()]
        self.hand_p2 = [self.deck.pop(), self.deck.pop()]
        
        self.current_turn = challenger
        self.game_over = False

    def generate_embed(self):
        embed = discord.Embed(title="🃏 Blackjack (21) - Duelo!", color=0x2b2d31)
        embed.description = f"💰 **Prêmio Base:** {self.bet} Bifinhos\n▶️ **Vez de:** {self.current_turn.mention}"
        
        score_p1 = calculate_score(self.hand_p1)
        hide_p2 = (self.current_turn == self.challenger and not self.game_over)
        
        if hide_p2:
            score_p2_display = "?"
        else:
            score_p2_display = calculate_score(self.hand_p2)

        embed.add_field(
            name=f"🎮 {self.challenger.display_name}", 
            value=f"**Cartas:** {format_hand(self.hand_p1)}\n**Pontos:** {score_p1}", 
            inline=False
        )
        
        embed.add_field(
            name=f"🎯 {self.challenged.display_name}", 
            value=f"**Cartas:** {format_hand(self.hand_p2, hide_second=hide_p2)}\n**Pontos:** {score_p2_display}", 
            inline=False
        )
        return embed

    async def end_game(self, interaction: discord.Interaction, reason: str, winner: discord.Member = None, tie: bool = False):
        self.game_over = True
        for child in self.children:
            child.disabled = True
            
        embed = self.generate_embed()
        embed.color = discord.Color.gold() if not tie else discord.Color.light_gray()
        
        if tie:
            embed.title = "🤝 Empate!"
            embed.description = f"{reason}\nOs **{self.bet} Bifinhos** foram devolvidos para cada um."
            change_balance(str(self.challenger.id), self.bet)
            change_balance(str(self.challenged.id), self.bet)
        else:
            embed.title = f"🎉 {winner.display_name} Venceu!"
            embed.description = f"{reason}\n🏆 Ganhou **{self.bet * 2} Bifinhos!**"
            change_balance(str(winner.id), self.bet * 2)
            registrar_ganho_mensal(str(winner.id), self.bet, "21") # Registra no TOP MENSAL!

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Comprar (Hit)", style=discord.ButtonStyle.primary, emoji="🃏")
    async def btn_hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.current_turn:
            return await interaction.response.send_message("❌ Não é sua vez!", ephemeral=True)
            
        new_card = self.deck.pop()
        
        if self.current_turn == self.challenger:
            self.hand_p1.append(new_card)
            score = calculate_score(self.hand_p1)
            if score > 21:
                await self.end_game(interaction, "💥 Estourou 21!", winner=self.challenged)
                return
        else:
            self.hand_p2.append(new_card)
            score = calculate_score(self.hand_p2)
            if score > 21:
                await self.end_game(interaction, "💥 Estourou 21!", winner=self.challenger)
                return

        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Parar (Stand)", style=discord.ButtonStyle.danger, emoji="🛑")
    async def btn_stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.current_turn:
            return await interaction.response.send_message("❌ Não é sua vez!", ephemeral=True)

        if self.current_turn == self.challenger:
            self.current_turn = self.challenged
            await interaction.response.edit_message(embed=self.generate_embed(), view=self)
        else:
            score_1 = calculate_score(self.hand_p1)
            score_2 = calculate_score(self.hand_p2)
            
            if score_1 > score_2:
                await self.end_game(interaction, f"📈 Maior pontuação ({score_1} x {score_2})", winner=self.challenger)
            elif score_2 > score_1:
                await self.end_game(interaction, f"📈 Maior pontuação ({score_2} x {score_1})", winner=self.challenged)
            else:
                await self.end_game(interaction, f"⚖️ Mesma pontuação ({score_1})", tie=True)

    async def on_timeout(self):
        if not self.game_over:
            loser = self.current_turn
            winner = self.challenged if loser == self.challenger else self.challenger
            
            for child in self.children:
                child.disabled = True
            
            change_balance(str(winner.id), self.bet * 2)
            registrar_ganho_mensal(str(winner.id), self.bet, "21")
            
            channel = self.challenger.guild.get_channel(self.message.channel.id)
            if channel:
                await channel.send(f"⏳ O tempo esgotou! {loser.mention} demorou muito e perdeu por W.O. {winner.mention} levou os **{self.bet * 2} Bifinhos**!")


class ChallengeView(discord.ui.View):
    def __init__(self, challenger: discord.Member, challenged: discord.Member, bet: int):
        super().__init__(timeout=60) # 1 minuto para aceitar
        self.challenger = challenger
        self.challenged = challenged
        self.bet = bet
        self.accepted = False

    @discord.ui.button(label="Aceitar Desafio", style=discord.ButtonStyle.success, emoji="✅")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.challenged:
            return await interaction.response.send_message("❌ Esse desafio não é para você!", ephemeral=True)

        bal_challenger = get_balance(str(self.challenger.id))
        bal_challenged = get_balance(str(self.challenged.id))

        if bal_challenger < self.bet:
            return await interaction.response.send_message(f"❌ {self.challenger.display_name} gastou o dinheiro e não tem mais os {self.bet} bifinhos!", ephemeral=True)
        if bal_challenged < self.bet:
            return await interaction.response.send_message(f"❌ Você não tem {self.bet} bifinhos suficientes para entrar na partida!", ephemeral=True)

        self.accepted = True
        for child in self.children:
            child.disabled = True

        change_balance(str(self.challenger.id), -self.bet)
        change_balance(str(self.challenged.id), -self.bet)

        await interaction.response.edit_message(content="⚔️ **Desafio Aceito! O jogo vai começar...**", embed=None, view=self)
        
        game_view = BlackjackView(self.challenger, self.challenged, self.bet)
        game_msg = await interaction.followup.send(embed=game_view.generate_embed(), view=game_view)
        game_view.message = game_msg 
        self.stop()

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.secondary, emoji="❌")
    async def btn_decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.challenged:
            return await interaction.response.send_message("❌ Esse desafio não é para você!", ephemeral=True)
            
        self.accepted = True
        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(content=f"💨 {self.challenged.mention} correu do desafio de {self.challenger.mention}!", embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        if not self.accepted:
            for child in self.children:
                child.disabled = True
            pass


# ==========================================
#              COG DO BOT
# ==========================================
class Jogo21(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _handle_apostar21_logic(self, challenger: discord.Member, challenged: discord.Member, bet: int):
        if bet <= 0:
            return False, "❌ O valor do desafio deve ser maior que zero!"
        
        if challenged.bot:
            return False, "❌ Você não pode jogar contra bots!"
            
        if challenged == challenger:
            return False, "❌ Você não pode desafiar a si mesmo!"

        bal_challenger = get_balance(str(challenger.id))
        bal_challenged = get_balance(str(challenged.id))

        if bal_challenger < bet:
            return False, f"❌ Você não tem bifinhos suficientes! Seu saldo: **{bal_challenger}**"
            
        if bal_challenged < bet:
            return False, f"❌ {challenged.display_name} não tem bifinhos suficientes para cobrir essa entrada! Saldo dele(a): **{bal_challenged}**"

        embed = discord.Embed(
            title="⚔️ NOVO DESAFIO: BLACKJACK (21)",
            description=f"{challenger.mention} desafiou {challenged.mention} para uma partida de 21!\n\n💰 **Prêmio em jogo:** {bet*2} Bifinhos",
            color=discord.Color.red()
        )
        embed.set_footer(text="O oponente tem 60 segundos para aceitar.")

        view = ChallengeView(challenger, challenged, bet)
        return True, (embed, view)

    # --- COMANDO DE PREFIXO (!) ---
    @commands.command(name="desafiar21")
    async def prefix_desafiar21(self, ctx, oponente: discord.Member, valor: int):
        success, result = await self._handle_apostar21_logic(ctx.author, oponente, valor)
        if not success:
            return await ctx.send(result)
        embed, view = result
        await ctx.send(content=oponente.mention, embed=embed, view=view)

    @prefix_desafiar21.error
    async def desafiar21_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument) or isinstance(error, commands.BadArgument):
            await ctx.send("❌ Como usar: `!desafiar21 @usuario <quantidade>`\nExemplo: `!desafiar21 @Impie 20`")

    # --- COMANDO DE SLASH (/) ---
    @app_commands.command(name="desafiar21", description="Desafie um amigo para uma partida de 21 valendo Bifinhos!")
    @app_commands.describe(oponente="Quem você quer desafiar?", valor="Quantos bifinhos vão colocar na mesa?")
    async def slash_desafiar21(self, interaction: discord.Interaction, oponente: discord.Member, valor: int):
        success, result = await self._handle_apostar21_logic(interaction.user, oponente, valor)
        
        if not success:
            return await interaction.response.send_message(result, ephemeral=True)
            
        embed, view = result
        await interaction.response.send_message(content=oponente.mention, embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Jogo21(bot))