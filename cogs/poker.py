import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import asyncio
from datetime import datetime

# Tenta importar a biblioteca de Poker. Se falhar, avisa no console.
try:
    from treys import Card, Evaluator, Deck
except ImportError:
    print("❌ ERRO CRÍTICO: Você precisa instalar a biblioteca 'treys'. Rode no terminal: pip install treys")
    Card, Evaluator, Deck = None, None, None

DB_PATH = "bifinhos.db"

# ==========================================
#              BANCO DE DADOS
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
#              HELPER DE CARTAS
# ==========================================
def format_card(card_int):
    """Converte o formato do 'treys' para Emojis bonitos no Discord"""
    s = Card.int_to_str(card_int)
    rank = s[0].upper().replace('T', '10')
    suit = s[1].lower()
    
    suit_map = {'s': '♠️', 'h': '♥️', 'd': '♦️', 'c': '♣️'}
    return f"` {rank}{suit_map.get(suit, suit)} `"

# ==========================================
#              ESTADO DO JOGO
# ==========================================
class PokerPlayer:
    def __init__(self, member: discord.Member):
        self.member = member
        self.hand = []
        self.bet_this_round = 0
        self.total_bet = 0
        self.folded = False
        self.all_in = False

class PokerMatch:
    def __init__(self, host: discord.Member, ante: int):
        self.host = host
        self.ante = ante
        self.players = []
        
        self.deck = Deck()
        self.board = []
        self.pot = 0
        
        self.current_bet = 0  # A maior contribuição da rodada atual
        self.turn_index = 0
        self.last_raiser_index = 0
        
        # 0=Lobby, 1=Pre-Flop, 2=Flop, 3=Turn, 4=River, 5=Showdown
        self.phase = 0 
        self.active = True
        self.message = None
        self.view = None

    @property
    def current_player(self):
        return self.players[self.turn_index]

    def get_active_players(self):
        return [p for p in self.players if not p.folded]

    def advance_turn(self):
        """Passa para o próximo jogador que não deu fold."""
        active = self.get_active_players()
        if len(active) == 1:
            return self.end_game(winner=active[0], reason="Todos os outros deram Fold!")

        while True:
            self.turn_index = (self.turn_index + 1) % len(self.players)
            
            if self.turn_index == self.last_raiser_index:
                self.advance_phase()
                break
                
            if not self.players[self.turn_index].folded and not self.players[self.turn_index].all_in:
                break

    def advance_phase(self):
        self.phase += 1
        self.current_bet = 0
        for p in self.players:
            p.bet_this_round = 0
            
        active = self.get_active_players()
        for i, p in enumerate(self.players):
            if not p.folded:
                self.turn_index = i
                self.last_raiser_index = i
                break

        if self.phase == 2: # Flop
            self.board = self.deck.draw(3)
        elif self.phase == 3: # Turn
            self.board.append(self.deck.draw(1))
        elif self.phase == 4: # River
            self.board.append(self.deck.draw(1))
        elif self.phase >= 5: # Showdown
            self.evaluate_winner()

    def evaluate_winner(self):
        evaluator = Evaluator()
        active = self.get_active_players()
        
        best_score = 99999
        winners = []
        
        for p in active:
            score = evaluator.evaluate(self.board, p.hand)
            if score < best_score:
                best_score = score
                winners = [p]
            elif score == best_score:
                winners.append(p)
                
        prize = self.pot // len(winners)
        win_names = " e ".join([w.member.display_name for w in winners])
        
        hand_class = evaluator.get_rank_class(best_score)
        hand_name = evaluator.class_to_string(hand_class)

        for w in winners:
            change_balance(str(w.member.id), prize)
            registrar_ganho_mensal(str(w.member.id), prize - w.total_bet, "poker") # Registra APENAS O LUCRO no Rank

        self.end_game(None, f"🏆 **{win_names}** venceu com **{hand_name}**!\n💰 Prêmio: **{prize} Bifinhos**")

    def end_game(self, winner=None, reason=""):
        self.active = False
        if winner: 
            change_balance(str(winner.member.id), self.pot)
            registrar_ganho_mensal(str(winner.member.id), self.pot - winner.total_bet, "poker") # Lucro
            self.win_reason = f"🏆 {winner.member.display_name} venceu! {reason}\n💰 Levou **{self.pot} Bifinhos**."
        else:
            self.win_reason = reason

