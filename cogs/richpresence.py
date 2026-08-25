import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os

class RichPresence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.file_path = "richpresence.json"
        self.activity = None
        self.load_presence()
        self.update_presence.start()

    def load_presence(self):
        """Carrega a última presença salva no arquivo JSON."""
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as file:
                data = json.load(file)
                self.activity = discord.Game(data.get("status", "Usando Discord"))
        else:
            self.activity = discord.Game("Usando Discord")

    def save_presence(self, status):
        """Salva a presença atual no arquivo JSON."""
        with open(self.file_path, "w") as file:
            json.dump({"status": status}, file, indent=4)

    @tasks.loop(seconds=60)
    async def update_presence(self):
        """Atualiza a presença do bot periodicamente."""
        await self.bot.change_presence(activity=self.activity)

    @commands.command(name="richpresence")
    async def richpresence(self, ctx, *, status: str):
        """Define a Rich Presence do bot (comando de prefixo)."""
        if ctx.author.id != 385747293845979138:
            await ctx.send("❌ Você não tem permissão para modificar o rich presence do bot.")
            return
        self.activity = discord.Game(status)
        self.save_presence(status)
        await self.bot.change_presence(activity=self.activity)
        await ctx.send(f"Rich Presence atualizada para: `{status}`")

    @app_commands.command(name="richpresence", description="Define a Rich Presence do bot.")
    async def richpresence_slash(self, interaction: discord.Interaction, status: str):
        """Define a Rich Presence do bot (comando slash)."""
        if interaction.user.id != 385747293845979138:
            await interaction.response.send_message("❌ Você não tem permissão para modificar o rich presence do bot.", ephemeral=True)
            return
        self.activity = discord.Game(status)
        self.save_presence(status)
        await self.bot.change_presence(activity=self.activity)
        await interaction.response.send_message(f"Rich Presence atualizada para: `{status}`", ephemeral=True)

async def setup(bot):
    """Função de entrada para carregar o cog."""
    await bot.add_cog(RichPresence(bot))