import discord
from discord.ext import commands, tasks
import json
import os
import random
import datetime
import pytz
import asyncio
from discord import app_commands

class Sorteio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.file_path = "sorteios.json"
        self.sorteios_data = self.load_sorteios_data()

    def load_sorteios_data(self):
        """Carrega os sorteios salvos no arquivo JSON."""
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as file:
                return json.load(file)
        return {}

    def save_sorteios_data(self):
        """Salva os sorteios no arquivo JSON."""
        with open(self.file_path, "w") as file:
            json.dump(self.sorteios_data, file, indent=4)

    def parse_tempo(self, tempo_str):
        """Converte uma string de tempo para segundos."""
        tempo_str = tempo_str.lower()
        unidades = {"s": 1, "m": 60, "h": 3600}
        try:
            if tempo_str[-1] in unidades:
                return int(tempo_str[:-1]) * unidades[tempo_str[-1]]
            return int(tempo_str)
        except ValueError:
            return None

    async def create_sorteio_message(self, source, titulo, descricao, tempo):
        """Cria uma mensagem de sorteio e adiciona reação."""
        fuso_horario = pytz.timezone("America/Sao_Paulo")
        horario_resultado = datetime.datetime.now(pytz.utc) + datetime.timedelta(seconds=tempo)
        horario_resultado_brasilia = horario_resultado.astimezone(fuso_horario)
        horario_formatado = horario_resultado_brasilia.strftime("%d/%m/%Y %H:%M:%S %Z")
        embed = discord.Embed(title=titulo, description=descricao, color=discord.Color.gold())
        embed.set_footer(text=f"Resultado do sorteio: {horario_formatado}")
        
        if isinstance(source, commands.Context):
            message = await source.send(embed=embed)
        elif isinstance(source, discord.Interaction):
            if not source.response.is_done():
                await source.response.send_message(embed=embed)
            else:
                await source.followup.send(embed=embed)
            message = await source.original_response()
        
        await message.add_reaction("🎉")
        
        self.sorteios_data[str(message.id)] = {
            "titulo": titulo,
            "descricao": descricao,
            "tempo": tempo,
            "guild_id": message.guild.id,
            "channel_id": message.channel.id
        }
        self.save_sorteios_data()
        
        self.bot.loop.create_task(self.handle_sorteio(message, tempo))

    async def handle_sorteio(self, message, tempo):
        """Espera o tempo do sorteio e escolhe um vencedor."""
        await asyncio.sleep(tempo)
        message = await self.bot.get_channel(message.channel.id).fetch_message(message.id)
        reaction = discord.utils.get(message.reactions, emoji="🎉")
        
        if reaction and reaction.count > 1:
            users = [user async for user in reaction.users() if not user.bot and user != self.bot.user]
            if users:
                winner = random.choice(users)
                titulo = self.sorteios_data[str(message.id)]['titulo']
                embed = discord.Embed(title="🎊 Parabéns ao Vencedor! 🎊", description=f"🎉 {winner.mention}, você ganhou o sorteio: **{titulo}**! 🎉", color=discord.Color.green())
                await message.channel.send(embed=embed)
            else:
                await message.channel.send("Ninguém válido participou do sorteio!")
        else:
            await message.channel.send("Ninguém participou do sorteio!")
        
        del self.sorteios_data[str(message.id)]
        self.save_sorteios_data()

    @commands.command(name="sorteio")
    @commands.has_permissions(administrator=True)
    async def sorteio(self, ctx, tempo: str, titulo: str, *, descricao: str):
        """Cria um sorteio (comando de prefixo)."""
        tempo_segundos = self.parse_tempo(tempo)
        if tempo_segundos is None:
            await ctx.send("Formato de tempo inválido! Use números seguidos de s (segundos), m (minutos) ou h (horas). Exemplo: 10m, 1h, 3600")
            return
        await self.create_sorteio_message(ctx, titulo, descricao, tempo_segundos)

    @app_commands.command(name="sorteio", description="Cria um sorteio.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sorteio_slash(self, interaction: discord.Interaction, tempo: str, titulo: str, descricao: str):
        """Cria um sorteio (comando slash)."""
        await interaction.response.defer()  # Garante resposta imediata para evitar timeout
        tempo_segundos = self.parse_tempo(tempo)
        if tempo_segundos is None:
            await interaction.followup.send("Formato de tempo inválido! Use números seguidos de s (segundos), m (minutos) ou h (horas). Exemplo: 10m, 1h, 3600", ephemeral=True)
            return
        await self.create_sorteio_message(interaction, titulo, descricao, tempo_segundos)
        await interaction.followup.send("Sorteio criado com sucesso!")

async def setup(bot):
    """Função de entrada para carregar o cog."""
    await bot.add_cog(Sorteio(bot))
