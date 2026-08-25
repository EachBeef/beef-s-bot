import discord
from discord.ext import commands, tasks
import sqlite3
import time

DB_PATH = "bifinhos.db"

class LembretesDaily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.verificador_lembretes.start()

    def cog_unload(self):
        self.verificador_lembretes.cancel()

    @tasks.loop(minutes=1)
    async def verificador_lembretes(self):
        now_ts = int(time.time())
        cooldown = 8 * 60 * 60  # 8 hours in seconds

        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Fetches users who turned on the reminder, haven't been notified yet, and whose cooldown has passed
        c.execute('''
            SELECT user_id, last_claim FROM bifinhos
            WHERE lembrete_ativo = 1 AND aviso_8h = 0
        ''')
        usuarios = c.fetchall()

        for row in usuarios:
            user_id = row['user_id']
            last_claim = row['last_claim']

            if last_claim > 0 and (now_ts >= last_claim + cooldown):
                try:
                    user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
                    if user:
                        embed = discord.Embed(
                            title="🥩 Seus Bifinhos estão prontos!",
                            description="Já se passaram 8 horas! Você já pode resgatar seus bifinhos diários no site.\n\n👉 **[Resgatar Bifinhos](https://www.bifes.com.br/bifinhos)**",
                            color=0x2ecc71
                        )
                        await user.send(embed=embed)
                        
                        # Marks the notification as sent so it doesn't spam them every minute
                        c.execute("UPDATE bifinhos SET aviso_8h = 1 WHERE user_id = ?", (user_id,))
                        conn.commit()
                        
                except discord.Forbidden:
                    # If the user has their DMs closed, we turn off the reminder automatically to save processing power
                    c.execute("UPDATE bifinhos SET lembrete_ativo = 0 WHERE user_id = ?", (user_id,))
                    conn.commit()
                except Exception as e:
                    print(f"Erro ao enviar lembrete para {user_id}: {e}")

        conn.close()

    @verificador_lembretes.before_loop
    async def before_verificador(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(LembretesDaily(bot))