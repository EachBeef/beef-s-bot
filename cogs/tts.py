import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
from gtts import gTTS
import edge_tts  # NOVA BIBLIOTECA DE VOZES NEURAIS
import asyncio
import os
import re
from datetime import datetime
from googletrans import Translator
import json
import collections
from cogs.spam_detector import is_spam

# Setup logger
logger = logging.getLogger('discord_bot')

TTS_SETTINGS_FILE = 'cogs/tts_settings.json'

class TTSVoiceManager:
    def __init__(self):
        self.translator = Translator()
        
        # Dicionário de vozes atualizado com as Vozes Neurais da Microsoft
        self.voices = {
            'antonio': {
                'name': 'Antônio (Masculino Natural 🇧🇷)', 
                'lang': 'pt-br', 
                'engine': 'edge', 
                'model': 'pt-BR-AntonioNeural'
            },
            'francisca': {
                'name': 'Francisca (Feminino Natural 🇧🇷)', 
                'lang': 'pt-br', 
                'engine': 'edge', 
                'model': 'pt-BR-FranciscaNeural'
            },
            'thalita': {
                'name': 'Thalita (Feminino Jovem 🇧🇷)', 
                'lang': 'pt-br', 
                'engine': 'edge', 
                'model': 'pt-BR-ThalitaNeural'
            },
            'julio': {
                'name': 'Júlio (Masculino Jovem 🇧🇷)', 
                'lang': 'pt-br', 
                'engine': 'edge', 
                'model': 'pt-BR-JulioNeural'
            },
            'google': {
                'name': 'Voz Clássica (Google TTS)', 
                'lang': 'pt-br', 
                'engine': 'gtts',
                'model': 'pt-br'
            },
            'en-us': {'name': 'Inglês (Christopher 🇺🇸)', 'lang': 'en-us', 'engine': 'edge', 'model': 'en-US-ChristopherNeural'},
            'es': {'name': 'Espanhol (Alvaro 🇪🇸)', 'lang': 'es', 'engine': 'edge', 'model': 'es-ES-AlvaroNeural'},
            'ja': {'name': 'Japonês (Keita 🇯🇵)', 'lang': 'ja', 'engine': 'edge', 'model': 'ja-JP-KeitaNeural'}
        }

    async def create_tts_file(self, text, voice_id='antonio'):
        """Cria o arquivo de áudio usando Edge TTS ou gTTS dependendo da escolha"""
        try:
            filename = f'tts_{datetime.now().strftime("%Y%m%d_%H%M%S%f")}.mp3'
            
            # Pega as informações da voz selecionada, se não achar usa o Antonio como padrão
            voice_info = self.voices.get(voice_id, self.voices['antonio'])
            
            if voice_info['engine'] == 'edge':
                # Usa a voz neural super natural da Microsoft
                communicate = edge_tts.Communicate(text, voice_info['model'])
                await communicate.save(filename)
            else:
                # Fallback para o robô clássico do Google
                tts = gTTS(text=text, lang=voice_info['lang'])
                await asyncio.to_thread(tts.save, filename)
            
            return filename
        except Exception as e:
            logger.error(f'Error creating TTS file: {str(e)}')
            return None

    def get_available_voices(self):
        return self.voices

    async def translate_text(self, text, target_lang):
        try:
            if target_lang.startswith('pt'):
                target_lang = 'pt'
            translation = await asyncio.to_thread(self.translator.translate, text, dest=target_lang)
            return translation.text
        except Exception as e:
            logger.error(f'Translation error: {str(e)}')
            return text

# Pre-generate voice choices for slash commands
_temp_vm = TTSVoiceManager()
VOICE_CHOICES = [
    app_commands.Choice(name=info['name'], value=id)
    for id, info in _temp_vm.voices.items()
]
del _temp_vm


