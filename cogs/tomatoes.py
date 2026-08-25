import discord
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)

class Tomatoes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id == 649396821675868164 and not message.author.bot:
            try:
                await message.add_reaction("🍅")
            except discord.Forbidden:
                logger.error(f"Permissão negada para adicionar reação no canal {message.channel}.")
            except Exception as e:
                logger.exception(f"Erro ao adicionar reação de tomate: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Tomatoes(bot))
