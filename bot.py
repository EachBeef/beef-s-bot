import discord
from discord.ext import commands
import os
import asyncio
import json

# Carrega configurações
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

token = config["token"]
prefix = config["prefix"]

# Configura Intents
intents = discord.Intents.default()
intents.messages = True
intents.reactions = True
intents.guilds = True
intents.message_content = True
intents.members = True # <--- Adicionado para o rank local funcionar e achar os membros!

bot = commands.Bot(command_prefix=prefix, intents=intents)

# Função para carregar as extensões (Cogs)
async def load_extensions():
    # Garante que a pasta cogs existe
    if os.path.exists("cogs"):
        for filename in os.listdir("cogs"):
            if filename.endswith('.py'):
                try:
                    # Carrega cogs.nome_do_arquivo
                    await bot.load_extension(f"cogs.{filename[:-3]}")
                    print(f"📦 Cog carregada: {filename[:-3]}")
                except Exception as e:
                    print(f"❌ Erro ao carregar {filename[:-3]}: {e}")
    else:
        print("⚠️ Pasta 'cogs' não encontrada!")

# Evento de inicialização
@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    print("------")
    
    # --- SINCRONIZAÇÃO AUTOMÁTICA DOS COMANDOS DE BARRA (SLASH) ---
    try:
        print("🔄 Sincronizando comandos slash...")
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comandos slash sincronizados automaticamente.")
    except Exception as e:
        print(f"❌ Erro ao sincronizar comandos: {e}")
    print("------")

# Comando manual de sync (ainda é útil para admins forçarem se precisarem)
@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ {len(synced)} comandos slash sincronizados.")
    except Exception as e:
        await ctx.send(f"❌ Erro ao sincronizar: {e}")

# Função principal de arranque
async def main():
    async with bot:
        # Carrega as Cogs PRIMEIRO (Isso vai iniciar a API e registrar comandos)
        await load_extensions()
        try:
            await bot.start(token)
        except KeyboardInterrupt:
            # Encerra graciosamente se der Ctrl+C
            await bot.close()

if __name__ == "__main__":
    asyncio.run(main())