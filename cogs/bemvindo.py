import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import re

DB_PATH = "bifinhos.db"

# ==========================================
#              BANCO DE DADOS
# ==========================================
def init_welcome_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL;')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS welcome_config (
            guild_id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            message_text TEXT NOT NULL,
            image_url TEXT,
            is_active INTEGER DEFAULT 1,
            role_id TEXT,
            color_hex TEXT DEFAULT '#2ecc71'
        )
    ''')
    
    # Atualiza o banco caso você já tenha a versão anterior
    try:
        c.execute('ALTER TABLE welcome_config ADD COLUMN role_id TEXT')
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE welcome_config ADD COLUMN color_hex TEXT DEFAULT '#2ecc71'")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()

def get_welcome_config(guild_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel_id, message_text, image_url, is_active, role_id, color_hex FROM welcome_config WHERE guild_id = ?", (guild_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_welcome_config(guild_id: str, channel_id: str, message_text: str, image_url: str = None, is_active: int = 1, role_id: str = None, color_hex: str = "#2ecc71"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO welcome_config (guild_id, channel_id, message_text, image_url, is_active, role_id, color_hex)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
        channel_id=excluded.channel_id,
        message_text=excluded.message_text,
        image_url=excluded.image_url,
        is_active=excluded.is_active,
        role_id=excluded.role_id,
        color_hex=excluded.color_hex
    ''', (guild_id, channel_id, message_text, image_url, is_active, role_id, color_hex))
    conn.commit()
    conn.close()

def extrair_id(texto: str):
    """Extrai apenas os números de uma string (útil se o usuário mencionar <#123> ou <@&123>)"""
    if not texto:
        return None
    numeros = re.sub(r'\D', '', texto)
    return numeros if numeros else None

def get_color_from_hex(hex_str: str):
    """Converte a cor HTML (Ex: #FF0000) para o formato do Discord Embed"""
    if not hex_str:
        return 0x2ecc71 # Verde padrão
    try:
        # Remove o # se o usuário tiver colocado
        hex_clean = hex_str.replace('#', '').strip()
        return int(hex_clean, 16)
    except ValueError:
        return 0x2ecc71 # Retorna verde se o código for inválido


