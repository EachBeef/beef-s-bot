import discord
from discord.ext import commands
import json
import os
from discord import app_commands
import asyncio  # para asyncio.TimeoutError

class ReactionRole(commands.Cog):
    def __init__(self, bot):
        print("Inicializando ReactionRole cog...")  # Log para debug
        self.bot = bot
        self.file_path = "reaction_roles.json"
        self.reactions_data = self.load_reactions_data()

    def load_reactions_data(self):
        """Carrega as informações de mensagens de reação do arquivo JSON."""
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as file:
                return json.load(file)
        return {}

    def save_reactions_data(self):
        """Salva as informações de mensagens de reação no arquivo JSON."""
        with open(self.file_path, "w") as file:
            json.dump(self.reactions_data, file, indent=4)

    @app_commands.command(
        name="criar_reaction_roles",
        description="Cria uma mensagem de reação para atribuir cargos"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def criar_reaction_roles(
        self,
        interaction: discord.Interaction,
        titulo: str,
        descricao: str
    ):
        """Cria uma nova mensagem de reaction roles de forma interativa."""
        await interaction.response.defer()
        
        # Cria o embed inicial
        embed = discord.Embed(
            title=titulo,
            description=f"{descricao}\n\n*Aguardando configuração dos cargos...*",
            color=discord.Color.blue()
        )
        
        # Envia a mensagem inicial com as instruções
        setup_msg = await interaction.followup.send(
            "**Configure os reaction roles respondendo a esta mensagem com o formato:**\n"
            "emoji @cargo\n"
            "emoji @cargo\n"
            "(Um por linha, até 10 cargos)\n\n"
            "Exemplo:\n"
            "🎮 @Gamer\n"
            "🎨 @Artista\n\n"
            "*Você tem 5 minutos para configurar.*",
            embed=embed
        )

        def check(m):
            return (
                m.author == interaction.user and
                m.channel == interaction.channel and
                not m.author.bot
            )

        try:
            # Aguarda a mensagem de configuração
            config_msg = await self.bot.wait_for('message', timeout=300.0, check=check)
            
            # Processa as linhas da configuração
            reactions = {}
            description_lines = [descricao, ""]

            for line in config_msg.content.split('\n'):
                # Limita a 10 configurações válidas
                if len(reactions) >= 10:
                    break

                if not line.strip():
                    continue
                    
                try:
                    emoji, role_mention = line.strip().split(None, 1)
                    # Remove <@& e > para pegar o ID do cargo
                    role_id = int(role_mention.strip('<@&>'))
                    role = interaction.guild.get_role(role_id)
                    
                    if role:
                        # Armazena o emoji usando a mesma formatação (str)
                        reactions[str(emoji)] = role_id
                        description_lines.append(f"\u23DF \u2772 {emoji} \u2773 = @{role.name}")
                    else:
                        print(f"Cargo não encontrado para o ID: {role_id}")
                except Exception as e:
                    # Ignora linhas com erro e imprime o erro para debug
                    print(f"Erro processando a linha '{line}': {e}")
                    continue

            if not reactions:
                await interaction.followup.send("❌ Nenhuma configuração válida fornecida. Tente novamente.")
                return

            # Atualiza o embed com as configurações
            embed.description = '\n'.join(description_lines)
            message = await interaction.channel.send(embed=embed)

            # Adiciona as reações na mensagem
            for emoji in reactions.keys():
                try:
                    await message.add_reaction(emoji)
                except Exception as e:
                    print(f"Erro ao adicionar a reação {emoji}: {e}")

            # Salva os dados no JSON
            self.reactions_data[str(message.id)] = {
                "reactions": reactions,
                "guild_id": interaction.guild_id
            }
            self.save_reactions_data()

            # Confirma a configuração
            await interaction.followup.send("✅ Reaction roles configurados com sucesso!")

            # Tenta deletar as mensagens de configuração
            try:
                await setup_msg.delete()
                await config_msg.delete()
            except Exception:
                pass

        except asyncio.TimeoutError:
            await interaction.followup.send("❌ Tempo esgotado. Tente novamente.")
            try:
                await setup_msg.delete()
            except Exception:
                pass

    @app_commands.command(
        name="remover_reaction_roles",
        description="Remove uma mensagem de reaction roles"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def remover_reaction_roles(
        self,
        interaction: discord.Interaction,
        message_id: str
    ):
        """Remove uma mensagem de reaction roles configurada."""
        await interaction.response.defer()

        if message_id in self.reactions_data:
            del self.reactions_data[message_id]
            self.save_reactions_data()
            await interaction.followup.send("✅ Reaction roles removidos com sucesso!")
        else:
            await interaction.followup.send("❌ ID da mensagem não encontrado na configuração.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Adiciona o cargo quando o usuário reage."""
        # Ignora as reações feitas pelo bot
        if payload.user_id == self.bot.user.id:
            return

        message_data = self.reactions_data.get(str(payload.message_id))
        if not message_data:
            return

        guild = self.bot.get_guild(message_data["guild_id"])
        if not guild:
            return

        # Usa sempre o str do emoji para buscar o cargo
        emoji_key = str(payload.emoji)
        role_id = message_data["reactions"].get(emoji_key)

        if role_id is None:
            print(f"Emoji não encontrado na configuração: {emoji_key}")
            return

        role = guild.get_role(role_id)
        if role is None:
            print(f"Cargo com ID {role_id} não encontrado no servidor.")
            return

        # Tenta obter o membro; se não estiver em cache, utiliza fetch_member
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception as e:
                print(f"Erro ao buscar o membro {payload.user_id}: {e}")
                return

        try:
            await member.add_roles(role)
            print(f"Cargo {role.name} adicionado para {member.name}.")
        except Exception as e:
            print(f"Erro ao adicionar cargo {role} para {member}: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Remove o cargo quando o usuário remove a reação."""
        if payload.user_id == self.bot.user.id:
            return

        message_data = self.reactions_data.get(str(payload.message_id))
        if not message_data:
            return

        guild = self.bot.get_guild(message_data["guild_id"])
        if not guild:
            return

        # Usa sempre o str do emoji para buscar o cargo
        emoji_key = str(payload.emoji)
        role_id = message_data["reactions"].get(emoji_key)

        if role_id is None:
            print(f"Emoji não encontrado na configuração: {emoji_key}")
            return

        role = guild.get_role(role_id)
        if role is None:
            print(f"Cargo com ID {role_id} não encontrado no servidor.")
            return

        # Tenta obter o membro; se não estiver em cache, utiliza fetch_member
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception as e:
                print(f"Erro ao buscar o membro {payload.user_id}: {e}")
                return

        try:
            await member.remove_roles(role)
            print(f"Cargo {role.name} removido de {member.name}.")
        except Exception as e:
            print(f"Erro ao remover cargo {role} de {member}: {e}")

async def setup(bot):
    cog = ReactionRole(bot)
    await bot.add_cog(cog)
