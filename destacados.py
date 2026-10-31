"""
destacados.py
--------------
Fase 2.5 -- COMBINADAS DEL DIA (reemplaza la seleccion anterior por
"Poder de Match + Estilo de Juego").

A las 6:05am (hora local), de los partidos del dia que SI tienen
seguimiento en vivo disponible (fixture_id ya localizado en ESPN) y que
todavia no empiezan, se descartan los menos probables y con los que
quedan se arman combinadas de 3 partidos.

Por que asi (analisis de 10.053 picks unicos de la hoja Seguimiento,
26-ago a 31-oct 2026):
- El % del favorito de la hoja es lo que mejor separa aciertos de fallos:
  los directos con >=75 % aciertan ~75-85 %, los de 60-70 % solo ~62 %.
  La Confianza (estrellas) y la Prioridad de la hoja aportan muy poco
  una vez filtrado por ese %.
- Las probabilidades calibradas de probabilidad.py predicen bien el
  acierto de una combinada de 3: la esperada (producto de las tres) y la
  real quedaron a 1-2 puntos en el backtest (~50-53 %).
- Aviso honesto: el filtro sube el acierto (de ~37 % a ~50 % por
  combinada) pero las cuotas de picks seguros pagan poco (~1.7-1.9 por
  combinada), asi que el retorno con apuesta plana quedo entre -12 % y
  0 % en el backtest. Mejora la tasa de acierto, no garantiza ganancia.

Reglas:
1. Candidatos: tienen fixture_id, no han empezado, y traen probabilidad
   calibrada (p_gana_fav / p_no_pierde_fav).
2. Filtro: favorito directo con % de la hoja >= UMBRAL_DIRECTO_COMBINADA;
   doble oportunidad con % del lado elegido >= UMBRAL_DC_COMBINADA.
3. Cantidad: siempre multiplo de 3, hasta MAX_PARTIDOS (9). Si los que
   cumplen el filtro no son multiplo de 3, se completan con los MAS
   PROBABLES de los que no lo cumplieron (marcados como "relleno"). Si
   ninguno cumple el filtro, no se arma combinada. Si cumplen mas de 9,
   se quedan los 9 mas probables.
4. Combinadas AL AZAR: los partidos elegidos se revuelven y se reparten
   de 3 en 3 (Combinada 1, 2, 3...), sin ordenar por probabilidad.

Cada partido elegido queda marcado en partidos_hoy.json con
"es_destacado": True y "grupo_destacado": N (numero de combinada), mas
"combinada_pick" con el mercado, la probabilidad y la cuota estimada,
para poder medir despues cuantas combinadas acertaron.

Reintenta cada 5 min dentro de una ventana corta y se autoprotege con
estado_diario ("destacados") para no repetir el envio si ya se hizo hoy
-- salvo que se llame con --forzar (util para pruebas manuales).
"""

import json
import random
import sys
import datetime
from pathlib import Path

from telegram_utils import enviar_mensaje_telegram, escapar_html
from estado_diario import ya_se_hizo, marcar_hecho

ARCHIVO = Path(__file__).parent / "data" / "partidos_hoy.json"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))

EMOJI_TIPO_PRONOSTICO = {
    "favorito_directo": "\U0001F3AF",   # 🎯
    "doble_oportunidad": "\U0001F500",  # 🔀
}
CORONA_FAVORITO = "\U0001F451"  # 👑

# --- Parametros (ajustables) ---
PARTIDOS_POR_COMBINADA = 3
MAX_PARTIDOS = 9                   # 9 partidos = hasta 3 combinadas de 3
UMBRAL_DIRECTO_COMBINADA = 0.75    # % de la hoja del favorito directo
UMBRAL_DC_COMBINADA = 0.55         # % de la hoja del lado de la doble oportunidad


