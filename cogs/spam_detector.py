import re
import logging
import discord
from discord.ext import commands

# Setup logger
logger = logging.getLogger('discord_bot')

MIN_SPAM_LENGTH = 15

def is_spam(text: str, min_length: int = MIN_SPAM_LENGTH) -> bool:
    """
    Check if the text is considered spam by detecting excessive repeating characters,
    allowing for spaces or non-alphanumeric characters in between.
    
    :param text: Message text to validate.
    :param min_length: Minimum length of text before spam check is applied.
    :return: True if text is spam, otherwise False.
    """
    text = text.strip()
    # Remove spaces and non-alphanumeric characters for spam detection
    filtered_text = re.sub(r'\W+', '', text)
    if len(filtered_text) >= min_length and len(set(filtered_text)) == 1:
        logger.debug(f"Spam detected in text: {text[:50]}...")  # Log first 50 chars to avoid huge logs
        return True
    return False

class SpamDetector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

async def setup(bot):
    await bot.add_cog(SpamDetector(bot))
    logger.info("SpamDetector cog loaded")