# ==========================================
#              JANELA POP-UP (MODAL)
# ==========================================
class WelcomeModal(discord.ui.Modal, title='Configurar Boas-Vindas'):
    canal_input = discord.ui.TextInput(
        label='Canal (Cole o ID ou Mencione)',
        style=discord.TextStyle.short,
        placeholder='Ex: 123456789 ou #geral',
        required=True
    )
    
    mensagem_input = discord.ui.TextInput(
        label='Mensagem',
        style=discord.TextStyle.paragraph,
        placeholder='Use {usuario}, {nome}, {servidor}, {membros}',
        default='Olá {usuario}! Seja muito bem-vindo(a) ao {servidor}!',
        required=True,
        max_length=2000
    )
    
    cargo_input = discord.ui.TextInput(
        label='Cargo Automático (ID ou Menção) - Opcional',
        style=discord.TextStyle.short,
        placeholder='Ex: 123456789 ou @Membro',
        required=False
    )

    imagem_input = discord.ui.TextInput(
        label='URL da Imagem/GIF - Opcional',
        style=discord.TextStyle.short,
        placeholder='Ex: https://i.imgur.com/suafoto.gif',
        required=False
    )
    
    cor_input = discord.ui.TextInput(
        label='Cor da Borda (HTML Hex) - Opcional',
        style=discord.TextStyle.short,
        placeholder='Ex: #FF5733',
        default='#2ecc71',
        required=False,
        max_length=7
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Pega os valores preenchidos na janela
        canal_str = self.canal_input.value
        mensagem = self.mensagem_input.value
        cargo_str = self.cargo_input.value
        imagem_url = self.imagem_input.value if self.imagem_input.value.strip() else None
        cor_hex = self.cor_input.value if self.cor_input.value.strip() else "#2ecc71"

        # Processa o Canal
        canal_id = extrair_id(canal_str)
        if not canal_id:
            return await interaction.response.send_message("❌ Canal inválido! Cole o ID ou mencione o canal.", ephemeral=True)
        
        canal = interaction.guild.get_channel(int(canal_id))
        if not canal:
            return await interaction.response.send_message("❌ Não consegui encontrar esse canal no servidor.", ephemeral=True)

        # Processa o Cargo (se foi preenchido)
        cargo = None
        if cargo_str.strip():
            role_id = extrair_id(cargo_str)
            if role_id:
                cargo = interaction.guild.get_role(int(role_id))
                if not cargo:
                    return await interaction.response.send_message("❌ Não encontrei esse cargo. Verifique o ID ou menção.", ephemeral=True)

        # Salva no Banco de Dados
        save_welcome_config(
            str(interaction.guild.id), 
            str(canal.id), 
            mensagem, 
            imagem_url, 
            1, 
            str(cargo.id) if cargo else None,
            cor_hex
        )

        # Resposta de Sucesso
        msg_sucesso = f"✅ **Boas-Vindas configuradas com sucesso!**\n💬 **Canal:** {canal.mention}"
        if cargo:
            msg_sucesso += f"\n👔 **Cargo Automático:** {cargo.mention}"
        msg_sucesso += f"\n🎨 **Cor Definida:** `{cor_hex}`"
        if imagem_url:
            msg_sucesso += "\n🖼️ **Imagem:** Adicionada com sucesso!"
            
        msg_sucesso += "\n\n👉 Teste agora mesmo digitando `/bemvindo testar`"

        await interaction.response.send_message(msg_sucesso, ephemeral=True)


# ==========================================
#              COG DO BOT
# ==========================================
class BemVindo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_welcome_db()

    def formatar_mensagem(self, texto: str, member: discord.Member):
        texto = texto.replace("{usuario}", member.mention)
        texto = texto.replace("{nome}", member.display_name)
        texto = texto.replace("{servidor}", member.guild.name)
        texto = texto.replace("{membros}", str(member.guild.member_count))
        return texto

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return

        config = get_welcome_config(str(member.guild.id))
        if not config or config[3] == 0: return

        channel_id, message_text, image_url, _, role_id, color_hex = config
        
        # 1. Dá o cargo automático
        if role_id:
            cargo = member.guild.get_role(int(role_id))
            if cargo:
                try:
                    await member.add_roles(cargo)
                except: pass

        # 2. Manda a mensagem
        channel = member.guild.get_channel(int(channel_id))
        if not channel: return

        embed_color = get_color_from_hex(color_hex)

        embed = discord.Embed(
            title=f"🎉 Bem-vindo(a) ao {member.guild.name}!",
            description=self.formatar_mensagem(message_text, member),
            color=embed_color
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if image_url: embed.set_image(url=image_url)

        try:
            await channel.send(content=member.mention, embed=embed)
        except: pass


    bemvindo_group = app_commands.Group(name="bemvindo", description="Configurações de boas-vindas")

    @bemvindo_group.command(name="configurar", description="Abre a janela (painel) para configurar as boas-vindas do servidor.")
    @app_commands.checks.has_permissions(administrator=True)
    async def bemvindo_configurar(self, interaction: discord.Interaction):
        # Verifica se o servidor já tem config para já deixar os campos preenchidos!
        config = get_welcome_config(str(interaction.guild.id))
        modal = WelcomeModal()
        
        if config:
            modal.canal_input.default = config[0]
            modal.mensagem_input.default = config[1]
            if config[4]: modal.cargo_input.default = config[4]
            if config[2]: modal.imagem_input.default = config[2]
            if config[5]: modal.cor_input.default = config[5]

        await interaction.response.send_modal(modal)

    @bemvindo_group.command(name="desativar", description="Desativa as mensagens de boas-vindas.")
    @app_commands.checks.has_permissions(administrator=True)
    async def bemvindo_desativar(self, interaction: discord.Interaction):
        config = get_welcome_config(str(interaction.guild.id))
        if not config: return await interaction.response.send_message("❌ O sistema já está desativado.", ephemeral=True)
        save_welcome_config(str(interaction.guild.id), config[0], config[1], config[2], 0, config[4], config[5])
        await interaction.response.send_message("🛑 **Sistema desativado!** Nenhuma mensagem será enviada.", ephemeral=True)

    @bemvindo_group.command(name="testar", description="Envia uma mensagem de teste no chat para ver como ficou.")
    @app_commands.checks.has_permissions(administrator=True)
    async def bemvindo_testar(self, interaction: discord.Interaction):
        config = get_welcome_config(str(interaction.guild.id))
        if not config or config[3] == 0:
            return await interaction.response.send_message("❌ O sistema não está configurado. Use `/bemvindo configurar` primeiro.", ephemeral=True)

        embed_color = get_color_from_hex(config[5])

        embed = discord.Embed(
            title=f"🎉 Bem-vindo(a) ao {interaction.guild.name}!",
            description=self.formatar_mensagem(config[1], interaction.user),
            color=embed_color
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        if config[2]: embed.set_image(url=config[2])
            
        cargo_msg = f"\n*(O usuário receberia o cargo: <@&{config[4]}>)*" if config[4] else ""

        await interaction.response.send_message(content=f"*(Exemplo de Teste)*\n{interaction.user.mention}{cargo_msg}", embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(BemVindo(bot))