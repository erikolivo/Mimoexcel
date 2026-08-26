"""
cuotas_reales.py
------------------
Fuente SECUNDARIA de cuota real (The Odds API), llamada desde
seleccionar_partidos.py DESPUES de intentar primero con las cuotas de
DraftKings embebidas en ESPN (gratis, sin cupo). Este modulo solo llena
huecos que ESPN no cubrio.

CAMBIOS (agosto 2026): (1) la probabilidad ahora se calcula quitando el
margen de la casa de apuestas -- ver _favorito_desde_evento(). (2)
_favorito_desde_evento() y obtener_favoritos_cuota_real() ahora
devuelven la cuota/probabilidad de AMBOS lados (local y visitante), no
solo del favorito, para que seleccionar_partidos.py pueda mostrar la
comparacion completa en el resumen de Telegram.

Filosofia (igual que siempre): nunca gastar una peticion si se puede
evitar. Solo se consultan ligas que tienen partidos hoy, se valida el
sport_key contra deportes activos antes de gastar una peticion real, y
hay tope diario + margen de seguridad en el cupo mensual.
"""

from fetch_data import obtener_deportes_odds_api, obtener_cuotas_liga, buscar_equipo_similar, ODDS_API_KEY
from mapeo_ligas_odds_api import sport_key_para
import cuota_odds_api

TOPE_LIGAS_POR_DIA = 20
UMBRAL_FAVORITO_CUOTA_REAL = 0.65  # alineado con PROB_MINIMA_FAVORITO tras el cambio de umbral (agosto 2026)


def _favorito_desde_evento(evento):
    """
    CORREGIDO (agosto 2026): antes calculaba la probabilidad como
    1/cuota directo, sin quitar el margen de la casa de apuestas (el
    "overround") -- eso infla artificialmente la probabilidad de
    CUALQUIER resultado, porque las 3 probabilidades implicitas (local+
    empate+visitante) siempre suman MAS de 100% en una cuota real (ese
    excedente es la ganancia de la casa). Con una cuota de 1.50, por
    ejemplo, el metodo viejo daba 66.7% cuando la probabilidad real de
    mercado (quitando el margen) es mas cercana a 63%. Esto podia colar
    a la lista de favoritos un equipo que el umbral del 65% deberia
    haber rechazado.

    Ahora se normaliza dividiendo entre la suma de las probabilidades
    implicitas de los 3 resultados (de-vig) -- MISMA metodologia que ya
    usaba fetch_data.extraer_favorito_odds_espn() para las cuotas de
    DraftKings, para que las dos fuentes de cuota real midan con la
    misma vara.
    """
    bookmakers = evento.get("bookmakers", [])
    if not bookmakers:
        return None

    bk = bookmakers[0]
    mercado_h2h = next((m for m in bk.get("markets", []) if m.get("key") == "h2h"), None)
    if not mercado_h2h:
        return None

    precios = {o["name"]: o["price"] for o in mercado_h2h.get("outcomes", [])}
    home_team = evento.get("home_team")
    away_team = evento.get("away_team")
    cuota_home = precios.get(home_team)
    cuota_away = precios.get(away_team)
    if not cuota_home or not cuota_away:
        return None

    p_home = 1 / cuota_home
    p_away = 1 / cuota_away
    p_draw = 0.0
    cuota_draw = precios.get("Draw")
    if cuota_draw:
        p_draw = 1 / cuota_draw

    total = p_home + p_away + p_draw
    if total <= 0:
        return None
    p_home_norm = p_home / total
    p_away_norm = p_away / total

    if p_home_norm >= p_away_norm:
        lado_favorito, prob_favorito = "local", p_home_norm
    else:
        lado_favorito, prob_favorito = "visitante", p_away_norm

    cuota_local = round(1 / p_home_norm, 2) if p_home_norm > 0 else None
    cuota_visitante = round(1 / p_away_norm, 2) if p_away_norm > 0 else None

    return {
        "lado_favorito": lado_favorito,
        "probabilidad_favorito": round(prob_favorito, 4),
        "probabilidad_local": round(p_home_norm, 4),
        "probabilidad_visitante": round(p_away_norm, 4),
        "cuota_local": cuota_local,
        "cuota_visitante": cuota_visitante,
        "casa_apuestas": bk.get("title", "?"),
    }


def obtener_favoritos_cuota_real(fixtures_api):
    if not ODDS_API_KEY:
        return {}

    if not cuota_odds_api.hay_cupo_suficiente():
        print("[AVISO] Cupo de The Odds API insuficiente este mes, se omite la verificacion por cuota real.")
        return {}

    ligas_hoy = {}
    for f in fixtures_api:
        pais = f.get("league", {}).get("country", "")
        liga = f.get("league", {}).get("name", "")
        ligas_hoy.setdefault((pais, liga), []).append(f)

    deportes_activos = obtener_deportes_odds_api()

    resultado = {}
    ligas_consultadas = 0

    for (pais, liga), fixtures_de_la_liga in ligas_hoy.items():
        if ligas_consultadas >= TOPE_LIGAS_POR_DIA:
            print(f"[INFO] Tope diario de {TOPE_LIGAS_POR_DIA} ligas para The Odds API alcanzado.")
            break
        if not cuota_odds_api.hay_cupo_suficiente():
            print("[AVISO] Cupo de The Odds API se agoto durante esta corrida, se detiene aqui.")
            break

        sport_key = sport_key_para(pais, liga, deportes_activos)
        if not sport_key:
            continue

        try:
            eventos = obtener_cuotas_liga(sport_key)
        except Exception as e:
            print(f"[AVISO] No se pudo obtener cuotas de {pais} - {liga} ({sport_key}): {e}")
            continue
        ligas_consultadas += 1

        nombres_fixtures_liga = {}
        for f in fixtures_de_la_liga:
            nombres_fixtures_liga[f["teams"]["home"]["name"]] = f
            nombres_fixtures_liga[f["teams"]["away"]["name"]] = f

        for evento in eventos:
            favorito = _favorito_desde_evento(evento)
            if not favorito or favorito["probabilidad_favorito"] < UMBRAL_FAVORITO_CUOTA_REAL:
                continue

            home_odds = evento.get("home_team", "")
            away_odds = evento.get("away_team", "")
            match_home = buscar_equipo_similar(home_odds, list(nombres_fixtures_liga.keys()), n=1, corte=0.75)
            match_away = buscar_equipo_similar(away_odds, list(nombres_fixtures_liga.keys()), n=1, corte=0.75)
            fixture = None
            if match_home:
                fixture = nombres_fixtures_liga[match_home[0]]
            elif match_away:
                fixture = nombres_fixtures_liga[match_away[0]]
            if not fixture:
                continue

            resultado[fixture["fixture"]["id"]] = favorito

    print(f"Cuotas reales (The Odds API): {ligas_consultadas} liga(s) consultada(s), "
          f"{len(resultado)} favorito(s) claro(s) detectado(s).")
    return resultado
