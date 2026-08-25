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
#              LÓGICA DA MÁQUINA
# ==========================================
# Com 10 símbolos diluídos, a chance de perder sobe para 70%!
SIMBOLOS = ['🍒', '🍇', '🍉', '🍊', '🍋', '🍌', '🍍', '🍓', '💎', '7️⃣']
PESOS = [12, 12, 12, 11, 11, 11, 11, 11, 8, 1] # O total continua a ser exatamente 100

# Multiplicadores caso tire 3 símbolos iguais
MULTIPLICADORES = {
    '7️⃣': 50.0,  # SUPER JACKPOT! Subiu para 50x por ser extremamente raro
    '💎': 10.0,
    '🍓': 5.0,
    '🍍': 4.0,
    '🍌': 4.0,
    '🍋': 3.0,
    '🍊': 3.0,
    '🍉': 3.0,
    '🍇': 3.0,
    '🍒': 3.0
}

# ==========================================
#              COG DO BOT
# ==========================================
class MaquinaSlots(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _handle_slots_logic(self, player: discord.Member, valor: int):
        if valor < 5:
            return False, "❌ A entrada mínima para a máquina é de **5 Bifinhos**."

        saldo_atual = get_balance(str(player.id))
        if saldo_atual < valor:
            return False, f"❌ Não tens bifinhos suficientes! O teu saldo: **{saldo_atual}**"

        # Tira o valor da entrada da carteira
        change_balance(str(player.id), -valor)

        # Rola os 3 símbolos baseado nas probabilidades (pesos)
        resultado = random.choices(SIMBOLOS, weights=PESOS, k=3)

        # Monta a animação de girar
        embed = discord.Embed(title="🎰 Máquina de Bifinhos", color=0x2b2d31)
        embed.description = f"**Jogador:** {player.mention}\n**Entrada:** {valor} 🥩\n\n"
        
        # Etapa 1: Girando tudo
        embed.add_field(name="Rolos", value="`[ 🔄 | 🔄 | 🔄 ]`", inline=False)
        
        return True, (embed, resultado)

    async def _animar_resultado(self, message, embed, resultado, valor, player):
        # Etapa 2: Para o primeiro rolo
        await asyncio.sleep(1)
        embed.set_field_at(0, name="Rolos", value=f"`[ {resultado[0]} | 🔄 | 🔄 ]`", inline=False)
        await message.edit(embed=embed)

        # Etapa 3: Para o segundo rolo
        await asyncio.sleep(1)
        embed.set_field_at(0, name="Rolos", value=f"`[ {resultado[0]} | {resultado[1]} | 🔄 ]`", inline=False)
        await message.edit(embed=embed)

        # Etapa 4: Resultado Final
        await asyncio.sleep(1.5)
        embed.set_field_at(0, name="Rolos", value=f"`[ {resultado[0]} | {resultado[1]} | {resultado[2]} ]`", inline=False)

        # Calcula os ganhos
        simbolos_unicos = len(set(resultado))
        premio = 0
        lucro_limpo = 0

        if simbolos_unicos == 1:
            # Acertou 3 iguais!
            multiplicador = MULTIPLICADORES[resultado[0]]
            premio = math.floor(valor * multiplicador)
            
            if resultado[0] == '7️⃣':
                embed.color = discord.Color.gold()
                embed.add_field(name="🎉 JACKPOT LENDÁRIO! 7️⃣7️⃣7️⃣", value=f"QUEBRASTE A BANCA DO SERVIDOR!\nGanhaste **{premio} Bifinhos** ({multiplicador}x)", inline=False)
            else:
                embed.color = discord.Color.green()
                embed.add_field(name="🎉 VITÓRIA!", value=f"Trinca perfeita!\nGanhaste **{premio} Bifinhos** ({multiplicador}x)", inline=False)

        elif simbolos_unicos == 2:
            # Acertou 2 iguais (Prémio de consolação)
            multiplicador = 1.5
            premio = math.floor(valor * multiplicador)
            embed.color = discord.Color.blurple()
            embed.add_field(name="👍 Quase!", value=f"Tiraste uma dupla e ganhaste **{premio} Bifinhos** ({multiplicador}x)", inline=False)

        else:
            # Perdeu (agora vai acontecer a maioria das vezes)
            embed.color = discord.Color.red()
            embed.add_field(name="😢 Deu azar...", value="Os rolos não combinaram. Mais sorte na próxima vez!", inline=False)

        # Paga o jogador se ele ganhou algo
        if premio > 0:
            change_balance(str(player.id), premio)
            lucro_limpo = premio - valor
            
            # Só regista no top mensal se houve LUCRO real
            if lucro_limpo > 0:
                registrar_ganho_mensal(str(player.id), lucro_limpo, "slots")

        await message.edit(embed=embed)

    # --- COMANDO DE PREFIXO (!) ---
    @commands.command(name="slots")
    async def prefix_slots(self, ctx, valor: int):
        """Gira a máquina de slots! Ex: !slots 50"""
        sucesso, resposta = await self._handle_slots_logic(ctx.author, valor)
        
        if not sucesso:
            return await ctx.send(resposta)
            
        embed, resultado = resposta
        msg = await ctx.send(embed=embed)
        
        # Inicia a animação a rodar em fundo
        asyncio.create_task(self._animar_resultado(msg, embed, resultado, valor, ctx.author))

    @prefix_slots.error
    async def slots_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument) or isinstance(error, commands.BadArgument):
            await ctx.send("❌ Como usar: `!slots <quantidade>`\nExemplo: `!slots 50`")

    # --- COMANDO DE SLASH (/) ---
    @app_commands.command(name="slots", description="🎰 Gira a máquina de prémios e tenta o Jackpot!")
    @app_commands.describe(valor="Quantos bifinhos vais colocar na máquina?")
    async def slash_slots(self, interaction: discord.Interaction, valor: int):
        sucesso, resposta = await self._handle_slots_logic(interaction.user, valor)
        
        if not sucesso:
            return await interaction.response.send_message(resposta, ephemeral=True)
            
        embed, resultado = resposta
        await interaction.response.send_message(embed=embed)
        
        # Pega a mensagem gerada para a poder editar na animação
        msg = await interaction.original_response()
        
        # Inicia a animação a rodar em fundo
        asyncio.create_task(self._animar_resultado(msg, embed, resultado, valor, interaction.user))


async def setup(bot: commands.Bot):
    await bot.add_cog(MaquinaSlots(bot))