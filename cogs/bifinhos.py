import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import io
import os
import time
from datetime import datetime
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

# Caminho do banco
DB_PATH = "bifinhos.db"

# --- ASSET MANAGER ---
def ensure_assets():
    """Baixa as fontes e emojis necessários para evitar telas brancas"""
    assets = {
        "Roboto-Bold.ttf": "https://raw.githubusercontent.com/googlefonts/roboto/main/src/hinted/Roboto-Bold.ttf",
        "Roboto-Medium.ttf": "https://raw.githubusercontent.com/googlefonts/roboto/main/src/hinted/Roboto-Medium.ttf",
        "trophy.png": "https://raw.githubusercontent.com/jdecked/twemoji/master/assets/72x72/1f3c6.png",
        "meat.png": "https://raw.githubusercontent.com/jdecked/twemoji/master/assets/72x72/1f969.png"
    }
    
    print("⏳ Verificando assets visuais do Ranking...")
    for filename, url in assets.items():
        if not os.path.exists(filename):
            try:
                print(f"Baixando {filename}...")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response, open(filename, 'wb') as out_file:
                    out_file.write(response.read())
            except Exception as e:
                print(f"⚠️ Erro ao baixar {filename}: {e}")
    print("✅ Assets verificados e prontos!")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS bifinhos (
            user_id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL,
            last_claim INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def get_user_data(user_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT balance, last_claim FROM bifinhos WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"balance": row[0], "last_claim": row[1]}
    else:
        return {"balance": 0, "last_claim": 0}

def get_text_dimensions(draw_obj, text, font):
    """Garante que a medição de texto funcione independente da versão da biblioteca Pillow"""
    try:
        bbox = draw_obj.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        return draw_obj.textsize(text, font=font)

class Bifinhos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()
        ensure_assets()

    def make_circle_avatar(self, avatar_bytes, size=(90, 90), border_color=(255, 255, 255, 255), border_width=3):
        """Cria o avatar redondo com as bordas dinâmicas do rank"""
        try:
            with Image.open(io.BytesIO(avatar_bytes)) as img:
                img = img.convert("RGBA").resize(size, resample=Image.Resampling.LANCZOS)
                
                mask = Image.new("L", size, 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, size[0], size[1]), fill=255)
                
                output = ImageOps.fit(img, mask.size, centering=(0.5, 0.5))
                output.putalpha(mask)
                
                border_img = Image.new("RGBA", size, (0, 0, 0, 0))
                b_draw = ImageDraw.Draw(border_img)
                b_draw.ellipse((border_width//2, border_width//2, size[0] - border_width//2 - 1, size[1] - border_width//2 - 1), outline=border_color, width=border_width)
                
                final_output = Image.alpha_composite(Image.new("RGBA", size, (0,0,0,0)), output)
                final_output.paste(border_img, (0,0), border_img)
                return final_output
        except Exception as e:
            print(f"Erro ao processar avatar: {e}")
            fallback = Image.new("RGBA", size, (60, 60, 65, 255))
            return fallback

    # ==========================================
    #             FUNÇÕES AUXILIARES
    # ==========================================
    def _create_resgatar_embed(self):
        url = "https://www.bifes.com.br/bifinhos" 
        embed = discord.Embed(
            title="🥩 Hora de pegar Bifinhos!!!",
            description=f"entre aqui e pegue seus bifinhos:\n\n👉 **[CLIQUE AQUI]({url})**",
            color=0x2ecc71
        )
        return embed

    def _create_wallet_embed(self, user: discord.User | discord.Member):
        user_id = str(user.id)
        user_data = get_user_data(user_id)
        balance = user_data["balance"]

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id FROM bifinhos ORDER BY balance DESC")
        rows = c.fetchall()
        conn.close()

        rank = "N/A"
        for i, (uid,) in enumerate(rows):
            if uid == user_id:
                rank = f"#{i + 1}"
                break

        embed = discord.Embed(title=f"🥩 Carteira de {user.display_name}", color=discord.Color.gold())
        embed.add_field(name="💰 Saldo", value=f"**{balance:,}** bifinhos".replace(",", "."), inline=False)
        embed.add_field(name="🏆 Rank Global", value=f"**{rank}**", inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        return embed

    async def _create_monthly_top_embed(self, mes_ano: str = None):
        """Gera o ranking mensal para a competição."""
        if not mes_ano:
            mes_ano = datetime.now().strftime("%m/%Y")
            
        conn = get_db_connection()
        c = conn.cursor()
        
        # BUSCA EXPLÍCITA ATUALIZADA: Adicionado Loteria e Jokenpo!
        c.execute('''
            SELECT user_id, SUM(quantidade) as total_farmado
            FROM historico_mensal
            WHERE mes_ano = ? AND tipo_ganho IN ('diario', 'xadrez', '21', 'poker', 'dados', 'slots', 'roleta', 'loteria', 'jokenpo')
            GROUP BY user_id
            ORDER BY total_farmado DESC
            LIMIT 10
        ''', (mes_ano,))
        rows = c.fetchall()
        conn.close()
        
        embed = discord.Embed(
            title=f"🏆 Top Farmadores de Bifinhos - {mes_ano}",
            description="Estes são os jogadores que mais **farmaram** bifinhos no mês (doações VIP não entram neste rank!).",
            color=0x3498db
        )
        
        if not rows:
            embed.description = "Nenhum bifinho foi farmado neste mês ainda!"
            return embed
            
        ranking_text = ""
        for i, (uid, total) in enumerate(rows):
            try:
                user = self.bot.get_user(int(uid)) or await self.bot.fetch_user(int(uid))
                name = user.display_name
            except:
                name = f"Usuário Desconhecido"
                
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🏅"
            ranking_text += f"{medal} **{i+1}º** - {name}: **{total:,}** 🥩\n".replace(",", ".")
            
        embed.add_field(name="Ranking da Competição", value=ranking_text, inline=False)
        
        # RODAPÉ ATUALIZADO
        embed.set_footer(text="Resgates diários e minigames (Loteria, Jokenpô, Xadrez, Roleta, Slots, etc) contam pontos!")
        return embed

    def _process_boost_logic(self, user_id: str, guild_id: str, member: discord.Member):
        now_ts = int(time.time())
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute("SELECT tier_vip, expira_em FROM bifinhos WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        
        # Verifica se tem um plano VIP ativo
        if not row or row[0] == 0 or row[1] < now_ts:
            conn.close()
            return False, "❌ **Você não tem um título nobre!** Adquira uma assinatura em nossa loja para dar boost em servidores:\n🛒 https://www.bifes.com.br/loja"
            
        tier_vip = row[0]
        multiplicador = 1.0
        nome_plano = ""
        limite_servidores = 1 # Padrão
        
        if tier_vip == 1:
            multiplicador = 1.25
            nome_plano = "Barão da Carne"
            limite_servidores = 1
        elif tier_vip == 2:
            multiplicador = 1.50
            nome_plano = "Rei do Churrasco"
            limite_servidores = 1
        elif tier_vip == 3:
            multiplicador = 2.00
            nome_plano = "Imperador dos Bifes"
            limite_servidores = 2
            
        # ===============================================
        # LÓGICA DE LIMITE DE SERVIDORES (Trava Anti-Abuso)
        # ===============================================
        c.execute("SELECT COUNT(*) FROM servidores_boost WHERE booster_user_id = ? AND expira_em > ? AND guild_id != ?", (user_id, now_ts, guild_id))
        boosts_ativos = c.fetchone()[0]
        
        if boosts_ativos >= limite_servidores:
            conn.close()
            if tier_vip < 3:
                return False, f"⚠️ **Limite Atingido!** O seu título de **{nome_plano}** permite impulsionar apenas **{limite_servidores}** servidor por vez.\nFaça upgrade para **Imperador dos Bifes** na loja para poder dar boost em mais servidores!\n🛒 https://www.bifes.com.br/loja"
            else:
                return False, f"⚠️ **Limite Atingido!** O seu título de **{nome_plano}** já atingiu o limite máximo de impulsionar **{limite_servidores}** servidores simultaneamente."
        # ===============================================
            
        c.execute("SELECT multiplicador, expira_em FROM servidores_boost WHERE guild_id = ?", (guild_id,))
        boost_row = c.fetchone()
        
        # Verifica se o servidor já tem um boost igual ou melhor
        if boost_row and boost_row[1] > now_ts:
            mult_atual = boost_row[0]
            if mult_atual >= multiplicador:
                conn.close()
                return False, f"⚠️ Este servidor já possui um boost ativo de **{mult_atual}x**. O seu boost é de **{multiplicador}x** e não pode sobrescrever um igual ou maior."

        expira_boost = now_ts + (30 * 24 * 60 * 60)
        c.execute('''
            INSERT INTO servidores_boost (guild_id, booster_user_id, multiplicador, expira_em)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
            booster_user_id=excluded.booster_user_id,
            multiplicador=excluded.multiplicador,
            expira_em=excluded.expira_em
        ''', (guild_id, user_id, multiplicador, expira_boost))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(
            title="🚀 SERVIDOR IMPULSIONADO!",
            description=f"O jogador {member.mention} usou seu título de **{nome_plano}** para impulsionar a economia deste servidor!\n\nAgora **TODOS OS MEMBROS** vão receber um bônus de **{multiplicador}x** no comando de bifinhos diários!",
            color=0x2ecc71
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Boost expira em 30 dias • Loja: bifes.com.br/loja")
        
        return True, embed

    async def _generate_ranking_image(self, page: int, guild: discord.Guild = None):
        """Gera a imagem do ranking geral (Quem tem mais dinheiro acumulado no total)."""
        if page < 1: page = 1
        limit = 5
        offset = (page - 1) * limit

        conn = get_db_connection()

        if guild is not None:
            member_ids = [str(m.id) for m in guild.members if not m.bot]
            if not member_ids:
                conn.close()
                return None, 1, 1

            placeholders = ','.join(['?'] * len(member_ids))
            total_users = conn.execute(f"SELECT COUNT(*) FROM bifinhos WHERE user_id IN ({placeholders})", member_ids).fetchone()[0]
            total_pages = max(1, (total_users + limit - 1) // limit)
            if page > total_pages:
                page = total_pages
                offset = (page - 1) * limit
            
            query = f"SELECT user_id, balance FROM bifinhos WHERE user_id IN ({placeholders}) ORDER BY balance DESC LIMIT ? OFFSET ?"
            params = member_ids + [limit, offset]
            rows = conn.execute(query, params).fetchall()
            header_title = f"   TOP LOCAL - PAGINA {page}"
        else:
            total_users = conn.execute("SELECT COUNT(*) FROM bifinhos").fetchone()[0]
            total_pages = max(1, (total_users + limit - 1) // limit)
            if page > total_pages:
                page = total_pages
                offset = (page - 1) * limit

            rows = conn.execute("SELECT user_id, balance FROM bifinhos ORDER BY balance DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            header_title = f"   TOP GLOBAL - PAGINA {page}"

        conn.close()

        if not rows:
            return None, page, total_pages

        # --- CONFIGURAÇÃO DA IMAGEM ---
        W, H = 1200, 750
        bg_color = (18, 18, 22, 255) 
        card_bg = (24, 25, 28, 255)  
        text_white = (255, 255, 255, 255)
        red_color = (255, 70, 70, 255)
        gold_color = (255, 215, 0, 255)
        silver_color = (200, 200, 200, 255)
        bronze_color = (205, 127, 50, 255)

        base_image = Image.new("RGBA", (W, H), bg_color)
        draw = ImageDraw.Draw(base_image)

        for i in range(15):
            y_line = 50 + i * 60
            draw.line((0, y_line, W, y_line), fill=(255, 255, 255, 2), width=1)
            draw.line((150 + i*100, 0, 50 + i*100, H), fill=(255, 70, 70, 5), width=2)

        try:
            font_title = ImageFont.truetype("Roboto-Bold.ttf", 42)
            font_rank_num = ImageFont.truetype("Roboto-Bold.ttf", 32)
            font_rank_label = ImageFont.truetype("Roboto-Medium.ttf", 16)
            font_name = ImageFont.truetype("Roboto-Bold.ttf", 36)
            font_balance_value = ImageFont.truetype("Roboto-Bold.ttf", 26)
            font_bifinhos_word = ImageFont.truetype("Roboto-Medium.ttf", 24)
            font_footer = ImageFont.truetype("Roboto-Medium.ttf", 18)
        except Exception:
            font_title = font_rank_num = font_rank_label = font_name = font_balance_value = font_bifinhos_word = font_footer = ImageFont.load_default()

        tw, th = get_text_dimensions(draw, header_title, font_title)
        tx = (W - tw) // 2
        draw.text((tx, 35), header_title, font=font_title, fill=text_white)

        try:
            trophy = Image.open("trophy.png").convert("RGBA").resize((42, 42), Image.Resampling.LANCZOS)
            base_image.paste(trophy, (tx, 35), trophy)
        except: pass 

        draw.line((350, 100, 850, 100), fill=(255, 70, 70, 80), width=2)

        def draw_neon_element(image_canvas, box, radius, fill_color, border_color):
            temp_glow = Image.new('RGBA', image_canvas.size, (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(temp_glow)
            glow_draw.rounded_rectangle(box, radius=radius, outline=(*border_color[:3], 150), width=12)
            blurred_glow = temp_glow.filter(ImageFilter.GaussianBlur(15))
            image_canvas.alpha_composite(blurred_glow)
            top_draw = ImageDraw.Draw(image_canvas)
            top_draw.rounded_rectangle(box, radius=radius, fill=fill_color, outline=border_color, width=3)

        rank_w, rank_h = 75, 130
        main_w, main_h = 420, 130
        base_y = 140

        for idx, (uid, bal) in enumerate(rows):
            rank = offset + idx + 1
            col = idx % 2
            row = idx // 2

            x_start = 60 if col == 0 else 630
            y = base_y + (row * 165)
            if col == 1: y += 82 

            rank_box = [x_start, y, x_start + rank_w, y + rank_h]
            main_box = [x_start + rank_w + 10, y, x_start + rank_w + 10 + main_w, y + main_h]

            if rank == 1:
                active_color = gold_color
                bal_num_color = red_color
            elif rank == 2:
                active_color = silver_color
                bal_num_color = red_color
            elif rank == 3:
                active_color = bronze_color
                bal_num_color = red_color
            else:
                active_color = red_color
                bal_num_color = red_color

            draw_neon_element(base_image, rank_box, radius=18, fill_color=card_bg, border_color=active_color)
            draw_neon_element(base_image, main_box, radius=18, fill_color=card_bg, border_color=active_color)

            rank_str = f"#{rank}"
            rw, rh = get_text_dimensions(draw, rank_str, font_rank_num)
            draw.text((x_start + (rank_w - rw)//2, y + 35), rank_str, font=font_rank_num, fill=active_color)
            
            lbl_str = "Rank"
            lw, lh = get_text_dimensions(draw, lbl_str, font_rank_label)
            draw.text((x_start + (rank_w - lw)//2, y + 80), lbl_str, font=font_rank_label, fill=(150, 150, 160, 255))

            main_inner_x = x_start + rank_w + 10
            try:
                user = self.bot.get_user(int(uid)) or await self.bot.fetch_user(int(uid))
                name = user.display_name
                avatar_bytes = await user.display_avatar.with_format("png").read()
                avatar_img = self.make_circle_avatar(avatar_bytes, size=(90, 90), border_color=active_color, border_width=3)
            except Exception:
                name = f"ID: {uid}"
                avatar_img = Image.new("RGBA", (90, 90), (60, 60, 65, 255))
                mask = Image.new("L", (90, 90), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, 90, 90), fill=255)
                avatar_img.putalpha(mask)
                ImageDraw.Draw(avatar_img).ellipse((0, 0, 89, 89), outline=active_color, width=3)

            base_image.paste(avatar_img, (main_inner_x + 20, y + 20), avatar_img)

            display_name = (name[:16] + '..') if len(name) > 16 else name
            draw.text((main_inner_x + 130, y + 30), display_name, font=font_name, fill=text_white)

            bal_str = f"{bal:,}".replace(",", ".")
            draw.text((main_inner_x + 130, y + 78), bal_str, font=font_balance_value, fill=bal_num_color)
            vw, vh = get_text_dimensions(draw, bal_str, font_balance_value)
            
            bif_str = " Bifinhos "
            draw.text((main_inner_x + 130 + vw, y + 78), bif_str, font=font_bifinhos_word, fill=text_white)
            bw, bh = get_text_dimensions(draw, bif_str, font_bifinhos_word)

            try:
                meat = Image.open("meat.png").convert("RGBA").resize((28, 28), Image.Resampling.LANCZOS)
                base_image.paste(meat, (int(main_inner_x + 130 + vw + bw), y + 78), meat)
            except: pass

        footer_text = f"Página {page} de {total_pages}"
        fw, fh = get_text_dimensions(draw, footer_text, font_footer)
        fx = (W - fw) // 2
        fy = 700

        draw.rounded_rectangle([fx - 25, fy - 6, fx + fw + 25, fy + fh + 12], radius=18, fill=(35, 36, 40, 255), outline=(50, 50, 55, 255), width=2)
        draw.text((fx, fy), footer_text, font=font_footer, fill=(180, 180, 180, 255))

        image_binary = io.BytesIO()
        base_image.save(image_binary, "PNG")
        image_binary.seek(0)
        return image_binary, page, total_pages


    # ==========================================
    #                PREFIX COMMANDS
    # ==========================================

    @commands.command(name="bifinhosresgatar")
    async def prefix_bifinhosresgatar(self, ctx):
        await ctx.send(embed=self._create_resgatar_embed())

    @commands.command(name="bifinhos")
    async def prefix_bifinhos(self, ctx):
        await ctx.send(embed=self._create_wallet_embed(ctx.author))
        
    @commands.command(name="boost")
    async def prefix_boost(self, ctx):
        if ctx.guild is None:
            return await ctx.send("❌ Este comando só pode ser usado dentro de um servidor.")
        sucesso, resposta = self._process_boost_logic(str(ctx.author.id), str(ctx.guild.id), ctx.author)
        if sucesso:
            await ctx.send(embed=resposta)
        else:
            await ctx.send(resposta)

    @commands.command(name="bifinhostoplocal")
    async def prefix_bifinhostoplocal(self, ctx, page: int = 1):
        if ctx.guild is None:
            return await ctx.send("❌ Comando apenas para servidores.")
        msg_loading = await ctx.send(f"🎨 Obtendo dados do servidor (Página {page})... por favor espere...")
        img_bytes, actual_page, _ = await self._generate_ranking_image(page, guild=ctx.guild)
        if img_bytes is None:
            return await msg_loading.edit(content="❌ Nenhum dado encontrado para o ranking deste servidor.")
        await msg_loading.delete()
        await ctx.send(file=discord.File(fp=img_bytes, filename=f"ranking_local_p{actual_page}.png"))

    @commands.command(name="bifinhostopglobal")
    async def prefix_bifinhostopglobal(self, ctx, page: int = 1):
        msg_loading = await ctx.send(f"🎨 Obtendo dados dos mais ricos em Bifinhos (Página {page})... por favor espere...")
        img_bytes, actual_page, _ = await self._generate_ranking_image(page)
        if img_bytes is None:
            return await msg_loading.edit(content="❌ Nenhum dado encontrado para o ranking.")
        await msg_loading.delete()
        await ctx.send(file=discord.File(fp=img_bytes, filename=f"ranking_p{actual_page}.png"))

    @commands.command(name="bifinhostopmensal")
    async def prefix_bifinhostopmensal(self, ctx, mes: int = None, ano: int = None):
        """Mostra o ranking da competição de um mês específico. Ex: !bifinhostopmensal 3 2026"""
        now = datetime.now()
        
        if mes is not None:
            if not (1 <= mes <= 12):
                return await ctx.send("❌ Mês inválido! Escolha um número de 1 a 12.")
            
            # Se não digitou o ano, pega o ano atual
            final_ano = ano if ano is not None else now.year
            mes_ano = f"{mes:02d}/{final_ano}"
        else:
            mes_ano = now.strftime("%m/%Y")
            
        embed = await self._create_monthly_top_embed(mes_ano)
        await ctx.send(embed=embed)


    # ==========================================
    #                SLASH COMMANDS
    # ==========================================

    @app_commands.command(name="bifinhosresgatar", description="Pega o link para resgatar seus bifinhos!")
    async def slash_bifinhosresgatar(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self._create_resgatar_embed())

    @app_commands.command(name="bifinhos", description="Verifica o saldo e o rank da sua carteira de bifinhos")
    async def slash_bifinhos(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self._create_wallet_embed(interaction.user))
        
    @app_commands.command(name="boost", description="🚀 [VIP] Dá um bônus de Bifinhos para este servidor inteiro!")
    async def slash_boost(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Este comando só pode ser usado dentro de um servidor.", ephemeral=True)
        sucesso, resposta = self._process_boost_logic(str(interaction.user.id), str(interaction.guild.id), interaction.user)
        if sucesso:
            await interaction.response.send_message(embed=resposta)
        else:
            await interaction.response.send_message(resposta, ephemeral=True)

    @app_commands.command(name="bifinhostoplocal", description="Gera uma imagem do ranking de bifinhos DESTE servidor")
    @app_commands.describe(page="Qual página do ranking você quer ver?")
    async def slash_bifinhostoplocal(self, interaction: discord.Interaction, page: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Comando apenas para servidores.", ephemeral=True)
        await interaction.response.defer(thinking=True)
        img_bytes, actual_page, _ = await self._generate_ranking_image(page, guild=interaction.guild)
        if img_bytes is None:
            return await interaction.followup.send(content="❌ Nenhum dado encontrado para o ranking deste servidor.")
        await interaction.followup.send(file=discord.File(fp=img_bytes, filename=f"ranking_local_p{actual_page}.png"))

    @app_commands.command(name="bifinhostopglobal", description="Gera uma imagem do ranking global (Acumulado de todos os tempos)")
    @app_commands.describe(page="Qual página do ranking você quer ver?")
    async def slash_bifinhostopglobal(self, interaction: discord.Interaction, page: int = 1):
        await interaction.response.defer(thinking=True)
        img_bytes, actual_page, _ = await self._generate_ranking_image(page)
        if img_bytes is None:
            return await interaction.followup.send(content="❌ Nenhum dado encontrado para o ranking.")
        await interaction.followup.send(file=discord.File(fp=img_bytes, filename=f"ranking_p{actual_page}.png"))

    @app_commands.command(name="bifinhostopmensal", description="🏆 Mostra quem farmou mais Bifinhos em um mês (Competição)!")
    @app_commands.describe(mes="Mês (ex: 3 para Março). Deixe vazio para o mês atual.", ano="Ano (ex: 2026). Deixe vazio para o ano atual.")
    async def slash_bifinhostopmensal(self, interaction: discord.Interaction, mes: int = None, ano: int = None):
        now = datetime.now()
        
        if mes is not None:
            if not (1 <= mes <= 12):
                return await interaction.response.send_message("❌ Mês inválido! Escolha um número de 1 a 12.", ephemeral=True)
            
            # Se não digitou o ano, pega o ano atual
            final_ano = ano if ano is not None else now.year
            mes_ano = f"{mes:02d}/{final_ano}"
        else:
            mes_ano = now.strftime("%m/%Y")

        await interaction.response.defer(thinking=True)
        embed = await self._create_monthly_top_embed(mes_ano)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Bifinhos(bot))