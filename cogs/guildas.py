import discord
from discord.ext import commands, tasks
import sqlite3
import time

DB_PATH = "bifinhos.db"

class RenameModal(discord.ui.Modal, title='Mudar Nome da Call'):
    novo_nome = discord.ui.TextInput(
        label='Novo Nome',
        style=discord.TextStyle.short,
        placeholder='Ex: Esconderijo do Patrão',
        max_length=25
    )

    def __init__(self, voice_channel):
        super().__init__()
        self.voice_channel = voice_channel

    async def on_submit(self, interaction: discord.Interaction):
        await self.voice_channel.edit(name=self.novo_nome.value)
        await interaction.response.send_message(f"✅ O nome da call foi alterado para **{self.novo_nome.value}**!", ephemeral=True)

class AddMemberView(discord.ui.View):
    def __init__(self, txt_channel, voc_channel):
        super().__init__(timeout=120)
        self.txt_channel = txt_channel
        self.voc_channel = voc_channel

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Seleciona os membros para adicionar...", min_values=1, max_values=10)
    async def select_users(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        for user in select.values:
            await self.txt_channel.set_permissions(user, read_messages=True, send_messages=True)
            await self.voc_channel.set_permissions(user, view_channel=True, connect=True)
        await interaction.response.send_message(f"✅ Membros adicionados com sucesso à tua Guilda!", ephemeral=True)

class RemMemberView(discord.ui.View):
    def __init__(self, txt_channel, voc_channel):
        super().__init__(timeout=120)
        self.txt_channel = txt_channel
        self.voc_channel = voc_channel

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Seleciona os membros para remover...", min_values=1, max_values=10)
    async def select_users(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        for user in select.values:
            if user.id == interaction.user.id:
                continue # Segurança: Previne que o dono se remova a si próprio!
            await self.txt_channel.set_permissions(user, overwrite=None)
            await self.voc_channel.set_permissions(user, overwrite=None)
        await interaction.response.send_message(f"✅ Membros removidos com sucesso!", ephemeral=True)

# Esta é a View Persistente (A que o bot nunca esquece)
class GuildaPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # O timeout=None é a magia que faz isto durar para sempre

    async def _get_guilda_channels(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT text_channel_id, voice_channel_id FROM guildas WHERE owner_id = ?", (str(interaction.user.id),)).fetchone()
        conn.close()

        if not row or str(interaction.channel.id) != row[0]:
            await interaction.response.send_message("❌ Apenas o Imperador dono desta guilda pode usar este painel!", ephemeral=True)
            return None, None

        txt = interaction.guild.get_channel(int(row[0]))
        voc = interaction.guild.get_channel(int(row[1]))
        return txt, voc

    @discord.ui.button(label="Adicionar Membro", style=discord.ButtonStyle.success, custom_id="g_add", emoji="➕")
    async def btn_add(self, interaction: discord.Interaction, button: discord.ui.Button):
        txt, voc = await self._get_guilda_channels(interaction)
        if txt and voc:
            await interaction.response.send_message("Seleciona quem pretendes **adicionar**:", view=AddMemberView(txt, voc), ephemeral=True)

    @discord.ui.button(label="Remover Membro", style=discord.ButtonStyle.danger, custom_id="g_rem", emoji="➖")
    async def btn_rem(self, interaction: discord.Interaction, button: discord.ui.Button):
        txt, voc = await self._get_guilda_channels(interaction)
        if txt and voc:
            await interaction.response.send_message("Seleciona quem pretendes **remover**:", view=RemMemberView(txt, voc), ephemeral=True)

    @discord.ui.button(label="Renomear Call", style=discord.ButtonStyle.primary, custom_id="g_ren", emoji="✏️")
    async def btn_ren(self, interaction: discord.Interaction, button: discord.ui.Button):
        txt, voc = await self._get_guilda_channels(interaction)
        if txt and voc:
            await interaction.response.send_modal(RenameModal(voc))

class GuildasCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(GuildaPanel()) # Registo da view persistente no motor do bot
        self.verificar_vencimentos.start()

    @tasks.loop(hours=1)
    async def verificar_vencimentos(self):
        """Fiscal automático: Roda a cada 1 hora para ver se as 48h de carência passaram."""
        now_ts = int(time.time())
        carencia = 48 * 3600 # 48 horas em segundos

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        query = '''
            SELECT g.owner_id, g.text_channel_id, g.voice_channel_id
            FROM guildas g
            JOIN bifinhos b ON g.owner_id = b.user_id
            WHERE b.tier_vip < 3 OR (b.expira_em > 0 AND b.expira_em < ?)
        '''
        expirados = c.execute(query, (now_ts - carencia,)).fetchall()

        for owner_id, txt_id, voc_id in expirados:
            try:
                # Apagar os canais
                txt = self.bot.get_channel(int(txt_id))
                voc = self.bot.get_channel(int(voc_id))
                if txt: await txt.delete()
                if voc: await voc.delete()
                
                # Avisar o ex-Imperador
                user = self.bot.get_user(int(owner_id))
                if user:
                    await user.send("⚠️ A tua Guilda foi apagada porque o teu título de **Imperador dos Bifes** expirou e passou o período de carência (48h). Renova na loja para criares uma nova e juntares os teus amigos!")
            except Exception as e:
                print(f"Erro ao apagar guilda: {e}")

            c.execute("DELETE FROM guildas WHERE owner_id = ?", (owner_id,))
        
        conn.commit()
        conn.close()

    @verificar_vencimentos.before_loop
    async def before_verificar(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(GuildasCog(bot))