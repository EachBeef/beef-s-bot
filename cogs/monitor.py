import discord
from discord.ext import tasks, commands
import sqlite3
import os
import json
import asyncio

# Nome do Banco de Dados (O mesmo do telegram.py e do site)
DB_FILE = "bifes_links.db"
CHANNELS_FILE = "active_channels.json"

class Monitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = self.load_channels()
        # Inicia o loop de verificação
        self.check_database.start()

    def load_channels(self):
        if os.path.exists(CHANNELS_FILE):
            try:
                with open(CHANNELS_FILE, "r") as f:
                    return set(json.load(f))
            except: return set()
        return set()

    def save_channels(self):
        with open(CHANNELS_FILE, "w") as f:
            json.dump(list(self.active_channels), f)

    def get_db_connection(self):
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row # Para acessar colunas pelo nome
        return conn

    # --- COMANDOS DE ATIVAÇÃO ---
    @commands.hybrid_command(name="promoon", description="Ativa o envio de promoções neste canal.")
    @commands.has_permissions(administrator=True)
    async def promoon(self, ctx):
        channel_id = ctx.channel.id
        if channel_id in self.active_channels:
            await ctx.send("✅ As promoções já estão ativas neste canal!", ephemeral=True)
        else:
            self.active_channels.add(channel_id)
            self.save_channels()
            await ctx.send(f"📢 **Promoções ATIVADAS**! As ofertas aprovadas no site aparecerão aqui.", ephemeral=False)

    @commands.hybrid_command(name="promoff", description="Desativa o envio de promoções.")
    @commands.has_permissions(administrator=True)
    async def promoff(self, ctx):
        channel_id = ctx.channel.id
        if channel_id not in self.active_channels:
            await ctx.send("❌ As promoções não estavam ativas aqui.", ephemeral=True)
        else:
            self.active_channels.remove(channel_id)
            self.save_channels()
            await ctx.send(f"🔕 **Promoções PAUSADAS** neste canal.", ephemeral=False)

    # --- COMANDO DE DEBUG ---
    @commands.hybrid_command(name="verbanco", description="Mostra as colunas do banco.")
    @commands.has_permissions(administrator=True)
    async def verbanco(self, ctx):
        await ctx.defer(ephemeral=True)
        conn = self.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM produtos ORDER BY rowid DESC LIMIT 1")
            item = cursor.fetchone()
            if not item:
                await ctx.send("❌ Banco vazio.", ephemeral=True)
                return
            dados = dict(item)
            msg_debug = "🕵️ **Debug Banco**\n```ini\n"
            for chave, valor in dados.items():
                msg_debug += f"[{chave}]: {valor}\n"
            msg_debug += "```"
            await ctx.send(msg_debug, ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Erro: {e}", ephemeral=True)
        finally:
            conn.close()

    # --- LOOP DE POSTAGEM ---
    @tasks.loop(seconds=10)
    async def check_database(self):
        conn = self.get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("ALTER TABLE produtos ADD COLUMN posted_discord INTEGER DEFAULT 0")
            conn.commit()
        except: pass

        # Busca itens não postados
        cursor.execute("""
            SELECT * FROM produtos 
            WHERE meu_link IS NOT NULL 
            AND meu_link != '' 
            AND (posted_discord IS NULL OR posted_discord = 0)
        """)
        
        itens_para_postar = cursor.fetchall()

        if not itens_para_postar:
            conn.close()
            return

        for item in itens_para_postar:
            mlb_id = item['mlb_id']
            nome = item['nome']
            link_afiliado = item['meu_link']
            vendedor = item['vendedor'] or "Oferta"
            loja = item['loja_origem']
            
            # --- CORREÇÃO AQUI: Ler 'descricao_oferta' em vez de calcular preço ---
            # O banco não tem coluna 'preco', ele tem 'descricao_oferta' que já vem com texto completo
            texto_oferta = item['descricao_oferta'] if 'descricao_oferta' in item.keys() else None

            # Se por acaso vier vazio, coloca um texto padrão
            if not texto_oferta:
                texto_oferta = "Corre que o preço está imperdível!"

            # Monta a descrição
            descricao = (
                f"🔥 **{nome}**\n\n"
                f"{texto_oferta}\n\n"
                f"🛒 **[Comprar Agora]({link_afiliado})**\n"
                f"Clique para pegar a promoção"
            )
            # ---------------------------------------------------------------------

            cor_embed = 0xff9900 if loja == "Amazon" else 0xffdb15
            
            embed = discord.Embed(
                title=nome,
                description=descricao,
                color=cor_embed,
                url=link_afiliado
            )
            embed.set_footer(text=f"Vendido por: {vendedor} • Aproveite!")

            caminho_imagem = f"imagens_temp/{mlb_id}.jpg"
            imagem_existe = os.path.exists(caminho_imagem)

            for channel_id in self.active_channels:
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    try:
                        if imagem_existe:
                            file_img = discord.File(caminho_imagem, filename="foto.jpg")
                            embed.set_image(url="attachment://foto.jpg")
                            await channel.send(embed=embed, file=file_img)
                            file_img.close()
                        else:
                            await channel.send(embed=embed)
                    except Exception as e:
                        print(f"Erro ao enviar no canal {channel_id}: {e}")

            cursor.execute("UPDATE produtos SET posted_discord = 1 WHERE mlb_id = ?", (mlb_id,))
            conn.commit()
            print(f"✅ [Discord] Postado: {nome}")

        conn.close()

    @check_database.before_loop
    async def before_check_database(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Monitor(bot))