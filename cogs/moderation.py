import discord
from discord.ext import commands
from discord import app_commands
import time
import re
import asyncio
import datetime
import json
import os


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.color = self.load_color()
        
    def load_color(self):
        """Carrega a cor do arquivo JSON, ou usa uma cor padrão se não existir."""
        if os.path.exists("color_config.json"):
            with open("color_config.json", "r") as f:
                data = json.load(f)
                return data.get("color", "#e93e00")
        return "#e93e00"

    def save_color(self, color):
        """Salva a cor no arquivo JSON."""
        with open("color_config.json", "w") as f:
            json.dump({"color": color}, f)

    # Comando com prefixo (!decide_color)
    @commands.command(name="decide_color")
    async def decide_color(self, ctx, color: str):
        """Define a cor dos embeds."""
        if not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', color):
            await ctx.send("Por favor, forneça um código de cor hexadecimal válido.")
            return

        self.color = color
        self.save_color(color)
        await ctx.send(f"A cor dos embeds foi definida para {color}.")

    # Slash command (/decide_color)
    @app_commands.command(name="decide_color", description="Define a cor dos embeds.")
    @app_commands.describe(color="Código de cor hexadecimal")
    async def decide_color_slash(self, interaction: discord.Interaction, color: str):
        """Define a cor dos embeds usando um comando de barra."""
        if not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', color):
            await interaction.response.send_message("Por favor, forneça um código de cor hexadecimal válido.", ephemeral=True)
            return

        self.color = color
        self.save_color(color)
        await interaction.response.send_message(f"A cor dos embeds foi definida para {color}.", ephemeral=True)

    # Exemplo de uso da cor nos embeds
    @commands.command(name="ping")
    async def ping(self, ctx):
        """Mostra o ping do bot"""
        latency = self.bot.latency * 1000  # Latência em milissegundos
        embed = discord.Embed(description=f'Pong! 🏓 (Latência: {latency:.2f} ms)', color=discord.Color.from_str(self.color))
        await ctx.send(embed=embed)

    # Slash command (/ping)
    @app_commands.command(name="ping", description="Mostra o ping do bot.")
    async def slash_ping(self, interaction: discord.Interaction):
        """Mostra o ping do bot usando um comando de barra"""
        latency = self.bot.latency * 1000  # Latência em milissegundos
        await interaction.response.send_message(f'Pong! 🏓 (Latência: {latency:.2f} ms)', color=discord.Color.from_str(self.color))
        
        # Comando com prefixo (!mute)
    @commands.command(name="mute")
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def mute(self, ctx, member: discord.Member, *, reason: str = "Nenhuma razão fornecida"):
        guild = ctx.guild
        muted_role = discord.utils.get(guild.roles, name="Muted")

        if not muted_role:
            muted_role = await guild.create_role(name="Muted")

            for channel in guild.channels:
                await channel.set_permissions(muted_role, speak=False, send_messages=False, read_message_history=True, read_messages=False)

        embed = discord.Embed(title="Muted", description=f"{member.mention} foi mutado", color=discord.Color.from_str(self.color), timestamp=datetime.datetime.utcnow())
        embed.add_field(name="Razão:", value=reason, inline=False)
        await ctx.send(embed=embed)
        await member.add_roles(muted_role, reason=reason)
        await member.send(f"Você foi mutado no servidor: {guild.name}. Razão: {reason}")

    # Slash command para mutar um membro
    @app_commands.command(name="mute", description="Muta um membro do servidor.")
    @app_commands.describe(member="Membro a ser mutado", reason="Razão do mutamento")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def mute_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nenhuma razão fornecida"):
        guild = interaction.guild
        muted_role = discord.utils.get(guild.roles, name="Muted")

        if not muted_role:
            muted_role = await guild.create_role(name="Muted")

            for channel in guild.channels:
                await channel.set_permissions(muted_role, speak=False, send_messages=False, read_message_history=True, read_messages=False)

        embed = discord.Embed(title="Muted", description=f"{member.mention} foi mutado", color=discord.Color.from_str(self.color), timestamp=datetime.datetime.utcnow())
        embed.add_field(name="Razão:", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)
        await member.add_roles(muted_role, reason=reason)
        await member.send(f"Você foi mutado no servidor: {guild.name}. Razão: {reason}")

        # Comando com prefixo (!unmute)
    @commands.command(name="unmute")
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def unmute(self, ctx, member: discord.Member):
        guild = ctx.guild
        muted_role = discord.utils.get(guild.roles, name="Muted")

        if muted_role not in member.roles:
            await ctx.send(f"{member.mention} não está mutado.")
            return

        await member.remove_roles(muted_role)
        await member.send(f"Você foi desmutado no servidor: {guild.name}")
        embed = discord.Embed(title="Unmute", description=f"{member.mention} foi desmutado", color=discord.Color.from_str(self.color), timestamp=datetime.datetime.utcnow())
        await ctx.send(embed=embed)

    # Slash command para desmutar um membro
    @app_commands.command(name="unmute", description="Desmuta um membro do servidor.")
    @app_commands.describe(member="Membro a ser desmutado")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def unmute_slash(self, interaction: discord.Interaction, member: discord.Member):
        guild = interaction.guild
        muted_role = discord.utils.get(guild.roles, name="Muted")

        if muted_role not in member.roles:
            await interaction.response.send_message(f"{member.mention} não está mutado.")
            return

        await member.remove_roles(muted_role)
        await member.send(f"Você foi desmutado no servidor: {guild.name}")
        embed = discord.Embed(title="Unmute", description=f"{member.mention} foi desmutado", color=discord.Color.from_str(self.color), timestamp=datetime.datetime.utcnow())
        await interaction.response.send_message(embed=embed)


    # Comando com prefixo (!kick)
    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason=None):
        """Kicka um membro do servidor"""
        try:
            await member.kick(reason=reason)
            await ctx.send(f'{member.mention} foi kickado.')
        except discord.Forbidden:
            await ctx.send('Não tenho permissão para kickar esse membro.')

    # Comando de barra (/kick)
    @app_commands.command(name="kick", description="Kicka um membro do servidor.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def slash_kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nenhuma razão fornecida"):
        """Kicka um membro do servidor usando um comando de barra"""
        try:
            await member.kick(reason=reason)
            await interaction.response.send_message(f'{member.mention} foi kickado.')
        except discord.Forbidden:
            await interaction.response.send_message('Não tenho permissão para kickar esse membro.')

    # Comando de prefixo para desbanir
    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int):
        await self.unban_user(ctx, user_id)

    # Slash command para desbanir
    @app_commands.command(name="unban", description="Desbane um usuário do servidor.")
    @app_commands.describe(user_id="ID do usuário a ser desbanido")
    async def unban_slash(self, interaction: discord.Interaction, user_id: int):
        await self.unban_user(interaction, user_id)

    # Função comum de desbanir
    async def unban_user(self, ctx_or_interaction, user_id):
        if not isinstance(user_id, int):
            await (ctx_or_interaction.response.send_message("O ID do usuário deve ser um número inteiro válido.") if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.send("O ID do usuário deve ser um número inteiro válido."))
            return

        try:
            user = await self.bot.fetch_user(user_id)
            guild = ctx_or_interaction.guild
            await guild.unban(user)
            response_message = f"**Usuário desbanido:** `{user.name}`."
            await (ctx_or_interaction.response.send_message(response_message) if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.send(response_message))
        
            # Enviar mensagem para o canal de logs (se configurado)
            log_channel_id = 123456789012345678  # Substitua pelo ID do canal de logs
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                embed = discord.Embed(title="Desbanimento", color=discord.Color.green())
                embed.add_field(name="Executor", value=ctx_or_interaction.user.name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.name, inline=False)
                embed.add_field(name="Usuário desbanido", value=user.name, inline=False)
                await log_channel.send(embed=embed)
        except discord.NotFound:
            await (ctx_or_interaction.response.send_message(f"Não foi encontrado um usuário com o ID: {user_id}") if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.send(f"Não foi encontrado um usuário com o ID: {user_id}"))
        except discord.Forbidden:
            await (ctx_or_interaction.response.send_message("Não tenho permissão para desbanir esse usuário.") if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.send("Não tenho permissão para desbanir esse usuário."))
    # Comando de prefixo para banir temporariamente
    @commands.command(name="tempban")
    @commands.has_permissions(ban_members=True)
    async def tempban(self, ctx, user: discord.Member, duration: str, *, reason: str = "Nenhuma razão fornecida"):
        await self.tempban_user(ctx, user, duration, reason)

    # Slash command para banir temporariamente
    @app_commands.command(name="tempban", description="Bane temporariamente um usuário do servidor.")
    @app_commands.describe(user="Usuário a ser banido", duration="Duração do banimento", reason="Razão do banimento")
    async def tempban_slash(self, interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "Nenhuma razão fornecida"):
        await self.tempban_user(interaction, user, duration, reason)

    # Função comum de banimento temporário
    async def tempban_user(self, ctx_or_interaction, user, duration, reason):
        # Converter duração para segundos
        seconds = self.parse_duration(duration)
        if seconds is None:
            await (ctx_or_interaction.response.send_message("Duração inválida. Use o formato: `1w3d5h30m20s`.") if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.send("Duração inválida. Use o formato: `1w3d5h30m20s`."))
            return

        try:
            guild = ctx_or_interaction.guild
            await guild.ban(user, reason=reason)
            response_message = f"**Usuário banido temporariamente:** `{user.name}` por {duration}. Razão: `{reason}`"
            await (ctx_or_interaction.response.send_message(response_message) if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.send(response_message))

            # Agendar o unban após a duração
            await self.schedule_unban(guild, user, seconds)

            # Enviar mensagem para o canal de logs (se configurado)
            log_channel_id = 123456789012345678  # Substitua pelo ID do canal de logs
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                embed = discord.Embed(title="Banimento Temporário", color=discord.Color.red())
                embed.add_field(name="Executor", value=ctx_or_interaction.user.name if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.name, inline=False)
                embed.add_field(name="Usuário banido", value=user.name, inline=False)
                embed.add_field(name="Duração", value=duration, inline=False)
                embed.add_field(name="Razão", value=reason, inline=False)
                await log_channel.send(embed=embed)
        except discord.Forbidden:
            await (ctx_or_interaction.response.send_message("Não tenho permissão para banir esse usuário.") if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.send("Não tenho permissão para banir esse usuário."))

    # Função para agendar o desbanimento
    async def schedule_unban(self, guild, user, duration):
        await asyncio.sleep(duration)
        try:
            await guild.unban(user)
            print(f"{user.name} foi desbanido após {duration} segundos.")
        except discord.NotFound:
            print(f"Usuário {user.name} já estava desbanido.")

    # Função para converter duração (1h30m20s) em segundos
    def parse_duration(self, duration_str):
        # Se a duração é apenas um número, trata-se de segundos
        if duration_str.isdigit():
            return int(duration_str)

        # Se a duração é uma string no formato especificado
        pattern = re.compile(r'((?P<weeks>\d+)w)?((?P<days>\d+)d)?((?P<hours>\d+)h)?((?P<minutes>\d+)m)?((?P<seconds>\d+)s)?')
        parts = pattern.match(duration_str)
        if not parts:
            return None
        time_params = {name: int(param) for name, param in parts.groupdict().items() if param}
        return int(time_params.get('weeks', 0)) * 604800 + \
            int(time_params.get('days', 0)) * 86400 + \
            int(time_params.get('hours', 0)) * 3600 + \
            int(time_params.get('minutes', 0)) * 60 + \
            int(time_params.get('seconds', 0))

    # Comando com prefixo (!clear)
    @commands.command(name="clear", aliases=["limpar"])
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def clear(self, ctx, amount: int = 1):
        if amount > 1000:
            await ctx.send("Você pode apagar no máximo 1000 mensagens por vez.")
            return
        
        await ctx.channel.purge(limit=amount + 1)  # +1 para incluir o próprio comando do usuário
        embed = discord.Embed(description=f"Foram excluídas com sucesso **{amount}** mensagens.", color=discord.Color.from_str(self.color))
        confirmation_message = await ctx.send(embed=embed)
        await confirmation_message.delete(delay=5)  # Mensagem desaparece após 5 segundos

    # Slash command para clear mensagens
    @app_commands.command(name="clear", description="Limpa uma quantidade de mensagens do canal (máx. 1000).")
    @app_commands.describe(amount="Quantidade de mensagens a clear")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_slash(self, interaction: discord.Interaction, amount: int = 1):
        if amount > 1000:
            await interaction.response.send_message("Você pode apagar no máximo 1000 mensagens por vez.", ephemeral=True)
            return

        # Adiar a resposta ao comando
        await interaction.response.defer(ephemeral=True)

        # Purge as mensagens, sem incluir o comando da interação
        await interaction.channel.purge(limit=amount)

        # Criar um embed para a mensagem de confirmação
        embed = discord.Embed(description=f"Foram excluídas com sucesso **{amount}** mensagens.", color=discord.Color.from_str(self.color))
        
        # Enviar uma mensagem de confirmação após o purge
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Comando com prefixo (!trancar)
    @commands.command(name="trancar", aliases=["lock"])
    @commands.has_permissions(administrator=True)
    async def trancar(self, ctx):
        channel = ctx.channel
        admin_role = discord.utils.get(ctx.guild.roles, permissions=discord.Permissions(administrator=True))

        # Restringe apenas cargos que não têm permissões administrativas
        for role in ctx.guild.roles:
            if role != admin_role and not role.permissions.administrator:
                await channel.set_permissions(role, send_messages=False)
                await asyncio.sleep(1)  # Pequena pausa para evitar rate limiting
        
        embed = discord.Embed(description=f"O canal {channel.mention} foi trancado. Somente administradores podem enviar mensagens agora.", color=discord.Color.from_str(self.color))
        await ctx.send(embed=embed)

    # Slash command para trancar o canal
    @app_commands.command(name="lock", description="Tranca o canal para que somente administradores possam enviar mensagens.")
    @app_commands.checks.has_permissions(administrator=True)
    async def trancar_slash(self, interaction: discord.Interaction):
        channel = interaction.channel
        admin_role = discord.utils.get(interaction.guild.roles, permissions=discord.Permissions(administrator=True))

        # Envia a resposta inicial rapidamente
        await interaction.response.send_message(f"Trancando o canal {channel.mention}. Isso pode levar alguns segundos...", ephemeral=True)

        # Restringe apenas cargos que não têm permissões administrativas
        for role in interaction.guild.roles:
            if role != admin_role and not role.permissions.administrator:
                await channel.set_permissions(role, send_messages=False)
                await asyncio.sleep(1)  # Pequena pausa para evitar rate limiting

        # Criar um embed para a mensagem de confirmação
        embed = discord.Embed(description=f"O canal {channel.mention} foi trancado com sucesso. Somente administradores podem enviar mensagens agora.", color=discord.Color.from_str(self.color))
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Comando com prefixo (!destrancar)
    @commands.command(name="destrancar", aliases=["unlock"])
    @commands.has_permissions(administrator=True)
    async def destrancar(self, ctx):
        channel = ctx.channel
        admin_role = discord.utils.get(ctx.guild.roles, permissions=discord.Permissions(administrator=True))

        # Remove as restrições de envio de mensagens de todos os cargos que não são administradores
        for role in ctx.guild.roles:
            if role != admin_role and not role.permissions.administrator:
                await channel.set_permissions(role, send_messages=None)  # Remove a restrição
                await asyncio.sleep(1)  # Pequena pausa para evitar rate limiting

        embed = discord.Embed(description=f"O canal {channel.mention} foi destrancado. Todos podem enviar mensagens agora.", color=discord.Color.from_str(self.color))
        await ctx.send(embed=embed)

    # Slash command para destrancar o canal
    @app_commands.command(name="destrancar", description="Destranca o canal permitindo que todos enviem mensagens.")
    @app_commands.checks.has_permissions(administrator=True)
    async def destrancar_slash(self, interaction: discord.Interaction):
        channel = interaction.channel
        admin_role = discord.utils.get(interaction.guild.roles, permissions=discord.Permissions(administrator=True))

        # Envia a resposta inicial rapidamente
        await interaction.response.send_message(f"Destrancando o canal {channel.mention}. Isso pode levar alguns segundos...", ephemeral=True)

        # Remove as restrições de envio de mensagens de todos os cargos que não são administradores
        for role in interaction.guild.roles:
            if role != admin_role and not role.permissions.administrator:
                await channel.set_permissions(role, send_messages=None)  # Remove a restrição
                await asyncio.sleep(1)  # Pequena pausa para evitar rate limiting

        # Criar um embed para a mensagem de confirmação
        embed = discord.Embed(description=f"O canal {channel.mention} foi destrancado. Todos podem enviar mensagens agora.", color=discord.Color.from_str(self.color))
        await interaction.followup.send(embed=embed, ephemeral=True)


    # Função para mutar o usuário temporariamente
    async def tempmute_user(self, ctx_or_interaction, member, duration, reason):
        # Converter a duração para segundos
        seconds = self.parse_duration(duration)
        if seconds is None or seconds <= 0:
            error_message = "Duração inválida. Use o formato: `1w3d5h30m20s` ou insira apenas os segundos."
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(error_message, ephemeral=True)
            else:
                await ctx_or_interaction.send(error_message)
            return

        guild = ctx_or_interaction.guild
        muted_role = discord.utils.get(guild.roles, name="Muted")

        if not muted_role:
            muted_role = await guild.create_role(name="Muted")

            for channel in guild.channels:
                await channel.set_permissions(muted_role, speak=False, send_messages=False, read_message_history=True, read_messages=False)

        await member.add_roles(muted_role, reason=reason)
        embed = discord.Embed(description=f"**{member.mention} foi mutado temporariamente por {duration}.** Razão: `{reason}`", color=discord.Color.from_str(self.color))
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

        # Agendar o desmute após a duração
        await asyncio.sleep(seconds)
        unmute_message = f"{member.mention} foi desmutado automaticamente após {duration}."
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.followup.send(unmute_message)
        else:
            await ctx_or_interaction.send(unmute_message)

    # Comando com prefixo (!tempmute)
    @commands.command(name="tempmute")
    @commands.has_permissions(manage_messages=True)
    async def tempmute(self, ctx, member: discord.Member, duration: str, *, reason: str = "Nenhuma razão fornecida"):
        """Muta temporariamente um membro do servidor"""
        await self.tempmute_user(ctx, member, duration, reason)

    # Slash command (/tempmute)
    @app_commands.command(name="tempmute", description="Muta temporariamente um membro do servidor.")
    @app_commands.describe(member="Membro a ser mutado", duration="Duração do mutamento", reason="Razão do mutamento")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def tempmute_slash(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "Nenhuma razão fornecida"):
        """Muta temporariamente um membro do servidor usando um comando de barra"""
        await self.tempmute_user(interaction, member, duration, reason)

    # Comando com prefixo para trancar chat
    @commands.command(name="tempchat")
    @commands.has_permissions(manage_channels=True)
    async def tempchat_prefix(self, ctx, time_input: str):
        time_in_seconds = self.parse_duration(time_input)
        await self.lock_and_unlock_channel(ctx.channel, time_in_seconds)

    # Slash command para trancar chat
    @app_commands.command(name="tempchat", description="Tranca o chat por um tempo temporário")
    @app_commands.describe(time_input="Tempo para trancar o chat (ex: '2h 10m', ou '600' para 10 minutos)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def tempchat_slash(self, interaction: discord.Interaction, time_input: str):
        time_in_seconds = self.parse_duration(time_input)
        await interaction.response.send_message(f"Chat será bloqueado por {time_in_seconds // 60} minutos.", ephemeral=True)
        await self.lock_and_unlock_channel(interaction.channel, time_in_seconds)

    async def lock_and_unlock_channel(self, channel, time_in_seconds):
        # Bloqueia o canal
        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)
        embed = discord.Embed(description=f"O chat foi trancado por {time_in_seconds // 60} minutos.", color=discord.Color.from_str(self.color))
        await channel.send(embed=embed)

        # Espera o tempo definido
        await asyncio.sleep(time_in_seconds)

        # Desbloqueia o canal
        overwrite.send_messages = True
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)
        embed = discord.Embed(description="O chat foi destrancado automaticamente.", color=discord.Color.from_str(self.color))
        await channel.send(embed=embed)

    def parse_duration(self, duration_str):
        # Implementação da função de conversão de duração
        pass

    # Comando com prefixo para slowmode
    @commands.command(name="slowmode")
    @commands.has_permissions(manage_channels=True)
    async def slowmode_prefix(self, ctx, time_input: str):
        time_in_seconds = self.parse_duration(time_input)

        # Verifica se o tempo está dentro do limite
        if time_in_seconds > 28800:  # 8 horas
            embed = discord.Embed(description="O tempo máximo para o modo lento é de 8 horas (28800 segundos).", color=discord.Color.from_str(self.color))
            await ctx.send(embed=embed)
            return

        await self.set_slowmode(ctx.channel, time_in_seconds)
        embed = discord.Embed(description=f"Modo lento definido para {time_in_seconds} segundos.", color=discord.Color.from_str(self.color))
        await ctx.send(embed=embed)

    # Slash command para slowmode
    @app_commands.command(name="slowmode", description="Define o modo lento (slowmode) no chat")
    @app_commands.describe(time_input="Tempo para o modo lento (ex: '10m', ou '600' para 10 minutos)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode_slash(self, interaction: discord.Interaction, time_input: str):
        time_in_seconds = self.parse_duration(time_input)

        # Verifica se o tempo está dentro do limite
        if time_in_seconds > 28800:  # 8 horas
            embed = discord.Embed(description="O tempo máximo para o modo lento é de 8 horas (28800 segundos).", color=discord.Color.from_str(self.color))
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(description=f"Modo lento será definido para {time_in_seconds} segundos.", color=discord.Color.from_str(self.color))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.set_slowmode(interaction.channel, time_in_seconds)

    # Função que aplica o slowmode
    async def set_slowmode(self, channel, time_in_seconds):
        await channel.edit(slowmode_delay=time_in_seconds)

    def parse_duration(self, duration_str):
        # Implementação da função de conversão de duração
        pass
        
async def setup(bot):
    await bot.add_cog(Moderation(bot))