def _hora_local(hora_inicio_utc_iso):
    if not hora_inicio_utc_iso:
        return "?"
    try:
        dt_utc = datetime.datetime.fromisoformat(hora_inicio_utc_iso.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(ZONA_HORARIA_LOCAL)
        return dt_local.strftime("%H:%M")
    except Exception:
        return hora_inicio_utc_iso


def _inicio_utc(partido):
    texto = partido.get("hora_inicio") or partido.get("kickoff_utc")
    if not texto:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _es_dc(partido):
    return partido.get("tipo_pronostico") == "doble_oportunidad"


def _p_exito(partido):
    """Probabilidad calibrada de que el pick se cumpla: gana el favorito
    (directo) o no pierde (doble oportunidad). None si falta el dato."""
    clave = "p_no_pierde_fav" if _es_dc(partido) else "p_gana_fav"
    valor = partido.get(clave)
    return float(valor) if valor is not None else None


def _cuota_pick(partido):
    """Cuota estimada del pick. Directo: cuota del favorito. DC: se
    deriva de las cuotas 1X2 (aproximada, no es la cuota DC publicada)."""
    c_fav = partido.get("cuota_local_inicial") if partido.get("favorito_es_local") \
        else partido.get("cuota_visitante_inicial")
    if not c_fav or c_fav <= 1:
        return None
    if not _es_dc(partido):
        return float(c_fav)
    c_x = partido.get("cuota_empate_inicial")
    if not c_x or c_x <= 1:
        return None
    return 1.0 / (1.0 / c_fav + 1.0 / c_x)


def _pasa_filtro(partido, ahora_utc):
    if not partido.get("fixture_id"):
        return False
    inicio = _inicio_utc(partido)
    if inicio is not None and inicio <= ahora_utc:
        return False                      # ya empezo o termino
    pf = partido.get("pf_hoja")
    if pf is None or _p_exito(partido) is None:
        return False
    umbral = UMBRAL_DC_COMBINADA if _es_dc(partido) else UMBRAL_DIRECTO_COMBINADA
    return pf >= umbral


def _es_elegible(partido, ahora_utc):
    """Puede entrar a una combinada (aunque no cumpla el filtro de %)."""
    if not partido.get("fixture_id"):
        return False
    inicio = _inicio_utc(partido)
    if inicio is not None and inicio <= ahora_utc:
        return False                      # ya empezo o termino
    return partido.get("pf_hoja") is not None and _p_exito(partido) is not None


def _pasa_filtro(partido, ahora_utc):
    if not _es_elegible(partido, ahora_utc):
        return False
    umbral = UMBRAL_DC_COMBINADA if _es_dc(partido) else UMBRAL_DIRECTO_COMBINADA
    return partido["pf_hoja"] >= umbral


def _por_probabilidad(partidos, ahora_utc):
    return sorted(partidos, key=lambda p: (-_p_exito(p), -p["pf_hoja"], _inicio_utc(p) or ahora_utc))


def armar_combinadas(partidos, ahora_utc=None, rng=None):
    """Devuelve (combinadas, elegidos, n_cumplen, rellenos).

    - n_cumplen: cuantos partidos cumplen el filtro.
    - elegidos: lista plana de partidos elegidos (multiplo de 3, max 9),
      en el orden en que quedaron repartidos.
    - rellenos: ids de fixture de los que NO cumplian el filtro y entraron
      para completar el multiplo de 3 (los mas probables de los restantes).
    - combinadas: lista de listas de 3, repartidas AL AZAR.
    No modifica los partidos."""
    ahora_utc = ahora_utc or datetime.datetime.now(datetime.timezone.utc)
    rng = rng or random.Random()

    elegibles = [p for p in partidos if _es_elegible(p, ahora_utc)]
    cumplen = _por_probabilidad([p for p in elegibles if _pasa_filtro(p, ahora_utc)], ahora_utc)
    resto = _por_probabilidad([p for p in elegibles if not _pasa_filtro(p, ahora_utc)], ahora_utc)

    if not cumplen:
        return [], [], 0, []

    # Siguiente multiplo de 3, con tope MAX_PARTIDOS
    objetivo = -(-len(cumplen) // PARTIDOS_POR_COMBINADA) * PARTIDOS_POR_COMBINADA
    objetivo = min(objetivo, MAX_PARTIDOS)

    elegidos = cumplen[:objetivo]
    faltan = objetivo - len(elegidos)
    rellenos = resto[:faltan] if faltan > 0 else []
    if len(elegidos) + len(rellenos) < objetivo:
        # No alcanzan los partidos elegibles para completar: baja al multiplo de 3 anterior
        total = len(elegidos) + len(rellenos)
        recorte = total - total % PARTIDOS_POR_COMBINADA
        todos = elegidos + rellenos
        elegidos, rellenos = todos[:recorte], [p for p in todos[:recorte] if p in rellenos]
        if recorte == 0:
            return [], [], len(cumplen), []
    else:
        elegidos = elegidos + rellenos

    # AL AZAR: se revuelven todos y se reparten de 3 en 3
    revueltos = list(elegidos)
    rng.shuffle(revueltos)
    combinadas = [revueltos[i:i + PARTIDOS_POR_COMBINADA]
                  for i in range(0, len(revueltos), PARTIDOS_POR_COMBINADA)]
    ids_relleno = [p.get("fixture_id") for p in rellenos]
    return combinadas, revueltos, len(cumplen), ids_relleno


def elegir_destacados(partidos, ahora_utc=None, rng=None):
    """Marca en los partidos (in place) a los elegidos y devuelve
    (combinadas, elegidos, n_cumplen, ids_relleno)."""
    for p in partidos:
        p.pop("es_destacado", None)
        p.pop("grupo_destacado", None)
        p.pop("combinada_pick", None)

    combinadas, elegidos, n_cumplen, ids_relleno = armar_combinadas(partidos, ahora_utc, rng)
    for numero, grupo in enumerate(combinadas, start=1):
        for p in grupo:
            cuota = _cuota_pick(p)
            p["es_destacado"] = True
            p["grupo_destacado"] = numero
            p["combinada_pick"] = {
                "mercado": "doble_oportunidad" if _es_dc(p) else "gana_favorito",
                "favorito": p.get("favorito"),
                "p_exito": _p_exito(p),
                "cuota_estimada": round(cuota, 2) if cuota else None,
                "relleno": p.get("fixture_id") in ids_relleno,
            }
    return combinadas, elegidos, n_cumplen, ids_relleno


def _linea_pick(indice, p, relleno=False):
    emoji = EMOJI_TIPO_PRONOSTICO.get(p.get("tipo_pronostico"), EMOJI_TIPO_PRONOSTICO["favorito_directo"])
    accion = "gana o empata" if _es_dc(p) else "gana"
    cuota = _cuota_pick(p)
    extra = f" · cuota ~{cuota:.2f}" if cuota else ""
    if relleno:
        extra += " · relleno"
    return (f"{indice}. {emoji}{CORONA_FAVORITO} <b>{escapar_html(p['favorito'])}</b> {accion}\n"
            f"    {escapar_html(p['local'])} vs {escapar_html(p['visitante'])} "
            f"· {_hora_local(p.get('hora_inicio'))} · prob. {_p_exito(p) * 100:.0f}%{extra}")


def _resumen_combinada(grupo):
    prob = 1.0
    cuota = 1.0
    cuota_completa = True
    for p in grupo:
        prob *= _p_exito(p)
        c = _cuota_pick(p)
        if c:
            cuota *= c
        else:
            cuota_completa = False
    texto = f"Prob. de que acierte la combinada: <b>{prob * 100:.0f}%</b>"
    if cuota_completa:
        texto += f" · Cuota total ~<b>{cuota:.2f}</b>"
    return texto


def enviar_destacados(forzar=False):
    if not forzar and ya_se_hizo("destacados"):
        print("Las combinadas de hoy ya se enviaron antes. Nada que hacer.")
        return

    if not ARCHIVO.exists():
        print("Fase 1 todavia no ha generado partidos_hoy.json. Se reintentara en el proximo ciclo.")
        return

    datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    partidos = datos.get("partidos", [])

    combinadas, elegidos, n_cumplen, ids_relleno = elegir_destacados(partidos)

    if not combinadas:
        exito = enviar_mensaje_telegram(
            "\U0001F3B2 Hoy ningun partido cumple el filtro de probabilidad para armar combinadas "
            f"(cumplen: {n_cumplen})."
        )
        if exito:
            ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
            marcar_hecho("destacados")
        print("Combinadas: ningun partido cumple el filtro." if exito else "Fallo el envio de combinadas.")
        return

    lineas = ["\U0001F3B2 <b>Combinadas de hoy</b>",
              f"<i>{len(elegidos)} partidos repartidos al azar en {len(combinadas)} combinada(s) de "
              f"{PARTIDOS_POR_COMBINADA}.</i>"]
    for numero, grupo in enumerate(combinadas, start=1):
        lineas.append("\n" + "=" * 35)
        lineas.append(f"<b>Combinada {numero}</b>")
        lineas.append("=" * 35)
        for i, p in enumerate(grupo, start=1):
            lineas.append(_linea_pick(i, p, relleno=p.get("fixture_id") in ids_relleno))
        lineas.append(_resumen_combinada(grupo))
    if ids_relleno:
        lineas.append("\n<i>\"Relleno\": no cumplia el filtro, se agrego para completar el grupo de 3.</i>")
    lineas.append("<i>Cuotas de doble oportunidad aproximadas (derivadas de las cuotas 1X2).</i>")

    exito = enviar_mensaje_telegram("\n".join(lineas))
    if exito:
        ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        marcar_hecho("destacados")
    print(f"Combinadas enviadas: {len(combinadas)} combinada(s), {len(elegidos)} partido(s)."
          if exito else "Fallo el envio de combinadas.")


if __name__ == "__main__":
    enviar_destacados(forzar="--forzar" in sys.argv)
