import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import asyncio
import aiosqlite
import os
import math
import random
from datetime import datetime, timezone, timedelta, time
import json
import re
import google.generativeai as genai
from dotenv import load_dotenv

# ==========================================
# 🔐 CARREGAMENTO DE CHAVES (API)
# ==========================================
load_dotenv()
PANDASCORE_API_KEY = os.getenv("PANDASCORE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configurar o Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 🔄 SISTEMA DE ROTAÇÃO DE CHAVES (SofaScore)
RAPIDAPI_KEYS = [
    os.getenv("RAPIDAPI_KEY_1"),
    os.getenv("RAPIDAPI_KEY_2")
]
current_rapidapi_key_idx = 0

HEADERS_PANDA = {"Authorization": f"Bearer {PANDASCORE_API_KEY}", "Accept": "application/json"}

def get_sofascore_headers():
    key = RAPIDAPI_KEYS[current_rapidapi_key_idx] or ""
    return {
        "x-rapidapi-key": key,
        "x-rapidapi-host": "sofascore.p.rapidapi.com"
    }

def rotate_api_key():
    global current_rapidapi_key_idx
    current_rapidapi_key_idx = (current_rapidapi_key_idx + 1) % len(RAPIDAPI_KEYS)
    print(f"🔄 [Sistema] A trocar para a chave RapidAPI #{current_rapidapi_key_idx + 1}")

# ==========================================
# ⚽ DADOS BASE DO FUTEBOL
# ==========================================
FOOTBALL_LEAGUES = {
    "Brasileirão Série A": 325,
    "Premier League": 17,
    "La Liga": 8,
    "Bundesliga": 35,
    "Ligue 1 McDonald's": 34,
    "Serie A TIM": 23,
    "Copa Libertadores": 384,
    "Champions League": 7
}

# 🧠 CACHE DE IDs DAS TEMPORADAS
SEASON_IDS_CACHE = {}

async def get_season_id(session, tournament_id):
    if tournament_id in SEASON_IDS_CACHE:
        return SEASON_IDS_CACHE[tournament_id]
        
    url = f"https://sofascore.p.rapidapi.com/tournaments/get-seasons?tournamentId={tournament_id}"
    for attempt in range(2):
        async with session.get(url, headers=get_sofascore_headers()) as resp:
            if resp.status == 429:
                rotate_api_key()
                continue
            if resp.status == 200:
                data = await resp.json()
                seasons = data.get('seasons', [])
                if seasons:
                    season_id = seasons[0]['id']
                    SEASON_IDS_CACHE[tournament_id] = season_id
                    return season_id
            break
    return None

# ==========================================
# 🤖 INTEGRAÇÃO GEMINI FLASH (Pesquisa Bet365 com Fallback)
# ==========================================
async def fetch_gemini_odds(home_team, away_team):
    """Utiliza o Gemini para ler a internet e extrair as odds da Bet365 em formato JSON, com sistema de fallback de modelos."""
    if not GEMINI_API_KEY:
        print("⚠️ Chave do Gemini não configurada. A usar odds padrão.")
        return 2.40, 3.20, 2.80

    prompt = f"""
    Pesquisa na internet as odds de apostas de futebol (formato decimal) no site Bet365 para o seguinte jogo: {home_team} vs {away_team}.
    Se não encontrares exatamente da Bet365, usa outra casa de apostas desportivas credível.
    Devolve EXCLUSIVAMENTE um ficheiro JSON válido e estrito com as chaves "casa", "empate" e "fora", contendo os valores decimais.
    Não adiciones texto, nem formatação markdown adicional. Responde apenas com o JSON.
    Exemplo do que deves responder:
    {{"casa": 2.10, "empate": 3.40, "fora": 2.85}}
    """
    
    modelos_para_tentar = [
        'gemini-3.1-flash-lite-preview', # Tentativa 1: O modelo 3.1 Lite que você pediu
        'gemini-3-flash-preview'               # Tentativa 2: O mais robusto (fallback)
    ]
    
    for nome_modelo in modelos_para_tentar:
        try:
            model = genai.GenerativeModel(nome_modelo)
            response = await asyncio.to_thread(model.generate_content, prompt)
            
            # Limpeza defensiva do texto (remove blocos de código markdown)
            regex_pattern = r'`{3}(?:json)?\n?(.*?)\n?`{3}'
            texto_limpo = re.sub(regex_pattern, r'\1', response.text, flags=re.DOTALL).strip()
            
            if not texto_limpo.startswith("{"):
                texto_limpo = response.text.strip()

            dados = json.loads(texto_limpo)
            
            # Proteção contra Erro de NoneType (caso a IA retorne "null")
            odd_h_raw = dados.get("casa")
            odd_d_raw = dados.get("empate")
            odd_a_raw = dados.get("fora")

            odd_h = float(odd_h_raw) if odd_h_raw is not None else 2.40
            odd_d = float(odd_d_raw) if odd_d_raw is not None else 3.20
            odd_a = float(odd_a_raw) if odd_a_raw is not None else 2.80
            
            return odd_h, odd_d, odd_a
            
        except Exception as e:
            print(f"  [IA] Falha com {nome_modelo}. A tentar o próximo se houver. Erro: {e}")
            continue

    print(f"⚠️ Todos os modelos Gemini falharam para {home_team} vs {away_team}. Usando fallback de matemática.")
    return 2.40, 3.20, 2.80

# ==========================================
# ⚙️ MOTOR MATEMÁTICO (PARI-MUTUEL & ODDS)
# ==========================================
def calculate_3way_dynamic_odds(pool_home, pool_draw, pool_away, house_edge=0.92):
    total_pool = pool_home + pool_draw + pool_away
    odd_home = max(1.01, round((total_pool / pool_home) * house_edge, 2)) if pool_home > 0 else 1.01
    odd_draw = max(1.01, round((total_pool / pool_draw) * house_edge, 2)) if pool_draw > 0 else 1.01
    odd_away = max(1.01, round((total_pool / pool_away) * house_edge, 2)) if pool_away > 0 else 1.01
    return odd_home, odd_draw, odd_away

def reverse_engineer_pools(odd_h, odd_d, odd_a, total_liquidity=50000):
    """Converte as odds do Gemini de volta para dinheiro virtual"""
    try:
        prob_h = 1 / float(odd_h)
        prob_d = 1 / float(odd_d)
        prob_a = 1 / float(odd_a)
        
        total_prob = prob_h + prob_d + prob_a
        norm_h = prob_h / total_prob
        norm_d = prob_d / total_prob
        norm_a = prob_a / total_prob
        
        return int(total_liquidity * norm_h), int(total_liquidity * norm_d), int(total_liquidity * norm_a)
    except:
        return 20000, 15000, 17000

def calculate_dynamic_odds(pool_a, pool_b, house_edge=0.92):
    total_pool = pool_a + pool_b
    return max(1.01, round((total_pool / pool_a) * house_edge, 2)), max(1.01, round((total_pool / pool_b) * house_edge, 2))

def calculate_f1_dynamic_odds(driver_pools: dict, house_edge=0.92):
    total_pool = sum(driver_pools.values())
    return dict(sorted({driver: round(max(1.01, (total_pool / pool) * house_edge), 2) if pool > 0 else 1.01 for driver, pool in driver_pools.items()}.items(), key=lambda item: item[1]))

# Horários do Futebol
OPEN_TIME = time(hour=11, minute=0, tzinfo=timezone.utc)  # 08:00 AM BRT
PAYOUT_TIME = time(hour=6, minute=0, tzinfo=timezone.utc) # 03:00 AM BRT

# ==========================================
# 🎮 VALORANT & F1 FETCHERS
# ==========================================
async def fetch_past_matches(session, team_id, limit=20): 
    url = f"https://api.pandascore.co/teams/{team_id}/matches"
    params = {"per_page": limit, "status": "finished", "sort": "-begin_at"}
    async with session.get(url, headers=HEADERS_PANDA, params=params) as response:
        if response.status == 200: return await response.json()
        return []

def calculate_h2h(team_a_id, team_b_id, matches_a):
    h2h_matches = [m for m in matches_a if any(opp['opponent']['id'] == team_b_id for opp in m.get('opponents', []))]
    if not h2h_matches: return 0.5 
    wins_a = sum(1 for m in h2h_matches if m.get('winner_id') == team_a_id)
    return wins_a / len(h2h_matches)

def calculate_advanced_power(team_id, matches):
    if not matches: return 0.0
    power_score = 0.0
    for index, match in enumerate(matches):
        weight = 1.0 - (index * 0.05) 
        team_score = sum(r.get('score', 0) for r in match.get('results', []) if r.get('team_id') == team_id)
        enemy_score = sum(r.get('score', 0) for r in match.get('results', []) if r.get('team_id') != team_id)
        total_maps = team_score + enemy_score
        map_efficiency = (team_score / total_maps) if total_maps > 0 else 0.5
        match_points = 1.0 + (map_efficiency * 0.5) if match.get('winner_id') == team_id else map_efficiency * 0.5
        power_score += (match_points * weight)
    return power_score

async def generate_base_probs(team_a_id, team_b_id):
    async with aiohttp.ClientSession() as session:
        matches_a, matches_b = await asyncio.gather(fetch_past_matches(session, team_a_id), fetch_past_matches(session, team_b_id))
        score_a, score_b = calculate_advanced_power(team_a_id, matches_a), calculate_advanced_power(team_b_id, matches_b)
        h2h_a = calculate_h2h(team_a_id, team_b_id, matches_a)
        total_score = (score_a + 1) + (score_b + 1)
        return ((score_a + 1) / total_score * 0.70) + (h2h_a * 0.30), ((score_b + 1) / total_score * 0.70) + ((1.0 - h2h_a) * 0.30)

async def fetch_f1_pro_odds(round_number="next", base_liquidity=50000):
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.jolpi.ca/ergast/f1/current/driverStandings.json") as resp_std:
            standings = (await resp_std.json())['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']
            total_points = sum(float(d['points']) for d in standings)
            championship_power = {f"{d['Driver']['givenName']} {d['Driver']['familyName']}": float(d['points']) / total_points if total_points > 0 else (1.0 / len(standings)) for d in standings}

        async with session.get("https://api.jolpi.ca/ergast/f1/current/next.json") as resp_sched:
            next_race = (await resp_sched.json())['MRData']['RaceTable']['Races'][0]

        async with session.get(f"https://api.jolpi.ca/ergast/f1/current/{round_number}/qualifying.json") as resp_quali:
            races = (await resp_quali.json())['MRData']['RaceTable']['Races']
            virtual_pools = {}
            if races:
                raw_weights = {f"{d['Driver']['givenName']} {d['Driver']['familyName']}": (math.exp(-0.35 * (int(d['position']) - 1)) * 0.60) + (championship_power.get(f"{d['Driver']['givenName']} {d['Driver']['familyName']}", 0.01) * 0.40) for d in races[0]['QualifyingResults']}
                total_blend = sum(raw_weights.values())
                virtual_pools = {name: base_liquidity * (weight / total_blend) for name, weight in raw_weights.items()}
            else:
                virtual_pools = {name: base_liquidity * max(0.005, w) for name, w in championship_power.items()}
            return virtual_pools, next_race['raceName'], next_race['date'], next_race.get('time', '15:00:00Z')

# ==========================================
# 📱 INTERFACE COM FILTROS E PAGINAÇÃO
# ==========================================
class LeagueSelect(discord.ui.Select):
    def __init__(self, view_parent, available_leagues):
        self.view_parent = view_parent
        
        # Cria as opções baseadas nas ligas que realmente têm jogos abertos no momento
        options = [discord.SelectOption(label="Todas as Ligas", value="all", default=True)]
        for league in sorted(list(available_leagues)):
            options.append(discord.SelectOption(label=league, value=league))
            
        super().__init__(
            placeholder="Filtra por Campeonato...",
            min_values=1,
            max_values=1,
            options=options,
            row=0 # Fica na linha superior aos botões
        )

    async def callback(self, interaction: discord.Interaction):
        # Atualiza o filtro na view principal
        self.view_parent.current_filter = self.values[0]
        self.view_parent.current_page = 0
        
        # Atualiza visualmente qual opção está selecionada
        for option in self.options:
            option.default = (option.value == self.view_parent.current_filter)
            
        self.view_parent.apply_filter_and_update()
        await interaction.response.edit_message(embed=self.view_parent.generate_embed(), view=self.view_parent)

class MatchesPagination(discord.ui.View):
    def __init__(self, all_markets_list, sport_type="valorant", timeout=180):
        super().__init__(timeout=timeout)
        self.all_markets = all_markets_list
        self.filtered_markets = all_markets_list # Inicialmente igual a todos
        self.sport_type = sport_type
        self.current_page = 0
        self.items_per_page = 10 if sport_type == "f1" else 5
        self.current_filter = "all"
        
        # Adiciona o menu suspenso apenas se for futebol e tivermos ligas
        if self.sport_type == "football" and self.all_markets:
            leagues = set(data['league'] for _, data in self.all_markets)
            if len(leagues) > 1: # Só faz sentido mostrar filtro se houver mais de 1 liga com jogos
                self.add_item(LeagueSelect(self, leagues))
                
        self.apply_filter_and_update()

    def apply_filter_and_update(self):
        # Filtra a lista com base no campeonato selecionado
        if self.current_filter == "all":
            self.filtered_markets = self.all_markets
        else:
            self.filtered_markets = [(m_id, data) for m_id, data in self.all_markets if data.get('league') == self.current_filter]
            
        self.max_pages = max(1, (len(self.filtered_markets) - 1) // self.items_per_page + 1)
        self.update_buttons()

    def update_buttons(self):
        # Os botões Prev/Next foram definidos via decorador, precisamos encontrá-los nos items
        prev_btn = next((x for x in self.children if getattr(x, "custom_id", "") == "prev_page"), None)
        next_btn = next((x for x in self.children if getattr(x, "custom_id", "") == "next_page"), None)
        
        if prev_btn: prev_btn.disabled = self.current_page == 0
        if next_btn: next_btn.disabled = self.current_page >= self.max_pages - 1

    def generate_embed(self):
        embed = discord.Embed(
            title="🎰 BifesBet: Mercados Abertos",
            description="⚠️ As cotações mudam conforme a comunidade aposta.\nUsa `/bet <ID> <Escolha> <Valor>` para travares a tua!",
            color=discord.Color.gold()
        )
        
        start = self.current_page * self.items_per_page
        page_markets = self.filtered_markets[start:start + self.items_per_page]

        if not page_markets:
            embed.add_field(name="Nenhum jogo encontrado", value="Não existem partidas agendadas para este filtro.", inline=False)
            return embed

        for m_id, data in page_markets:
            try:
                # Lemos a data como UTC absoluto
                if 'Z' in data['time']:
                    dt_obj = datetime.strptime(data['time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                else:
                    dt_obj = datetime.strptime(data['time'], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                
                # Deixamos o próprio Discord cuidar do fuso horário e exibir na linguagem correta!
                unix_ts = int(dt_obj.timestamp())
                time_str = f"<t:{unix_ts}:F>" 
            except:
                time_str = "TBA"

            if self.sport_type == "f1":
                drivers_text = "".join([f"> 🏎️ **{d}** (`{det['odd']}x`)\n" for d, det in data['drivers'].items()])
                embed.add_field(name=f"🎫 ID: {m_id} | 🏆 {data['name']}", value=f"🕒 {time_str}\n{drivers_text}", inline=False)
            
            elif self.sport_type == "football":
                market_text = (
                    f"> 🏠 **{data['home']}** (`{data['odds']['home']}x`)\n"
                    f"> 🤝 **Empate** (`{data['odds']['draw']}x`)\n"
                    f"> ✈️ **{data['away']}** (`{data['odds']['away']}x`)\n"
                    f"> 🕒 {time_str}"
                )
                embed.add_field(name=f"🎫 ID: {m_id} | ⚽ {data['league']}", value=market_text, inline=False)
                
            else: # Valorant
                market_text = (
                    f"> 🎮 **{data['team_a']['name']}** (`{data['team_a']['odd']}x`)\n"
                    f"> 🆚 **{data['team_b']['name']}** (`{data['team_b']['odd']}x`)\n"
                    f"> 🕒 {time_str}"
                )
                embed.add_field(name=f"🎫 ID: {m_id} | 🏆 {data['name']}", value=market_text, inline=False)
            
        filtro_texto = f" ({self.current_filter})" if self.current_filter != "all" else ""
        embed.set_footer(text=f"Página {self.current_page + 1} de {self.max_pages} • Total: {len(self.filtered_markets)}{filtro_texto}")
        return embed

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary, custom_id="prev_page", row=1)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Próxima ▶", style=discord.ButtonStyle.primary, custom_id="next_page", row=1)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

# ==========================================
# 🧠 COG PRINCIPAL (BifesBet)
# ==========================================
class BifesBetSportsbook(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_markets = {}
        self.VIRTUAL_LIQUIDITY = 20000 

    def save_football_backup(self):
        football_only = {k: v for k, v in self.active_markets.items() if v.get('sport') == 'football'}
        with open("futebol_backup.json", "w", encoding="utf-8") as f:
            json.dump(football_only, f, ensure_ascii=False, indent=4)

    async def cog_load(self):
        async with aiosqlite.connect("banco.db") as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, match_id TEXT, 
                team_bet TEXT, stake INTEGER, payout INTEGER, status TEXT DEFAULT 'pending')''')
            
            await db.execute('''CREATE TABLE IF NOT EXISTS bot_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT, key_name TEXT UNIQUE, value TEXT)''')
            await db.commit()
            
        self.valorant_updater.start()
        self.f1_updater.start()
        self.football_market_updater.start()
        self.football_result_checker.start()
        
        self.bot.loop.create_task(self.check_memory_and_update_football())

    def cog_unload(self):
        self.valorant_updater.cancel()
        self.f1_updater.cancel()
        self.football_market_updater.cancel()
        self.football_result_checker.cancel()

    # ==========================================
    # 🚨 COMANDO ADMIN: FORÇAR ATUALIZAÇÃO
    # ==========================================
    @commands.command(name="forcar_futebol")
    @commands.has_permissions(administrator=True)
    async def forcar_futebol(self, ctx):
        await ctx.send("🔄 A apagar a memória e a convocar o **Gemini AI** para pesquisar novas odds. Isto pode levar alguns segundos...")
        async with aiosqlite.connect("banco.db") as db:
            await db.execute("DELETE FROM bot_memory WHERE key_name = 'last_football_update'")
            await db.commit()
            
        # 💥 LIMPEZA ABSOLUTA: Destrói o backup local antigo e corrompido para forçar a API a criar um 100% novo!
        self.active_markets = {k: v for k, v in self.active_markets.items() if v.get('sport') != 'football'}
        if os.path.exists("futebol_backup.json"):
            os.remove("futebol_backup.json")
            
        await self.check_memory_and_update_football()
        await ctx.send("✅ O Gemini terminou a pesquisa! Utiliza `/matches sport:Futebol` para ver os resultados com cotações reais.")

    # ==========================================
    # 🎮 LOOP: VALORANT 
    # ==========================================
    @tasks.loop(hours=6)
    async def valorant_updater(self):
        print("🎮 [BifesBet] A pesquisar partidas de Valorant...")
        url = "https://api.pandascore.co/valorant/matches/upcoming"
        params = {"per_page": 15, "sort": "begin_at"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS_PANDA, params=params) as response:
                if response.status == 200:
                    matches = await response.json()
                    self.active_markets = {k: v for k, v in self.active_markets.items() if v.get('sport') != 'valorant'}
                    
                    market_id = 1
                    for match in matches:
                        opponents = match.get('opponents', [])
                        if len(opponents) == 2:
                            team_a = opponents[0]['opponent']
                            team_b = opponents[1]['opponent']
                            prob_a, prob_b = await generate_base_probs(team_a['id'], team_b['id'])
                            pool_a = self.VIRTUAL_LIQUIDITY * prob_a
                            pool_b = self.VIRTUAL_LIQUIDITY * prob_b
                            odd_a, odd_b = calculate_dynamic_odds(pool_a, pool_b)
                            
                            self.active_markets[f"VAL-{market_id}"] = {
                                "sport": "valorant",
                                "match_id": match['id'],
                                "name": match['name'],
                                "time": match['begin_at'], 
                                "team_a": {"name": team_a['name'], "odd": odd_a, "pool": pool_a},
                                "team_b": {"name": team_b['name'], "odd": odd_b, "pool": pool_b},
                                "status": "open"
                            }
                            market_id += 1

    @valorant_updater.before_loop
    async def before_valorant_updater(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 🏎️ LOOP: FÓRMULA 1 
    # ==========================================
    @tasks.loop(hours=6)
    async def f1_updater(self):
        print("🏎️ [BifesBet] A pesquisar dados da Fórmula 1...")
        pools, race_name, race_date, race_time = await fetch_f1_pro_odds()
        
        if pools:
            odds = calculate_f1_dynamic_odds(pools)
            drivers_data = {}
            for driver in odds:
                drivers_data[driver] = {"odd": odds[driver], "pool": pools[driver]}
                
            dt_str = f"{race_date}T{race_time}"
            
            self.active_markets["F1-NEXT"] = {
                "sport": "f1",
                "match_id": "f1_next",
                "name": race_name,
                "time": dt_str,
                "drivers": drivers_data,
                "status": "open"
            }

    @f1_updater.before_loop
    async def before_f1_updater(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # ⚽ ROTINA PRINCIPAL DE FUTEBOL (SofaScore + Gemini)
    # ==========================================
    async def check_memory_and_update_football(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        async with aiosqlite.connect("banco.db") as db:
            async with db.execute("SELECT value FROM bot_memory WHERE key_name = 'last_football_update'") as cursor:
                result = await cursor.fetchone()
                
            if result and result[0] == today:
                if os.path.exists("futebol_backup.json"):
                    with open("futebol_backup.json", "r", encoding="utf-8") as f:
                        try:
                            backup = json.load(f)
                            for k, v in backup.items():
                                self.active_markets[k] = v
                                
                            if any(v.get('sport') == 'football' for v in self.active_markets.values()):
                                print("🛡️ [BifesBet] Futebol carregado do backup local.")
                                return
                        except: pass
            
            print("⚽ [BifesBet] A pesquisar novos jogos e a convocar o Gemini para extrair odds reais...")
            
            now_ts = datetime.now(timezone.utc).timestamp()
            min_ts = now_ts - 86400  
            max_ts = now_ts + 172800 
            
            async with aiohttp.ClientSession() as session:
                for league_name, league_id in FOOTBALL_LEAGUES.items():
                    season_id = await get_season_id(session, league_id)
                    if not season_id: continue
                        
                    url = f"https://sofascore.p.rapidapi.com/tournaments/get-next-matches?tournamentId={league_id}&seasonId={season_id}&pageIndex=0"
                    
                    for attempt in range(2):
                        async with session.get(url, headers=get_sofascore_headers()) as response:
                            if response.status == 429:
                                rotate_api_key()
                                continue
                                
                            if response.status == 200:
                                data = await response.json()
                                events = data.get('events', [])
                                
                                self.active_markets = {k: v for k, v in self.active_markets.items() if not (v.get('sport') == 'football' and v.get('league') == league_name)}
                                
                                games_added = 0
                                for event in events:
                                    start_ts = event.get('startTimestamp', 0)
                                    
                                    if min_ts <= start_ts <= max_ts:
                                        match_id = str(event['id'])
                                        home_team = event['homeTeam']['name']
                                        away_team = event['awayTeam']['name']
                                        
                                        # Correção do Timezone: Força a salvar estritamente em UTC
                                        match_time = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                                        
                                        print(f"➔ Gemini a investigar: {home_team} vs {away_team}...")
                                        odd_h, odd_d, odd_a = await fetch_gemini_odds(home_team, away_team)
                                        
                                        pool_home, pool_draw, pool_away = reverse_engineer_pools(odd_h, odd_d, odd_a)
                                        final_h, final_d, final_a = calculate_3way_dynamic_odds(pool_home, pool_draw, pool_away)
                                        
                                        self.active_markets[f"FUT-{match_id}"] = {
                                            "sport": "football", "league": league_name,
                                            "name": f"{home_team} vs {away_team}",
                                            "time": match_time, "home": home_team, "away": away_team,
                                            "pools": {"home": pool_home, "draw": pool_draw, "away": pool_away},
                                            "odds": {"home": final_h, "draw": final_d, "away": final_a},
                                            "status": "open"
                                        }
                                        games_added += 1
                                        
                                print(f"✅ {league_name}: {games_added} jogos cadastrados com odds da Bet365/Gemini.")
                            break
                            
            self.save_football_backup()
            await db.execute("INSERT OR REPLACE INTO bot_memory (key_name, value) VALUES ('last_football_update', ?)", (today,))
            await db.commit()

    @tasks.loop(time=OPEN_TIME) 
    async def football_market_updater(self):
        await self.check_memory_and_update_football()

    @football_market_updater.before_loop
    async def before_football_market_updater(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 💰 LOOP: DISTRIBUIÇÃO DOS BIFINHOS (03:00 AM)
    # ==========================================
    @tasks.loop(time=PAYOUT_TIME)
    async def football_result_checker(self):
        print("🌙 [BifesBet] Madrugada: A verificar resultados e processar pagamentos...")
        async with aiosqlite.connect("banco.db") as db:
            async with db.execute("SELECT DISTINCT match_id FROM bets WHERE status = 'pending' AND match_id LIKE 'FUT-%'") as cursor:
                pending_rows = await cursor.fetchall()

            if not pending_rows: return

            pending_api_ids = [row[0].split("-")[1] for row in pending_rows]

            async with aiohttp.ClientSession() as session:
                for league_name, league_id in FOOTBALL_LEAGUES.items():
                    season_id = await get_season_id(session, league_id)
                    if not season_id: continue
                        
                    url = f"https://sofascore.p.rapidapi.com/tournaments/get-last-matches?tournamentId={league_id}&seasonId={season_id}&pageIndex=0"
                    
                    for attempt in range(2):
                        async with session.get(url, headers=get_sofascore_headers()) as response:
                            if response.status == 429:
                                rotate_api_key()
                                continue
                                
                            if response.status == 200:
                                data = await response.json()
                                events = data.get('events', [])
                                
                                for event in events:
                                    api_match_id = str(event['id'])
                                    full_match_id = f"FUT-{api_match_id}"
                                    
                                    if api_match_id in pending_api_ids and event.get('status', {}).get('type') == 'finished':
                                        home_score = event.get('homeScore', {}).get('current', 0)
                                        away_score = event.get('awayScore', {}).get('current', 0)
                                        
                                        if home_score > away_score: winning_choice = event['homeTeam']['name']
                                        elif away_score > home_score: winning_choice = event['awayTeam']['name']
                                        else: winning_choice = "Draw"
                                        
                                        async with db.execute("SELECT id, user_id, team_bet, payout FROM bets WHERE match_id = ? AND status = 'pending'", (full_match_id,)) as bet_cursor:
                                            bets = await bet_cursor.fetchall()
                                            
                                            for bet_id, user_id, team_bet, payout in bets:
                                                if team_bet == winning_choice or (team_bet == "Draw" and winning_choice == "Draw"):
                                                    await db.execute("UPDATE users SET bifinhos = bifinhos + ? WHERE user_id = ?", (payout, user_id))
                                                    await db.execute("UPDATE bets SET status = 'paid' WHERE id = ?", (bet_id,))
                                                    try:
                                                        user = await self.bot.fetch_user(user_id)
                                                        await user.send(f"🎉 **Pagamento da BifesBet!** O placar final foi {home_score}x{away_score} ({winning_choice})! O depósito de 💰 **{payout:,} Bifinhos** foi efetuado na tua conta.")
                                                    except: pass
                                                else:
                                                    await db.execute("UPDATE bets SET status = 'lost' WHERE id = ?", (bet_id,))
                                        
                                        await db.commit()
                                        
                                        if full_match_id in self.active_markets: 
                                            del self.active_markets[full_match_id]
                                            self.save_football_backup()
                                            
                                        pending_api_ids.remove(api_match_id)
                            break

    @football_result_checker.before_loop
    async def before_football_result_checker(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # 📜 COMANDOS DOS JOGADORES
    # ==========================================
    @commands.hybrid_command(name="matches", description="Verifica as partidas e corridas disponíveis!")
    @app_commands.describe(sport="Escolhe o desporto que desejas consultar")
    @app_commands.choices(sport=[
        app_commands.Choice(name="🎮 Valorant", value="valorant"),
        app_commands.Choice(name="🏎️ Fórmula 1", value="f1"),
        app_commands.Choice(name="⚽ Futebol", value="football")
    ])
    async def show_matches(self, ctx, sport: app_commands.Choice[str]):
        sport_value = sport.value
        filtered_markets = [(k, v) for k, v in self.active_markets.items() if v['sport'] == sport_value]

        if not filtered_markets:
            return await ctx.send(f"❌ Não há mercados abertos para **{sport.name}** de momento! Pode ser que não existam rondas hoje.")

        view = MatchesPagination(filtered_markets, sport_type=sport_value)
        embed = view.generate_embed()
        
        # Se for menu de opções, enviamos com a view para o Dropdown funcionar
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="bet", description="Faz uma aposta num evento desportivo.")
    async def place_bet(self, ctx, market_id: str, choice: str, amount: int):
        if amount <= 0: return await ctx.send("❌ Precisas de apostar um valor válido!")
        if market_id not in self.active_markets: return await ctx.send("❌ ID inválido. Usa `/matches` para veres os jogos abertos.")
            
        market = self.active_markets[market_id]
        
        try:
            # Trava de Segurança Otimizada para UTC Global
            if 'Z' in market['time']:
                match_time = datetime.strptime(market['time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            else:
                match_time = datetime.strptime(market['time'], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                
            if datetime.now(timezone.utc) >= match_time:
                return await ctx.send("❌ Este evento já teve início! As apostas encontram-se bloqueadas.")
        except Exception as e: 
            print(f"Erro ao converter a hora do jogo: {e}")

        chosen_odd = 0
        real_choice_name = ""

        if market['sport'] == 'football':
            choice_clean = choice.lower()
            if choice_clean in market['home'].lower() or choice_clean == "1" or choice_clean == "casa":
                chosen_odd = market['odds']['home']
                real_choice_name = market['home']
                market['pools']['home'] += amount
            elif choice_clean == "draw" or choice_clean == "x" or choice_clean == "empate":
                chosen_odd = market['odds']['draw']
                real_choice_name = "Draw"
                market['pools']['draw'] += amount
            elif choice_clean in market['away'].lower() or choice_clean == "2" or choice_clean == "fora":
                chosen_odd = market['odds']['away']
                real_choice_name = market['away']
                market['pools']['away'] += amount
            else:
                return await ctx.send(f"❌ Escolha inválida! Seleciona **{market['home']}**, **Empate**, ou **{market['away']}**.")
            
            h, d, a = calculate_3way_dynamic_odds(market['pools']['home'], market['pools']['draw'], market['pools']['away'])
            market['odds']['home'], market['odds']['draw'], market['odds']['away'] = h, d, a
            self.save_football_backup()

        elif market['sport'] == 'f1':
            found = False
            for driver_name in market['drivers'].keys():
                if choice.lower() in driver_name.lower():
                    chosen_odd = market['drivers'][driver_name]['odd']
                    real_choice_name = driver_name
                    market['drivers'][driver_name]['pool'] += amount
                    found = True
                    break
            if not found: return await ctx.send("❌ Piloto não encontrado!")
            pools = {d: data['pool'] for d, data in market['drivers'].items()}
            new_f1_odds = calculate_f1_dynamic_odds(pools)
            for d in market['drivers'].keys(): market['drivers'][d]['odd'] = new_f1_odds[d]
            
        elif market['sport'] == 'valorant':
            if choice.lower() == market['team_a']['name'].lower():
                chosen_odd = market['team_a']['odd']
                real_choice_name = market['team_a']['name']
                market['team_a']['pool'] += amount
            elif choice.lower() == market['team_b']['name'].lower():
                chosen_odd = market['team_b']['odd']
                real_choice_name = market['team_b']['name']
                market['team_b']['pool'] += amount
            else: return await ctx.send("❌ Equipa não encontrada!")
            n_a, n_b = calculate_dynamic_odds(market['team_a']['pool'], market['team_b']['pool'])
            market['team_a']['odd'], market['team_b']['odd'] = n_a, n_b

        async with aiosqlite.connect("banco.db") as db:
            async with db.execute("SELECT bifinhos FROM users WHERE user_id = ?", (ctx.author.id,)) as cursor:
                result = await cursor.fetchone()
            if result is None or result[0] < amount: return await ctx.send(f"❌ Saldo insuficiente! Não possuis **{amount:,} Bifinhos**.")

            await db.execute("UPDATE users SET bifinhos = bifinhos - ? WHERE user_id = ?", (amount, ctx.author.id))
            potential_payout = int(amount * chosen_odd)
            await db.execute("INSERT INTO bets (user_id, match_id, team_bet, stake, payout) VALUES (?, ?, ?, ?, ?)", 
                             (ctx.author.id, market_id, real_choice_name, amount, potential_payout))
            await db.commit()

        embed = discord.Embed(title="🧾 BifesBet: Aposta Confirmada!", color=discord.Color.green())
        embed.add_field(name="Evento", value=market['name'], inline=False)
        embed.add_field(name="A tua Escolha", value=f"**{real_choice_name}**", inline=True)
        embed.add_field(name="Cotação Fixada", value=f"`{chosen_odd}x`", inline=True)
        embed.add_field(name="Valor Apostado", value=f"🥩 {amount:,} Bifinhos", inline=False)
        embed.add_field(name="Retorno Possível", value=f"💰 **{potential_payout:,} Bifinhos**", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="my_bets", description="Consulta o teu histórico de apostas.")
    async def my_bets(self, ctx):
        async with aiosqlite.connect("banco.db") as db:
            async with db.execute("SELECT match_id, team_bet, stake, payout, status FROM bets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (ctx.author.id,)) as cursor:
                bets = await cursor.fetchall()
        if not bets:
            return await ctx.send("❌ Ainda não efetuaste nenhuma aposta!")
            
        embed = discord.Embed(title=f"🧾 Histórico de Apostas: {ctx.author.display_name}", color=discord.Color.blue())
        for match_id, team_bet, stake, payout, status in bets:
            if status == 'pending': status_emoji, result_text = "🟡 **PENDENTE**", f"Retorno Possível: 💰 {payout:,} Bifinhos"
            elif status == 'paid': status_emoji, result_text = "🟢 **GANHO**", f"Lucro: 💰 +{payout:,} Bifinhos"
            else: status_emoji, result_text = "🔴 **PERDA**", f"Prejuízo: 🥩 -{stake:,} Bifinhos"
            
            embed.add_field(name=f"ID: {match_id} | {status_emoji}", value=f"**Escolha:** {team_bet}\n**Aposta:** 🥩 {stake:,}\n{result_text}", inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BifesBetSportsbook(bot))