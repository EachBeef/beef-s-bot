import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import random
import asyncio
from datetime import datetime
import math

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
#              LÓGICA DA ROLETA
# ==========================================
VERMELHOS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
PRETOS = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

def get_color_emoji(num):
    if num == 0: return '🟢'
    if num in VERMELHOS: return '🔴'
    return '⚫'

def get_color_name(num):
    if num == 0: return 'verde'
    if num in VERMELHOS: return 'vermelho'
    return 'preto'


# ==========================================
#              INTERFACES (UI)
# ==========================================
class NumeroModal(discord.ui.Modal, title='Escolher Número da Roleta'):
    numero = discord.ui.TextInput(
        label='Digite um número (0 a 36)',
        style=discord.TextStyle.short,
        placeholder='Exemplo: 17',
        required=True,
        min_length=1,
        max_length=2
    )

    def __init__(self, view, valor):
        super().__init__()
        self.roleta_view = view
        self.valor = valor

    async def on_submit(self, interaction: discord.Interaction):
        val = self.numero.value.strip()
        if not val.isdigit() or not (0 <= int(val) <= 36):
            await interaction.response.send_message("❌ Número inválido! Tem de ser entre **0 e 36**.", ephemeral=True)
            return
            
        await self.roleta_view.start_game(interaction, palpite=str(int(val)), is_numero=True)