# ==========================================
#              MODAL DE AUMENTO (RAISE)
# ==========================================
class RaiseModal(discord.ui.Modal, title='Aumentar Fichas (Raise)'):
    amount = discord.ui.TextInput(
        label='Quantos Bifinhos quer adicionar?',
        placeholder='Ex: 200',
        style=discord.TextStyle.short,
        required=True
    )

    def __init__(self, view_instance):
        super().__init__()
        self.v = view_instance

    async def on_submit(self, interaction: discord.Interaction):
        try:
            raise_amount = int(self.amount.value)
        except:
            return await interaction.response.send_message("❌ Digite apenas números inteiros!", ephemeral=True)

        match = self.v.match
        player = match.current_player
        
        to_call = match.current_bet - player.bet_this_round
        total_needed = to_call + raise_amount
        
        if raise_amount <= 0:
            return await interaction.response.send_message("❌ O aumento deve ser maior que zero.", ephemeral=True)

        if get_balance(str(player.member.id)) < total_needed:
            return await interaction.response.send_message("❌ Você não tem saldo suficiente.", ephemeral=True)

        change_balance(str(player.member.id), -total_needed)
        player.bet_this_round += total_needed
        player.total_bet += total_needed
        match.pot += total_needed
        match.current_bet = player.bet_this_round
        match.last_raiser_index = match.turn_index 
        
        match.advance_turn()
        await interaction.response.edit_message(embed=self.v.generate_embed(), view=self.v)

