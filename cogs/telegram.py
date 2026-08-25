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

def get_db_promo():
    conn = sqlite3.connect('bifes_links.db', timeout=15)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

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
        self.canais_alvo = ['xetdaspromocoes', 'LaPromotion'] 
        
        self.atualizar_tabela()

        if self.api_id and self.api_hash:
            self.api_id = int(self.api_id)
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            self.bot.loop.create_task(self.iniciar_telegram())
        else:
            print("❌ [Telegram] Erro: TELEGRAM_API_ID ou TELEGRAM_API_HASH faltando no .env")

    def atualizar_tabela(self):
        """ Garante que todas as colunas necessárias existam no banco """
        conn = get_db_promo()
        cursor = conn.cursor()
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
        conn.commit()
        conn.close()

    async def gerar_texto_anuncio(self, produto, info_verde, cupom=None):
        if not self.model: return f"🔥 {produto}"
        
        instrucao_cupom = f"O cupom é **{cupom}**." if cupom else "Sem cupom."
        prompt = f"""
        Crie um título curto e chamativo para promoções no Discord e Telegram.
        Produto: {produto}
        Detalhes: {info_verde}
        {instrucao_cupom}
        Regras:
        1. Máximo 1 linha direta e limpa.
        2. Use 1 emoji no início.
        3. NÃO coloque link.
        """
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            txt = response.text.strip()
            return txt if txt else f"🔥 {produto}"
        except Exception:
            return f"🔥 {produto}"

    def extrair_cupom(self, texto):
        match = re.search(r'(?:cupom|código|use|cupom\s*:)\s*[:\s]+([A-Z0-9_-]{3,20})', texto, re.IGNORECASE)
        if match: return match.group(1).upper()
        return None

    def analisar_texto_mensagem(self, texto, plataforma_padrao="Mercado Livre"):
        linhas = [l.strip() for l in texto.split('\n') if l.strip()]
        if not linhas:
            return "Oferta Especial", "Confira os detalhes no link!", plataforma_padrao

        # Procura onde está o link
        indice_link = next((i for i, l in enumerate(linhas) if "http" in l), -1)

        # Encontra a linha com o nome do produto (evitando linhas que são só emojis ou palavras genéricas como "OFERTA", "CORRE")
        nome_produto = ""
        palavras_ignorar = ['oferta', 'corre', 'promoção', 'imperdível', 'alerta', 'achadinho', 'olha isso', 'atenção', 'baixa de preço']
        
        for linha in linhas:
            linha_limpa = re.sub(r'[^\w\s]', '', linha).strip().lower()
            if not linha_limpa: continue
            if any(linha_limpa == p for p in palavras_ignorar): continue
            if "http" in linha.lower(): continue
            if linha.startswith("R$") or re.match(r'^(por|de|preço|cupom):', linha_limpa): continue
            
            nome_produto = linha
            break

        if not nome_produto:
            nome_produto = linhas[0]

        # Encontra detalhes de preço
        termos_preco = ['r$', '%', 'x de', 'juros', 'cupom', 'pix', 'boleto', 'off', 'frete', 'por:']
        info_verde_lista = []
        vendedor = plataforma_padrao

        for linha in linhas:
            if linha == nome_produto: continue
            if "http" in linha: continue
            
            if any(t in linha.lower() for t in termos_preco):
                info_verde_lista.append(linha)
            elif not any(linha.lower() in p for p in palavras_ignorar) and len(linha) < 40:
                vendedor = linha

        texto_verde = "\n".join(info_verde_lista)
        if not texto_verde:
            texto_verde = "Confira os detalhes da oferta no link!"

        return nome_produto, texto_verde, vendedor

    def resolver_apenas_redirect(self, url):
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        try:
            response = requests.head(url, allow_redirects=True, timeout=6, headers=headers)
            if response.status_code in [301, 302, 303, 307, 308, 403, 405]:
                response = requests.get(url, allow_redirects=True, timeout=6, headers=headers, stream=True)
            return response.url
        except:
            return url

    async def iniciar_telegram(self):
        await self.bot.wait_until_ready()
        try:
            print("[Telegram] Conectando ao Telegram...")
            await self.client.start()
            
            # Sincroniza canais e dialogs no cache do Telethon
            try:
                dialogs = await self.client.get_dialogs(limit=50)
                print(f"[Telegram] 🔄 {len(dialogs)} canais/dialogs sincronizados com sucesso.")
            except Exception as ed:
                print(f"[Telegram] Aviso ao sincronizar dialogs: {ed}")
            
            @self.client.on(events.NewMessage(chats=self.canais_alvo))
            async def handler(event):
                try:
                    await self.processar_mensagem(event)
                except Exception as ep:
                    print(f"❌ [Telegram] Erro ao processar mensagem: {ep}")
                
            print(f"[Telegram] ✅ Monitorando canais: {self.canais_alvo}")
            await self.client.run_until_disconnected()
        except Exception as e:
            print(f"[Telegram] ❌ Erro de conexão Telethon: {e}")

    async def processar_mensagem(self, event):
        texto = event.raw_text or getattr(event.message, 'message', '') or getattr(event.message, 'caption', '') or ""
        
        # 1. Extração Completa de Links (Texto + Entities + Botões Inline)
        links = re.findall(r'(https?://[^\s<>"\']+)', texto)

        # Links embutidos no texto (Hyperlinks)
        if getattr(event.message, 'entities', None):
            for ent in event.message.entities:
                if hasattr(ent, 'url') and ent.url:
                    links.append(ent.url)

        # Links em botões inline (MUITO comum em canais como LaPromotion)
        if getattr(event.message, 'buttons', None):
            for row in event.message.buttons:
                for btn in row:
                    if hasattr(btn, 'url') and btn.url:
                        links.append(btn.url)

        links = list(dict.fromkeys(links)) # Remove duplicatas
        if not links: return

        for link in links:
            # 2. Resolve Redirect primeiro para descobrir a loja real
            url_real = await asyncio.to_thread(self.resolver_apenas_redirect, link)
            url_check = (url_real + " " + link).lower()

            plataforma = None
            if "mercadolivre" in url_check or "meli.la" in url_check: 
                plataforma = "Mercado Livre"
            elif "amazon" in url_check or "amzn" in url_check or "a.co" in url_check or "amzlink.to" in url_check or "link.amazon" in url_check: 
                plataforma = "Amazon"
            elif "shopee" in url_check or "shp.ee" in url_check: 
                plataforma = "Shopee"
            elif "magazineluiza" in url_check or "magalu" in url_check:
                plataforma = "Magalu"
            elif "kabum" in url_check:
                plataforma = "Kabum"
            else:
                plataforma = "Mercado Livre" # Fallback padrão
            
            print(f"🔍 [Telegram] Capturada Oferta ({plataforma}): {link} ➔ {url_real}")
            
            nome_produto, info_verde, nome_vendedor = self.analisar_texto_mensagem(texto, plataforma_padrao=plataforma)
            
            # 3. Geração de ID Único da Oferta
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
            
            if not id_oferta:
                id_oferta = f"TEMP_{hashlib.md5((url_real + nome_produto).encode()).hexdigest()[:8]}"

            # 4. Consulta Banco de Dados
            conn = get_db_promo()
            cursor = conn.cursor()
            cursor.execute("SELECT meu_link, ultima_notificacao, vendedor FROM produtos WHERE mlb_id = ?", (id_oferta,))
            resultado = cursor.fetchone()

            # 5. Baixa Imagem do Telegram se houver
            caminho_imagem = None
            if event.message.photo:
                try:
                    caminho_imagem = await self.client.download_media(event.message, file=f"imagens_temp/{id_oferta}.jpg")
                except Exception as e_img:
                    print(f"⚠️ Erro ao baixar foto do Telegram: {e_img}")

            canal_ofertas = self.bot.get_channel(self.ml_channel_id) if self.ml_channel_id else None

            # --- CASO 1: REPOST (JÁ FOI APROVADO ANTERIORMENTE) ---
            if resultado and resultado[0]:
                meu_link = resultado[0]
                vendedor_db = resultado[2] or nome_vendedor
                cupom = self.extrair_cupom(texto)
                
                titulo_gerado = await self.gerar_texto_anuncio(nome_produto, info_verde, cupom)
                descricao_final = f"{titulo_gerado}\n\n**{info_verde}**\n\n🛒 **Acesse a promoção aqui:**\n{meu_link}"

                cor_embed = 0xff9900 if plataforma == "Amazon" else (0xee4d2d if plataforma == "Shopee" else 0xffdb15)
                
                embed = discord.Embed(title=nome_produto, description=descricao_final, color=cor_embed, timestamp=datetime.now())
                if cupom: embed.add_field(name="🎟️ Cupom", value=f"`{cupom}`", inline=True)
                embed.set_footer(text=f"Loja: {vendedor_db} • Bifes Bot")
                
                if canal_ofertas:
                    if caminho_imagem and os.path.exists(caminho_imagem):
                        arquivo = discord.File(caminho_imagem, filename="foto.jpg")
                        embed.set_image(url="attachment://foto.jpg")
                        await canal_ofertas.send(content=meu_link, file=arquivo, embed=embed)
                    else:
                        await canal_ofertas.send(content=meu_link, embed=embed)
                conn.close()

            # --- CASO 2: NOVA OFERTA (VAI PRO BANCO & PAINEL PROMOADM) ---
            else:
                agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                titulo_ia = await self.gerar_texto_anuncio(nome_produto, info_verde)

                cursor.execute("""
                    INSERT INTO produtos 
                    (mlb_id, nome, ultima_notificacao, vendedor, url_original, loja_origem, descricao_oferta, titulo_ia) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(mlb_id) DO UPDATE SET 
                    ultima_notificacao=excluded.ultima_notificacao,
                    descricao_oferta=excluded.descricao_oferta,
                    titulo_ia=excluded.titulo_ia
                """, (id_oferta, nome_produto, agora, nome_vendedor, url_real, plataforma, info_verde, titulo_ia))
                conn.commit()
                conn.close()

                print(f"✅ [Telegram] Salvo no banco: [{id_oferta}] {nome_produto}")

                if canal_ofertas:
                    msg_admin = (
                        f"🚨 **NOVA PENDÊNCIA ({plataforma})**\n\n"
                        f"🔵 **Produto:** `{nome_produto}`\n"
                        f"🟢 **Detalhes:**\n{info_verde}\n"
                        f"🏪 **Loja:** {nome_vendedor}\n"
                        f"🟡 **Link Original:** {url_real}\n"
                        f"👉 **Painel:** https://www.bifes.com.br/promoadm.html"
                    )
                    try:
                        if caminho_imagem and os.path.exists(caminho_imagem):
                            arquivo_prev = discord.File(caminho_imagem, filename="preview.jpg")
                            await canal_ofertas.send(content=msg_admin, file=arquivo_prev)
                        else:
                            await canal_ofertas.send(content=msg_admin)
                    except Exception as e_send:
                        print(f"⚠️ Erro ao enviar aviso no canal Discord: {e_send}")

async def setup(bot):
    await bot.add_cog(TelegramListener(bot))