class TTS(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_clients = {}
        self.tts_enabled = {}
        self.voice_manager = TTSVoiceManager()
        self.user_settings = {}  # Mudado para user_settings
        self.last_activity = {}
        self.enabled_text_channels = {}  
        self.queues = collections.defaultdict(collections.deque)  
        self._load_settings()
        self.check_activity.start()

    def _clean_text_for_tts(self, text: str) -> str:
        text = re.sub(r'<a?:\w+:\d+>', '', text)
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'\d{7,}', '', text)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  
            "\U0001F300-\U0001F5FF"  
            "\U0001F680-\U0001F6FF"  
            "\U0001F1E0-\U0001F1FF"  
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE,
        )
        text = emoji_pattern.sub('', text)
        return text.strip()

    def _load_settings(self):
        try:
            if os.path.exists(TTS_SETTINGS_FILE):
                with open(TTS_SETTINGS_FILE, 'r') as f:
                    self.user_settings = json.load(f)
            else:
                self.user_settings = {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading TTS settings: {e}")
            self.user_settings = {}

    def _save_settings(self):
        try:
            with open(TTS_SETTINGS_FILE, 'w') as f:
                json.dump(self.user_settings, f, indent=4)
        except IOError as e:
            logger.error(f"Error saving TTS settings: {e}")

    async def _send_message(self, ctx, content=None, embed=None, ephemeral: bool = False):
        try:
            if isinstance(ctx, discord.Interaction):
                if not ctx.response.is_done():
                    await ctx.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
                else:
                    await ctx.followup.send(content=content, embed=embed, ephemeral=ephemeral)
            else:
                await ctx.send(content=content, embed=embed)
        except discord.Forbidden:
            logger.warning("Bot lacks permission to send text messages in this channel.")
        except discord.HTTPException as e:
            logger.error(f"HTTP Exception while sending message: {e}")

    def cog_unload(self):
        self.check_activity.cancel()

    @tasks.loop(seconds=30)
    async def check_activity(self):
        try:
            current_time = datetime.now()
            for guild_id, voice_client in list(self.voice_clients.items()):
                if not voice_client or not voice_client.is_connected():
                    continue

                channel = voice_client.channel
                members = channel.members
                
                humans = [m for m in members if not m.bot]
                if len(humans) == 0:
                    await self._auto_disconnect(guild_id, "Saí do canal pois não há mais humanos ouvindo.")
                    continue

                last_active = self.last_activity.get(guild_id, current_time)
                inactive_time = (current_time - last_active).total_seconds()
                
                if inactive_time >= 300 and not voice_client.is_playing():  
                    await self._auto_disconnect(guild_id, "Saí do canal por inatividade (5 minutos).")

        except Exception as e:
            logger.error(f'Error in activity checker: {str(e)}')

    async def _auto_disconnect(self, guild_id: int, reason: str):
        try:
            voice_client = self.voice_clients.get(guild_id)
            if voice_client and voice_client.is_connected():
                channel = voice_client.channel
                await voice_client.disconnect()
                self.voice_clients.pop(guild_id, None)
                self.tts_enabled[guild_id] = False
                self.last_activity.pop(guild_id, None)

                if guild_id in self.queues:
                    for audio_file in self.queues.pop(guild_id, []):
                        if os.path.exists(audio_file):
                            try:
                                os.remove(audio_file)
                            except Exception:
                                pass
                
                guild = voice_client.guild
                text_channel_id = self.enabled_text_channels.pop(guild_id, None)
                
                notification_channel = guild.get_channel(text_channel_id) if text_channel_id else guild.system_channel

                if notification_channel:
                    embed = discord.Embed(
                        title="👋 Bot Desconectado!",
                        description=f"Canal: {channel.name}\nMotivo: {reason}",
                        color=discord.Color.red()
                    )
                    try:
                        await notification_channel.send(embed=embed)
                    except discord.Forbidden:
                        pass

                logger.info(f'Bot auto-disconnected from {guild.name}: {reason}')
        except Exception as e:
            logger.error(f'Error in auto disconnect: {str(e)}')

    async def _update_activity(self, guild_id: int):
        self.last_activity[guild_id] = datetime.now()

    @commands.command(name='entrar', help='Faz o bot entrar no canal de voz')
    async def join(self, ctx):
        await self._join(ctx)

    @commands.command(name='sair', help='Faz o bot sair do canal de voz')
    async def leave(self, ctx):
        await self._leave(ctx)

    @commands.command(name='voz', help='Define a voz do TTS')
    async def set_voice(self, ctx, voice_type: str = None):
        await self._set_voice(ctx, voice_type)

    @commands.command(name='tts', help='Faz o bot falar uma mensagem')
    async def tts_cmd(self, ctx, *, text: str):
        await self._speak(ctx, text)

    @commands.command(name='vozes', help='Lista todas as vozes disponíveis')
    async def list_voices(self, ctx):
        await self._list_voices(ctx)

    # Defer adicionado aqui para evitar o erro "O aplicativo não respondeu"
    @app_commands.command(name='entrar', description='Faz o bot entrar no canal de voz')
    async def slash_join(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._join(interaction)

    @app_commands.command(name='sair', description='Faz o bot sair do canal de voz')
    async def slash_leave(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._leave(interaction)

    @app_commands.command(name='voz', description='Define a voz do TTS')
    @app_commands.choices(voice_type=VOICE_CHOICES)
    async def slash_set_voice(self, interaction: discord.Interaction, voice_type: str):
        await interaction.response.defer()
        await self._set_voice(interaction, voice_type)

    @app_commands.command(name='tts', description='Faz o bot falar uma mensagem')
    async def slash_tts(self, interaction: discord.Interaction, texto: str):
        await interaction.response.defer(ephemeral=True)
        await self._speak(interaction, texto)

    @app_commands.command(name='vozes', description='Lista todas as vozes disponíveis')
    async def slash_list_voices(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._list_voices(interaction)

    async def audio_playback_done(self, guild_id, audio_file, error=None):
        if error:
            logger.error(f'Player error in guild {guild_id}: {error}')
        try:
            if os.path.exists(audio_file):
                os.remove(audio_file)
        except Exception as e:
            pass
        await self._play_next_in_queue(guild_id)

    async def _play_next_in_queue(self, guild_id: int):
        if self.queues[guild_id]:
            voice_client = self.voice_clients.get(guild_id)
            if voice_client and not voice_client.is_playing() and voice_client.is_connected():
                audio_file = self.queues[guild_id].popleft()
                await self._update_activity(guild_id)
                try:
                    options = '-filter:a "volume=2.0"'
                    audio_source = discord.FFmpegPCMAudio(audio_file, options=options)
                    voice_client.play(audio_source, after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.audio_playback_done(guild_id, audio_file, e), self.bot.loop))
                except Exception as e:
                    logger.error(f'Error playing audio file {audio_file}: {str(e)}')
                    await self.audio_playback_done(guild_id, audio_file, e)

    async def _join(self, ctx):
        try:
            is_interaction = isinstance(ctx, discord.Interaction)
            author = ctx.user if is_interaction else ctx.author
            guild = ctx.guild
            text_channel = ctx.channel

            if author.voice is None:
                return await self._send_message(ctx, "❌ Você precisa estar em um canal de voz!")

            voice_channel = author.voice.channel
            permissions = voice_channel.permissions_for(guild.me)
            if not permissions.connect:
                return await self._send_message(ctx, "❌ Eu não tenho permissão para **Conectar** neste canal de voz.")
            if not permissions.speak:
                return await self._send_message(ctx, "❌ Eu não tenho permissão para **Falar** neste canal de voz.")

            voice_client = guild.voice_client

            if voice_client is None:
                try:
                    voice_client = await voice_channel.connect(timeout=10.0, reconnect=True)
                except Exception as connection_error:
                    logger.error(f"Discord connection error: {connection_error}")
                    return await self._send_message(ctx, "❌ Erro ao conectar. Tente novamente.")
                self.voice_clients[guild.id] = voice_client
            else:
                await voice_client.move_to(voice_channel)
                self.voice_clients[guild.id] = voice_client

            self.tts_enabled[guild.id] = True
            self.enabled_text_channels[guild.id] = text_channel.id
            await self._update_activity(guild.id)
            
            embed = discord.Embed(
                title="🎤 Bot Conectado!",
                description=f"Conectado ao canal: {voice_channel.name}\nPronto para falar! (Use `/voz` para escolher a sua)",
                color=discord.Color.green()
            )
            await self._send_message(ctx, embed=embed)

        except Exception as e:
            logger.error(f'Error joining voice channel: {str(e)}')

    async def _leave(self, ctx):
        try:
            guild = ctx.guild
            if guild.voice_client:
                guild_id = guild.id
                if guild_id in self.queues:
                    if guild.voice_client.is_playing():
                        guild.voice_client.stop()
                    for audio_file in self.queues.pop(guild_id, []):
                        if os.path.exists(audio_file):
                            os.remove(audio_file)

                await guild.voice_client.disconnect()
                self.voice_clients.pop(guild.id, None)
                self.tts_enabled[guild.id] = False
                self.last_activity.pop(guild.id, None)
                self.enabled_text_channels.pop(guild.id, None)
                
                embed = discord.Embed(
                    title="👋 Bot Desconectado!",
                    description="Saí do canal de voz e limpei a fila de mensagens.",
                    color=discord.Color.red()
                )
                await self._send_message(ctx, embed=embed)
            else:
                await self._send_message(ctx, "❌ Não estou em nenhum canal de voz!")
        except Exception as e:
            logger.error(f'Error leaving voice channel: {str(e)}')

    async def _set_voice(self, ctx, voice_type: str = None):
        try:
            if voice_type is None:
                await self._list_voices(ctx)
                return

            available_voices = self.voice_manager.get_available_voices()
            if voice_type not in available_voices:
                return await self._send_message(ctx, "❌ Voz não encontrada! Use `/vozes` para ver a lista.")

            # SALVA PELO ID DO AUTOR DA MENSAGEM
            is_interaction = isinstance(ctx, discord.Interaction)
            author = ctx.user if is_interaction else ctx.author
            user_id_str = str(author.id)

            self.user_settings[user_id_str] = {
                'voice_type': voice_type,
                'language': available_voices[voice_type]['lang']
            }
            self._save_settings()
            
            if ctx.guild:
                await self._update_activity(ctx.guild.id)

            embed = discord.Embed(
                title="✅ Voz Alterada!",
                description=f"{author.mention}, sua voz agora é: **{available_voices[voice_type]['name']}**",
                color=discord.Color.green()
            )
            await self._send_message(ctx, embed=embed)

        except Exception as e:
            logger.error(f'Error setting voice: {str(e)}')

    async def _speak(self, ctx, text: str):
        try:
            is_interaction = isinstance(ctx, discord.Interaction)
            author = ctx.user if is_interaction else ctx.author
            guild = ctx.guild
            voice_client = guild.voice_client

            if not voice_client:
                return await self._send_message(ctx, "❌ Não estou em um canal de voz! Use `/entrar` primeiro.")
            if not self.tts_enabled.get(guild.id, False):
                return await self._send_message(ctx, "❌ TTS está desativado! Use `/entrar` para ativar.")
                
            if is_spam(text):
                return await self._send_message(ctx, "❌ Mensagem bloqueada por spam.")

            MAX_TEXT_LENGTH = 1000
            if len(text) > MAX_TEXT_LENGTH:
                return await self._send_message(ctx, f"❌ Texto muito longo!")

            await self._update_activity(guild.id)
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text:
                return

            # BUSCA PELO ID DO AUTOR DA MENSAGEM
            user_id_str = str(author.id)
            settings = self.user_settings.get(user_id_str, {'voice_type': 'antonio', 'language': 'pt-br'})
            voz_id = settings.get('voice_type', 'antonio')
            
            if settings['language'] != 'pt-br':
                cleaned_text = await self.voice_manager.translate_text(cleaned_text, settings['language'])

            audio_file = await self.voice_manager.create_tts_file(
                cleaned_text,
                voice_id=voz_id
            )
            
            if audio_file:
                self.queues[guild.id].append(audio_file)
                if not voice_client.is_playing():
                    await self._play_next_in_queue(guild.id)

                if is_interaction:
                    embed = discord.Embed(title="🗣️ Mensagem na Fila", description=f"Na fila: {text}", color=discord.Color.blue())
                    await self._send_message(ctx, embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Error in speak command: {str(e)}')

    async def _list_voices(self, ctx):
        try:
            available_voices = self.voice_manager.get_available_voices()
            embed = discord.Embed(
                title="🎙️ Vozes Disponíveis",
                description="Use `/voz <nome>` para selecionar a sua voz preferida!",
                color=discord.Color.blue()
            )

            pt_voices = [(vid, vinfo) for vid, vinfo in available_voices.items() if vinfo['lang'] == 'pt-br']
            other_voices = [(vid, vinfo) for vid, vinfo in available_voices.items() if vinfo['lang'] != 'pt-br']
            
            embed.add_field(
                name="🇧🇷 Português",
                value="\n".join([f"`{v[0]}`: {v[1]['name']}" for v in pt_voices]),
                inline=False
            )
            embed.add_field(
                name="🌎 Outras",
                value="\n".join([f"`{v[0]}`: {v[1]['name']}" for v in other_voices]),
                inline=False
            )
            await self._send_message(ctx, embed=embed)
        except Exception as e:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            if before.channel and before.channel != after.channel:
                if self.bot.user in before.channel.members:
                    guild_id = before.channel.guild.id
                    voice_client = self.voice_clients.get(guild_id)
                    if voice_client and voice_client.channel == before.channel:
                        humans = [m for m in before.channel.members if not m.bot]
                        if len(humans) == 0:
                            await self._auto_disconnect(guild_id, "Saí do canal pois fiquei sozinho.")
        except Exception as e:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author == self.bot.user or not message.guild or not self.tts_enabled.get(message.guild.id, False):
                return

            voice_client = self.voice_clients.get(message.guild.id)
            if not voice_client:
                return

            ctx = await self.bot.get_context(message)
            if ctx.valid or message.content.startswith('/'):
                return

            if message.channel.id != self.enabled_text_channels.get(message.guild.id):
                return
                
            text = message.content
            
            if is_spam(text):
                try:
                    await message.channel.send(f"{message.author.mention} pare de spammar.")
                    await message.delete()
                except discord.Forbidden:
                    pass
                return

            # BUSCA PELO ID DO AUTOR DA MENSAGEM
            user_id_str = str(message.author.id)
            settings = self.user_settings.get(user_id_str, {'voice_type': 'antonio', 'language': 'pt-br'})
            voz_id = settings.get('voice_type', 'antonio')

            text_to_speak = self._clean_text_for_tts(message.content)

            for user in message.mentions:
                text_to_speak = text_to_speak.replace(f'<@{user.id}>', user.name).replace(f'<@!{user.id}>', user.name)
            for channel in message.channel_mentions:
                text_to_speak = text_to_speak.replace(f'<#{channel.id}>', 'um canal foi mencionado')

            if len(text_to_speak) > 1000 or not text_to_speak:
                return

            if settings['language'] != 'pt-br':
                text_to_speak = await self.voice_manager.translate_text(text_to_speak, settings['language'])

            await self._update_activity(message.guild.id)

            audio_file = await self.voice_manager.create_tts_file(
                text_to_speak,
                voice_id=voz_id
            )

            if audio_file:
                self.queues[message.guild.id].append(audio_file)
                if not voice_client.is_playing():
                    await self._play_next_in_queue(message.guild.id)

        except Exception as e:
            logger.error(f'Error in on_message event: {str(e)}')

async def setup(bot):
    await bot.add_cog(TTS(bot))
    logger.info('TTS cog loaded')