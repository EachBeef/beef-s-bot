import discord
from discord.ext import commands
from telethon import TelegramClient, events
import asyncio
import re
import requests
import sqlite3
import os
import hashlib
import google.generativeai as genai
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

class TelegramListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        if not os.path.exists("imagens_temp"):
            os.makedirs("imagens_temp")

        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.gemini_key = os.getenv('GEMINI_API_KEY')
        
        channel_id_env = os.getenv('ML_CHANNEL_ID')
        self.ml_channel_id = int(channel_id_env) if channel_id_env else None
        
        # --- CONFIGURAÇÃO GEMINI ---
        if self.gemini_key:
            try:
                genai.configure(api_key=self.gemini_key)
                self.model = genai.GenerativeModel('gemini-1.5-flash') 
            except Exception as e:
                print(f"⚠️ [Gemini] Erro ao configurar IA: {e}")
                self.model = None
        else:
            self.model = None
            
        self.session_name = 'sessao_bifes_bot'
        
        # 🚨 ATUALIZAÇÃO AQUI: Adicionado o canal LaPromotion
        self.canais_alvo = ['xetdaspromocoes', 'LaPromotion'] 
        
        self.conn = sqlite3.connect('bifes_links.db')
        self.atualizar_tabela()

        if self.api_id and self.api_hash:
            self.api_id = int(self.api_id)
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            self.bot.loop.create_task(self.iniciar_telegram())
        else:
            print("❌ [Telegram] Erro: API_ID ou API_HASH faltando no .env")

    def atualizar_tabela(self):
        """ Garante que todas as colunas necessárias existam no banco """
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS produtos (
                mlb_id TEXT PRIMARY KEY,
                nome TEXT,
                meu_link TEXT,
                ultima_notificacao TEXT,
                vendedor TEXT,
                url_original TEXT,
                loja_origem TEXT,
                descricao_oferta TEXT,
                titulo_ia TEXT
            )
        ''')
        
        colunas_novas = ["vendedor", "url_original", "loja_origem", "descricao_oferta", "titulo_ia"]
        for col in colunas_novas:
            try: 
                cursor.execute(f"ALTER TABLE produtos ADD COLUMN {col} TEXT")
            except: 
                pass 
        self.conn.commit()

    async def gerar_texto_anuncio(self, produto, info_verde, cupom=None):
        if not self.model: return f"🔥 Oferta: {produto}"
        
        instrucao_cupom = f"O cupom é **{cupom}**." if cupom else "Sem cupom."
        prompt = f"""
        Crie um título curto e chamativo para Telegram (estilo clickbait honesto).
        Produto: {produto}
        Detalhes: {info_verde}
        {instrucao_cupom}
        Regras:
        1. Máximo 1 linha.
        2. Use 1 emoji no início.
        3. NÃO coloque o link.
        4. Exemplo: "🔥 R$ 67 CONTO CADA RESERVA"
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text.strip()
        except:
            return f"🔥 Oferta: {produto}"

    def extrair_cupom(self, texto):
        match = re.search(r'(?:cupom|código|use)[:\s]+([A-Z0-9]{4,15})', texto, re.IGNORECASE)
        if match: return match.group(1).upper()
        return None

    def analisar_texto_mensagem(self, texto, plataforma_padrao="Desconhecido"):
        linhas = [l.strip() for l in texto.split('\n') if l.strip()]
        
        indice_link = next((i for i, l in enumerate(linhas) if "http" in l), -1)
        if indice_link == -1: return "Oferta", "", plataforma_padrao
        
        idx_nome = 1 if indice_link > 1 else 0
        nome_produto = linhas[idx_nome]
        
        linha_pre_link = linhas[indice_link - 1]
        termos_preco = ['R$', '%', 'x de', 'juros', 'cupom', 'pix', 'boleto']
        
        if any(t.lower() in linha_pre_link.lower() for t in termos_preco):
            vendedor = plataforma_padrao
            idx_fim_verde = indice_link 
        else:
            vendedor = linha_pre_link
            idx_fim_verde = indice_link - 1 
        
        idx_inicio_verde = idx_nome + 1
        
        info_verde_lista = []
        if idx_fim_verde > idx_inicio_verde:
            info_verde_lista = linhas[idx_inicio_verde:idx_fim_verde]
        
        texto_verde = "\n".join(info_verde_lista)
        
        if not texto_verde:
             texto_verde = "Confira os detalhes no link!"

        return nome_produto, texto_verde, vendedor

    def resolver_apenas_redirect(self, url):
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            response = requests.head(url, allow_redirects=True, timeout=5, headers=headers)
            if response.status_code in [301, 302, 303, 307, 308, 403, 405]:
                 response = requests.get(url, allow_redirects=True, timeout=5, headers=headers, stream=True)
            return response.url
        except:
            return url

    async def iniciar_telegram(self):
        await self.bot.wait_until_ready()
        try:
            print("[Telegram] Conectando...")
            await self.client.start()
            
            @self.client.on(events.NewMessage(chats=self.canais_alvo))
            async def handler(event):
                await self.processar_mensagem(event)
                
            print(f"[Telegram] ✅ Monitorando: {self.canais_alvo}")
            await self.client.run_until_disconnected()
        except Exception as e:
            print(f"[Telegram] ❌ Erro de conexão: {e}")

    async def processar_mensagem(self, event):
        texto = event.raw_text or getattr(event.message, 'message', '') or getattr(event.message, 'caption', '') or ""
        if not texto: return

        links = re.findall(r'(https?://\S+)', texto)

        for link in links:
            plataforma = None
            
            # 🚨 ATUALIZAÇÃO AQUI: Adicionado suporte para Shopee!
            if "mercadolivre" in link or "meli.la" in link: 
                plataforma = "Mercado Livre"
            elif "amazon" in link or "amzn" in link or "a.co" in link or "amzlink.to" in link: 
                plataforma = "Amazon"
            elif "shopee" in link or "shp.ee" in link: 
                plataforma = "Shopee"
            
            if plataforma:
                print(f"🔍 [Telegram] Processando ({plataforma}): {link}")
                
                nome_produto, info_verde, nome_vendedor = self.analisar_texto_mensagem(texto, plataforma_padrao=plataforma)
                url_real = await asyncio.to_thread(self.resolver_apenas_redirect, link)
                
                # 3. ID (Agora com lógica para a Shopee)
                id_oferta = None
                if plataforma == "Mercado Livre":
                    match = re.search(r'MLB[-]?(\d+)', url_real)
                    if match: id_oferta = f"MLB{match.group(1)}"
                elif plataforma == "Amazon":
                    match = re.search(r'/(B0[A-Z0-9]{8})', url_real)
                    if match: id_oferta = f"AMZ_{match.group(1)}"
                elif plataforma == "Shopee":
                    match = re.search(r'-i\.(\d+\.\d+)', url_real)
                    if match: id_oferta = f"SHP_{match.group(1).replace('.','_')}"
                
                if not id_oferta: id_oferta = f"TEMP_{hashlib.md5(link.encode()).hexdigest()[:8]}"

                cursor = self.conn.cursor()
                cursor.execute("SELECT meu_link, ultima_notificacao, vendedor FROM produtos WHERE mlb_id = ?", (id_oferta,))
                resultado = cursor.fetchone()

                caminho_imagem = None
                if event.message.photo:
                    try:
                        caminho_imagem = await self.client.download_media(event.message, file=f"imagens_temp/{id_oferta}.jpg")
                    except: pass

                canal_ofertas = self.bot.get_channel(self.ml_channel_id)

                # --- REPOST (JÁ TEM NO BANCO) ---
                if resultado and resultado[0]:
                    meu_link = resultado[0]
                    vendedor_db = resultado[2] or nome_vendedor
                    cupom = self.extrair_cupom(texto)
                    
                    titulo_gerado = await self.gerar_texto_anuncio(nome_produto, info_verde, cupom)
                    descricao_final = f"{titulo_gerado}\n\n**{info_verde}**\n\n🛒 **Acesse a promoção aqui:**\n{meu_link}"

                    # Cor específica por plataforma
                    cor_embed = 0xff9900 if plataforma == "Amazon" else (0xee4d2d if plataforma == "Shopee" else 0xffdb15)
                    
                    embed = discord.Embed(title=nome_produto, description=descricao_final, color=cor_embed)
                    if cupom: embed.add_field(name="🎟️ Cupom", value=f"`{cupom}`", inline=True)
                    embed.set_footer(text=f"Loja: {vendedor_db} • Bifes Bot")
                    
                    msg_content = f"{meu_link}"
                    
                    if caminho_imagem:
                        arquivo = discord.File(caminho_imagem, filename="foto.jpg")
                        embed.set_image(url="attachment://foto.jpg")
                        await canal_ofertas.send(content=msg_content, file=arquivo, embed=embed)
                        arquivo.close()
                        os.remove(caminho_imagem) 
                    else:
                        await canal_ofertas.send(content=msg_content, embed=embed)

                # --- NOVO (VAI PRO PAINEL ADMIN) ---
                else:
                    agora = datetime.now()
                    titulo_ia = await self.gerar_texto_anuncio(nome_produto, info_verde)

                    if not resultado:
                        cursor.execute("""
                            INSERT OR IGNORE INTO produtos 
                            (mlb_id, nome, ultima_notificacao, vendedor, url_original, loja_origem, descricao_oferta, titulo_ia) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (id_oferta, nome_produto, str(agora), nome_vendedor, url_real, plataforma, info_verde, titulo_ia))
                        self.conn.commit()

                        if canal_ofertas:
                            msg_admin = (
                                f"🚨 **PENDÊNCIA ({plataforma})**\n\n"
                                f"🔵 **Produto:** `{nome_produto}`\n"
                                f"🟢 **Info Capturada:**\n{info_verde}\n"
                                f"🏪 **Loja:** {nome_vendedor}\n"
                                f"🟡 **Link Original:** {url_real}\n"
                                f"👉 **Painel:** https://www.bifes.com.br/promoadm.html"
                            )
                            if caminho_imagem:
                                arquivo_prev = discord.File(caminho_imagem, filename="preview.jpg")
                                await canal_ofertas.send(content=msg_admin, file=arquivo_prev)
                            else:
                                await canal_ofertas.send(content=msg_admin)

async def setup(bot):
    await bot.add_cog(TelegramListener(bot))