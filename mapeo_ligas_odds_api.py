"""
mapeo_ligas_odds_api.py
-------------------------
SIN CAMBIOS -- The Odds API se mantiene como fuente SECUNDARIA/respaldo
tras la migracion a ESPN (la primaria ahora es la cuota de DraftKings
embebida en ESPN, ver fetch_data.extraer_favorito_odds_espn). Este
mapeo solo se consulta para llenar huecos que ESPN no cubrio.
"""

import difflib

MAPEO_LIGA_A_SPORT_KEY = {
    ("England", "Premier League"): "soccer_epl",
    ("England", "Championship"): "soccer_efl_champ",
    ("Spain", "La Liga"): "soccer_spain_la_liga",
    ("Italy", "Serie A"): "soccer_italy_serie_a",
    ("Germany", "Bundesliga"): "soccer_germany_bundesliga",
    ("Germany", "2. Bundesliga"): "soccer_germany_bundesliga2",
    ("France", "Ligue 1"): "soccer_france_ligue_one",
    ("Netherlands", "Eredivisie"): "soccer_netherlands_eredivisie",
    ("Portugal", "Primeira Liga"): "soccer_portugal_primeira_liga",
    ("Belgium", "Jupiler Pro League"): "soccer_belgium_first_div",
    ("Turkey", "Super Lig"): "soccer_turkey_super_league",
    ("Greece", "Super League 1"): "soccer_greece_super_league",
    ("Brazil", "Campeonato Brasileiro"): "soccer_brazil_campeonato",
    ("Argentina", "Liga Profesional Argentina"): "soccer_argentina_primera_division",
    ("Mexico", "Liga MX"): "soccer_mexico_ligamx",
    ("USA", "Major League Soccer"): "soccer_usa_mls",
    ("World", "UEFA Champions League"): "soccer_uefa_champs_league",
    ("World", "UEFA Europa League"): "soccer_uefa_europa_league",
    ("Colombia", "Primera A"): "soccer_colombia_primera_a",
    ("Chile", "Primera Division"): "soccer_chile_campeonato",
    ("Uruguay", "Primera Division"): "soccer_uruguay_primera_division",
}


def sport_key_para(pais, liga_nombre, deportes_activos=None, corte=0.7):
    candidatas = {liga: key for (p, liga), key in MAPEO_LIGA_A_SPORT_KEY.items() if p == pais}
    if not candidatas:
        return None

    match = difflib.get_close_matches(liga_nombre, list(candidatas.keys()), n=1, cutoff=corte)
    if not match:
        return None

    key = candidatas[match[0]]
    if deportes_activos is not None and key not in deportes_activos:
        return None
    return key