# ==========================================
#              VIEWS DO JOGO
# ==========================================
class PokerActionView(discord.ui.View):
    def __init__(self, match: PokerMatch):
        super().__init__(timeout=120)
        self.match = match

    def generate_embed(self):
        match = self.match
        
        if not match.active:
            embed = discord.Embed(title="🃏 Texas Hold'em - Fim de Jogo", description=match.win_reason, color=discord.Color.gold())
            for p in match.get_active_players():
                cards = " ".join([format_card(c) for c in p.hand])
                embed.add_field(name=p.member.display_name, value=cards, inline=True)
            self.stop()
            return embed

        embed = discord.Embed(title="♠️ Texas Hold'em - Mesa VIP ♠️", color=0x2b2d31)
        embed.description = f"💰 **Pote Total:** {match.pot} Bifinhos\n💵 **Maior Lance Atual:** {match.current_bet}\n\n"
        
        board_str = []
        for i in range(5):
            if i < len(match.board):
                board_str.append(format_card(match.board[i]))
            else:
                board_str.append("` ❓ `")
        
        embed.add_field(name="Cartas Comunitárias", value=" ".join(board_str), inline=False)
        
        players_str = ""
        for i, p in enumerate(match.players):
            status = ""
            if p.folded:
                status = "❌ *(Fold)*"
            elif i == match.turn_index:
                status = f"▶️ **(Pensando...)**"
            else:
                status = f"✅ Na mesa"
                
            players_str += f"{status} | **{p.member.display_name}** | Mesa: {p.bet_this_round}\n"
            
        embed.add_field(name="Jogadores", value=players_str, inline=False)
        embed.set_footer(text=f"Vez de: {match.current_player.member.display_name}")
        return embed

    @discord.ui.button(label="Ver Cartas", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def btn_cards(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = next((p for p in self.match.players if p.member == interaction.user), None)
        if not player:
            return await interaction.response.send_message("❌ Você não está nesta mesa.", ephemeral=True)
            
        cards = " ".join([format_card(c) for c in player.hand])
        await interaction.response.send_message(f"🤫 **Suas cartas secretas:** {cards}", ephemeral=True)

    @discord.ui.button(label="Fold", style=discord.ButtonStyle.danger, emoji="🏃")
    async def btn_fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.match.current_player.member:
            return await interaction.response.send_message("❌ Não é sua vez!", ephemeral=True)
            
        self.match.current_player.folded = True
        self.match.advance_turn()
        
        embed = self.generate_embed()
        if not self.match.active: self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Call / Check", style=discord.ButtonStyle.success, emoji="✔️")
    async def btn_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        match = self.match
        if interaction.user != match.current_player.member:
            return await interaction.response.send_message("❌ Não é sua vez!", ephemeral=True)
            
        player = match.current_player
        to_call = match.current_bet - player.bet_this_round
        
        if get_balance(str(player.member.id)) < to_call:
            return await interaction.response.send_message("❌ Saldo insuficiente para igualar a mesa.", ephemeral=True)
            
        change_balance(str(player.member.id), -to_call)
        player.bet_this_round += to_call
        player.total_bet += to_call
        match.pot += to_call
        
        match.advance_turn()
        embed = self.generate_embed()
        if not match.active: self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Raise", style=discord.ButtonStyle.primary, emoji="⏫")
    async def btn_raise(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.match.current_player.member:
            return await interaction.response.send_message("❌ Não é sua vez!", ephemeral=True)
            
        await interaction.response.send_modal(RaiseModal(self))


class LobbyView(discord.ui.View):
    def __init__(self, match: PokerMatch):
        super().__init__(timeout=120)
        self.match = match
        self.match.players.append(PokerPlayer(match.host))

    def generate_embed(self):
        embed = discord.Embed(title="♠️ Mesa de Poker Aberta! ♠️", color=discord.Color.red())
        embed.description = f"**Host:** {self.match.host.mention}\n**Entrada (Ante):** {self.match.ante} Bifinhos\n\n**Jogadores na mesa:**\n"
        for p in self.match.players:
            embed.description += f"👤 {p.member.display_name}\n"
        return embed

    @discord.ui.button(label="Sentar na Mesa", style=discord.ButtonStyle.success, emoji="🪑")
    async def btn_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.match.players) >= 8:
            return await interaction.response.send_message("❌ A mesa está cheia (Máx 8)!", ephemeral=True)
            
        if any(p.member == interaction.user for p in self.match.players):
            return await interaction.response.send_message("❌ Você já está na mesa!", ephemeral=True)
            
        if get_balance(str(interaction.user.id)) < self.match.ante:
            return await interaction.response.send_message(f"❌ Você precisa de {self.match.ante} Bifinhos para entrar!", ephemeral=True)

        self.match.players.append(PokerPlayer(interaction.user))
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Iniciar Jogo", style=discord.ButtonStyle.primary, emoji="🃏")
    async def btn_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.match.host:
            return await interaction.response.send_message("❌ Só o dono da mesa pode iniciar o jogo.", ephemeral=True)
            
        if len(self.match.players) < 2:
            return await interaction.response.send_message("❌ Precisa de pelo menos 2 jogadores para iniciar.", ephemeral=True)

        self.stop()
        
        for p in self.match.players:
            change_balance(str(p.member.id), -self.match.ante)
            self.match.pot += self.match.ante
            p.total_bet += self.match.ante # Para calcularmos o lucro limpo no final
            p.hand = self.match.deck.draw(2)
            
        self.match.phase = 1 # Inicia o Pre-Flop
        
        game_view = PokerActionView(self.match)
        await interaction.response.edit_message(content="🃏 **O jogo começou!**", embed=game_view.generate_embed(), view=game_view)


# ==========================================
#              COG DO BOT
# ==========================================
class Poker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _handle_poker_create(self, host: discord.Member, ante: int):
        if not Evaluator:
            return False, "❌ O sistema de Poker está offline. O dono do bot precisa instalar a biblioteca `treys`."
            
        if ante < 10:
            return False, "❌ A entrada mínima (Ante) é de 10 Bifinhos."
            
        if get_balance(str(host.id)) < ante:
            return False, f"❌ Você não tem saldo para criar a mesa. Precisa de {ante} Bifinhos."

        match = PokerMatch(host, ante)
        view = LobbyView(match)
        return True, (view.generate_embed(), view)

    # --- PREFIXO (!) ---
    @commands.command(name="poker")
    async def prefix_poker(self, ctx, entrada: int = 50):
        success, result = await self._handle_poker_create(ctx.author, entrada)
        if not success:
            return await ctx.send(result)
        embed, view = result
        await ctx.send(embed=embed, view=view)

    # --- SLASH (/) ---
    @app_commands.command(name="poker", description="Abre uma mesa multiplayer de Texas Hold'em!")
    @app_commands.describe(entrada="Qual será o valor de entrada (pinga) da mesa?")
    async def slash_poker(self, interaction: discord.Interaction, entrada: int = 50):
        success, result = await self._handle_poker_create(interaction.user, entrada)
        if not success:
            return await interaction.response.send_message(result, ephemeral=True)
        embed, view = result
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Poker(bot))