class RoletaView(discord.ui.View):
    def __init__(self, player: discord.Member, valor: int, cog):
        super().__init__(timeout=60)
        self.player = player
        self.valor = valor
        self.cog = cog

    async def check_player(self, interaction: discord.Interaction):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("❌ Estás a tentar usar os botões de outra pessoa!", ephemeral=True)
            return False
        return True

    # --- LINHA 1 DE BOTÕES (Cores) ---
    @discord.ui.button(label="Vermelho", style=discord.ButtonStyle.danger, emoji="🔴", row=0)
    async def btn_red(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.check_player(interaction):
            await self.start_game(interaction, "vermelho", is_numero=False)

    @discord.ui.button(label="Preto", style=discord.ButtonStyle.secondary, emoji="⚫", row=0)
    async def btn_black(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.check_player(interaction):
            await self.start_game(interaction, "preto", is_numero=False)

    @discord.ui.button(label="Verde (0)", style=discord.ButtonStyle.success, emoji="🟢", row=0)
    async def btn_green(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.check_player(interaction):
            await self.start_game(interaction, "verde", is_numero=False)

    # --- LINHA 2 DE BOTÕES (Variações e Número) ---
    @discord.ui.button(label="Par", style=discord.ButtonStyle.primary, emoji="🔢", row=1)
    async def btn_par(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.check_player(interaction):
            await self.start_game(interaction, "par", is_numero=False)

    @discord.ui.button(label="Ímpar", style=discord.ButtonStyle.primary, emoji="🔢", row=1)
    async def btn_impar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.check_player(interaction):
            await self.start_game(interaction, "impar", is_numero=False)

    @discord.ui.button(label="Número Exato", style=discord.ButtonStyle.secondary, emoji="🎯", row=1)
    async def btn_num(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self.check_player(interaction):
            # Abre o pop-up para digitar o número!
            await interaction.response.send_modal(NumeroModal(self, self.valor))

    async def start_game(self, interaction: discord.Interaction, palpite: str, is_numero: bool):
        # Desativa os botões para não clicarem duas vezes
        for child in self.children:
            child.disabled = True

        # Verifica se ainda tem dinheiro
        saldo = get_balance(str(self.player.id))
        if saldo < self.valor:
            msg_erro = f"❌ Já não tens {self.valor} bifinhos para jogar!"
            if not interaction.response.is_done():
                await interaction.response.edit_message(content=msg_erro, embed=None, view=None)
            else:
                await interaction.followup.send(msg_erro, ephemeral=True)
            self.stop()
            return

        # Desconta o valor
        change_balance(str(self.player.id), -self.valor)

        # Atualiza a interface visualmente para iniciar o giro
        embed = discord.Embed(title="🎡 Roleta de Bifinhos", color=0x2b2d31)
        embed.description = f"**Jogador:** {self.player.mention}\n**Entrada:** {self.valor} 🥩\n**Palpite:** `{palpite.upper()}`\n\n"
        embed.add_field(name="A roda está a girar...", value="`[ 🔄 ] ⬅️ [ 🔄 ] ⬅️ [ 🔄 ]`", inline=False)

        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

        self.stop() # Para a escuta dos botões
        
        # Inicia a animação de forma assíncrona
        asyncio.create_task(self.cog._animar_resultado(interaction, embed, palpite, is_numero, self.valor, self.player))


# ==========================================
#              COG DO BOT
# ==========================================
class RoletaJogo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _animar_resultado(self, interaction, embed, palpite, is_numero, valor, player):
        # O Número Vencedor!
        resultado_num = random.randint(0, 36)
        resultado_cor = get_color_name(resultado_num)
        emoji_resultado = get_color_emoji(resultado_num)

        # Animação passando números aleatórios
        for _ in range(3):
            await asyncio.sleep(1)
            n1 = random.randint(0, 36); n2 = random.randint(0, 36); n3 = random.randint(0, 36)
            anim_str = f"`[ {get_color_emoji(n1)} {n1} ] ⬅️ [ {get_color_emoji(n2)} {n2} ] ⬅️ [ {get_color_emoji(n3)} {n3} ]`"
            embed.set_field_at(0, name="A roda está a girar...", value=anim_str, inline=False)
            await interaction.edit_original_response(embed=embed)

        # Para no resultado final
        await asyncio.sleep(1.5)
        embed.set_field_at(0, name="A roda parou em:", value=f"🌟 **[ {emoji_resultado} {resultado_num} ]** 🌟", inline=False)

        # Checa se ganhou e aplica as Variações de Multiplicador
        ganhou = False
        multiplicador = 0.0

        if is_numero:
            if int(palpite) == resultado_num:
                ganhou = True
                multiplicador = 36.0
        else:
            if palpite == 'verde' and resultado_cor == 'verde':
                ganhou = True
                multiplicador = 36.0
                
            elif palpite in ['vermelho', 'preto'] and palpite == resultado_cor:
                ganhou = True
                multiplicador = 2.0  # Retorno Padrão
                
            elif palpite == 'par' and resultado_num != 0 and resultado_num % 2 == 0:
                ganhou = True
                multiplicador = 1.5  # Retorno Variado
                
            elif palpite == 'impar' and resultado_num != 0 and resultado_num % 2 != 0:
                ganhou = True
                multiplicador = 1.5  # Retorno Variado

        # Aplica os prémios
        if ganhou:
            premio = math.floor(valor * multiplicador)
            lucro_limpo = premio - valor
            
            embed.color = discord.Color.green()
            embed.add_field(name="🎉 VITÓRIA!", value=f"O teu palpite estava certo!\nGanhaste **{premio} Bifinhos** ({multiplicador}x)", inline=False)
            
            change_balance(str(player.id), premio)
            if lucro_limpo > 0:
                registrar_ganho_mensal(str(player.id), lucro_limpo, "roleta")
        else:
            embed.color = discord.Color.red()
            embed.add_field(name="💸 Perdeste...", value="A roleta não foi gentil contigo desta vez.", inline=False)

        await interaction.edit_original_response(embed=embed)

    # --- COMANDO DE PREFIXO (!) ---
    @commands.command(name="roleta")
    async def prefix_roleta(self, ctx, valor: int):
        """Joga na roleta! Ex: !roleta 50"""
        if valor < 5:
            return await ctx.send("❌ A entrada mínima na roleta é de **5 Bifinhos**.")
            
        saldo = get_balance(str(ctx.author.id))
        if saldo < valor:
            return await ctx.send(f"❌ Não tens bifinhos suficientes! Saldo: **{saldo}**")

        embed = discord.Embed(
            title="🎡 Roleta de Cassino",
            description=f"Escolhe onde queres colocar os teus **{valor} Bifinhos**:\n\n🔴 **Vermelho** (2x)\n⚫ **Preto** (2x)\n🟢 **Verde** (36x)\n🔢 **Par/Ímpar** (1.5x)\n🎯 **Número Exato** (36x)",
            color=0x2b2d31
        )
        
        view = RoletaView(ctx.author, valor, self)
        await ctx.send(embed=embed, view=view)

    @prefix_roleta.error
    async def roleta_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument) or isinstance(error, commands.BadArgument):
            await ctx.send("❌ Como usar: `!roleta <quantidade>`\nExemplo: `!roleta 50`")

    # --- COMANDO DE SLASH (/) ---
    @app_commands.command(name="roleta", description="🎡 Roda a roleta e tenta multiplicar os teus Bifinhos!")
    @app_commands.describe(valor="Quantos bifinhos vais colocar na mesa?")
    async def slash_roleta(self, interaction: discord.Interaction, valor: int):
        if valor < 5:
            return await interaction.response.send_message("❌ A entrada mínima na roleta é de **5 Bifinhos**.", ephemeral=True)
            
        saldo = get_balance(str(interaction.user.id))
        if saldo < valor:
            return await interaction.response.send_message(f"❌ Não tens bifinhos suficientes! Saldo: **{saldo}**", ephemeral=True)

        embed = discord.Embed(
            title="🎡 Roleta de Cassino",
            description=f"Escolhe onde queres colocar os teus **{valor} Bifinhos**:\n\n🔴 **Vermelho** (2x)\n⚫ **Preto** (2x)\n🟢 **Verde** (36x)\n🔢 **Par/Ímpar** (1.5x)\n🎯 **Número Exato** (36x)",
            color=0x2b2d31
        )
        
        view = RoletaView(interaction.user, valor, self)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(RoletaJogo(bot))