"""
resumen.py
----------
FASE 2. AJUSTADO a pedido explicito (agosto 2026):
  - Estrella (fav ⭐) junto al nombre del favorito, igual que en las
    alertas en vivo de monitor.py.
  - Se muestran las cuotas de AMBOS lados (favorito y no favorito) del
    modelo propio, siempre. Cuando ademas hay cuota real (DraftKings
    via ESPN o el respaldo de The Odds API), se agrega una segunda
    linea con la cuota real de los dos lados, para poder comparar.
  - NUEVO: Poder de Match y Estilo de Juego para cada equipo.
"""

import json
import datetime
import difflib
import sys
from pathlib import Path

from telegram_utils import enviar_mensaje_telegram, escapar_html
from estado_diario import ya_se_hizo, marcar_hecho
from fetch_data import obtener_historial_equipo, obtener_resultados_liga

ARCHIVO = Path(__file__).parent / "data" / "partidos_hoy.json"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))

# Mismo esquema de emojis que monitor.py (Fase 3), a pedido explicito.
EMOJI_TIPO_PRONOSTICO = {
    "favorito_directo": "\U0001F3AF",   # 🎯
    "doble_oportunidad": "\U0001F500",  # 🔀
}
CORONA_FAVORITO = "\U0001F451"  # 👑

# Estilos de juego segun football-data.co.uk
ESTILO_OFENSIVO = "\u2694\uFE0F Ofensivo"
ESTILO_DEFENSIVO = "\U0001F6E1\uFE0F Defensivo"
ESTILO_EQUILIBRADO = "\u2696\uFE0F Equilibrado"
ESTILO_PRESION_ALTA = "\U0001F525 Presión Alta"
ESTILO_JUEGO_SUCIO = "\u2660\uFE0F Juego Sucio"
ESTILO_GOLEADOR_TEMPRANO = "\U0001F305 Goleador Temprano"

# Mapeo de liga_slug (ESPN) a codigo (football-data.co.uk)
MAPA_LIGA_SLUG_A_CODIGO = {
    "eng.1": "E0", "eng.2": "E1",
    "esp.1": "SP1", "esp.2": "SP2",
    "ita.1": "I1", "ita.2": "I2",
    "ger.1": "D1", "ger.2": "D2",
    "fra.1": "F1", "fra.2": "F2",
    "ned.1": "N1",
    "por.1": "P1",
    "bel.1": "B1",
    "tur.1": "T1",
    "gre.1": "G1",
    "sco.1": "SC0",
}


def _calcular_estilo_juego(datos_historial):
    """
    Calcula el estilo de juego basado en estadisticas de football-data.co.uk
    datos_historial: lista de dicts con tiros, corners, faltas, etc.
    """
    if not datos_historial or len(datos_historial) < 3:
        return None, None
    
    # Calcular promedios
    tiros_totales = sum(d.get('tiros_totales', 0) for d in datos_historial) / len(datos_historial)
    tiros_puerta = sum(d.get('tiros_puerta', 0) for d in datos_historial) / len(datos_historial)
    corners = sum(d.get('corners', 0) for d in datos_historial) / len(datos_historial)
    faltas = sum(d.get('faltas', 0) for d in datos_historial) / len(datos_historial)
    amarillas = sum(d.get('amarillas', 0) for d in datos_historial) / len(datos_historial)
    goles_1t = sum(d.get('goles_1t', 0) for d in datos_historial) / len(datos_historial)
    
    # Determinar estilo principal
    estilo = ESTILO_EQUILIBRADO
    confianza = 0.5
    
    if tiros_totales >= 14 and corners >= 6:
        estilo = ESTILO_OFENSIVO
        confianza = 0.8
    elif tiros_totales <= 8 and faltas >= 12:
        estilo = ESTILO_DEFENSIVO
        confianza = 0.7
    elif faltas >= 14 or amarillas >= 3:
        estilo = ESTILO_JUEGO_SUCIO
        confianza = 0.75
    elif tiros_totales >= 12 and corners >= 5:
        estilo = ESTILO_PRESION_ALTA
        confianza = 0.7
    elif goles_1t >= 1.2:
        estilo = ESTILO_GOLEADOR_TEMPRANO
        confianza = 0.65
    
    return estilo, confianza


# Cache en memoria por proceso: codigo de liga -> filas del CSV.
# El CSV de una liga es igual para todos sus equipos, asi que se
# descarga una sola vez por corrida del proceso.
_CSV_LIGA = {}


def _resultados_liga_cache(codigo):
    """Filas del CSV de una liga, descargadas como mucho una vez."""
    if codigo not in _CSV_LIGA:
        _CSV_LIGA[codigo] = obtener_resultados_liga(codigo)
    return _CSV_LIGA[codigo]


def _num(x):
    """Celda CSV como flotante; vacio o invalido = 0.0."""
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return 0.0


def _tiene_valor(x):
    """True si la celda no esta vacia (el 0 cuenta como valor)."""
    if x is None:
        return False
    return str(x).strip() != ""


def _emparejar_nombre(equipo, nombres):
    """Nombre del equipo (ESPN) mas parecido al de football-data
    (corte 0.72). Si no hay coincidencia clara devuelve None: mejor
    no mostrar estilo que mostrar el de otro equipo."""
    if not equipo or not nombres:
        return None
    if equipo in nombres:
        return equipo
    coincidencias = difflib.get_close_matches(equipo, nombres, n=1, cutoff=0.72)
    if coincidencias:
        return coincidencias[0]
    print(f"[AVISO] No se pudo emparejar '{equipo}' con los equipos de football-data")
    return None


def _obtener_datos_estilo(equipo, liga_slug):
    """
    Ultimas 6 filas de estilo del equipo en football-data.co.uk.

    Usa las columnas reales del CSV (HomeTeam/AwayTeam, no
    local/visitante), empareja el nombre del equipo por similitud y
    solo toma partidos con marcador final completo. Si el nombre no se
    empareja, devuelve None (preferible a estilo de otro equipo).
    """
    try:
        if liga_slug not in MAPA_LIGA_SLUG_A_CODIGO:
            return None

        codigo_liga = MAPA_LIGA_SLUG_A_CODIGO[liga_slug]
        resultados = _resultados_liga_cache(codigo_liga)
        if not resultados:
            return None

        nombres = sorted({f.get("HomeTeam") for f in resultados if f.get("HomeTeam")} |
                         {f.get("AwayTeam") for f in resultados if f.get("AwayTeam")})
        nombre = _emparejar_nombre(equipo, nombres)
        if nombre is None:
            return None

        filas = [f for f in resultados
                 if f.get("HomeTeam") == nombre or f.get("AwayTeam") == nombre]
        filas = [f for f in filas
                 if _tiene_valor(f.get("FTHG")) and _tiene_valor(f.get("FTAG"))]
        filas = filas[-6:]

        datos_equipo = []
        for f in filas:
            de_casa = f.get("HomeTeam") == nombre
            datos_equipo.append({
                "tiros_totales": _num(f.get("HS" if de_casa else "AS")),
                "tiros_puerta": _num(f.get("HST" if de_casa else "AST")),
                "corners": _num(f.get("HC" if de_casa else "AC")),
                "faltas": _num(f.get("HF" if de_casa else "AF")),
                "amarillas": _num(f.get("HY" if de_casa else "AY")),
                "goles_1t": _num(f.get("HTHG" if de_casa else "HTAG")),
            })

        return datos_equipo if datos_equipo else None
    except Exception:
        return None


PUNTOS = {"V": 3, "E": 1, "D": 0}
DECAIMIENTO_FORMA = 0.85
VENTANA_NIVEL = 6
MIN_PARTIDOS_NIVEL = 4


def _pesos_recencia(n):
    """Peso de cada partido segun recencia: el mas reciente pesa 1.0
    (el mas antiguo, 0.85 ** (n-1))."""
    return [DECAIMIENTO_FORMA ** (n - 1 - i) for i in range(n)]


def _forma_0_100(partidos):
    """Puntos ponderados (V=3, E=1, D=0) sobre el maximo posible."""
    if not partidos:
        return 0.0
    pesos = _pesos_recencia(len(partidos))
    pts = sum(PUNTOS.get(p["resultado"], 0) * w for p, w in zip(partidos, pesos))
    return pts / (sum(pesos) * 3) * 100


def _goles_0_100(partidos):
    """Diferencia de goles ponderada por recencia, en escala 0-100."""
    if not partidos:
        return 50.0
    pesos = _pesos_recencia(len(partidos))
    sw = sum(pesos)
    gf = sum(p["goles_favor"] * w for p, w in zip(partidos, pesos)) / sw
    gc = sum(p["goles_contra"] * w for p, w in zip(partidos, pesos)) / sw
    return max(0.0, min(100.0, 50 + (gf - gc) * 20))


def _score_mixto(partidos):
    """70% forma + 30% goles, misma escala 0-100 para todos."""
    return 0.70 * _forma_0_100(partidos) + 0.30 * _goles_0_100(partidos)


def _calcular_nivel_actual(historial_equipo, es_local):
    """
    Calcula el Nivel Actual (0-10) con 3 componentes en escala 0-100:
    1. Forma global: puntos ponderados con decaimiento 0.85 (el mas
       reciente pesa 1.0) sobre la ventana de 6 partidos.
    2. Goles global: diferencia GF-GC con los MISMOS pesos de recencia.
    3. Sede: 70% forma + 30% goles de los ultimos 6 partidos de esa
       sede (si hay menos de 2, usa el equivalente global).
    Combinacion: 40% forma global + 40% sede + 20% goles global,
    dividido entre 10 y acotado a 0-10.
    Retorna (poder, color, n_partidos) o (None, None, 0) si no hay datos.
    El historial se ordena por (fecha, id) por si llega desordenado.
    """
    if not historial_equipo or len(historial_equipo) < MIN_PARTIDOS_NIVEL:
        return None, None, 0

    ordenado = sorted(historial_equipo,
                      key=lambda p: (p.get("fecha", ""), str(p.get("id") or "")))
    ventana = ordenado[-VENTANA_NIVEL:]
    n = len(ventana)

    forma_global = _forma_0_100(ventana)
    goles_global = _goles_0_100(ventana)

    sede_partidos = [p for p in ordenado if p.get("es_local") == es_local][-VENTANA_NIVEL:]
    if len(sede_partidos) >= 2:
        sede = _score_mixto(sede_partidos)
    else:
        sede = _score_mixto(ventana)

    poder = (0.40 * forma_global + 0.40 * sede + 0.20 * goles_global) / 10
    poder = max(0.0, min(10.0, poder))

    if poder >= 8:
        color = "🔵"
    elif poder >= 6:
        color = "🟢"
    elif poder >= 4:
        color = "🟡"
    else:
        color = "🔴"

    return poder, color, n


def _hora_local(hora_inicio_utc_iso):
    if not hora_inicio_utc_iso:
        return "?"
    try:
        dt_utc = datetime.datetime.fromisoformat(hora_inicio_utc_iso.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(ZONA_HORARIA_LOCAL)
        return dt_local.strftime("%H:%M")
    except Exception:
        return hora_inicio_utc_iso


def enviar_resumen(forzar=False):
    """forzar=True (a pedido explicito, agosto 2026) ignora ya_se_hizo()
    -- util para probar el mensaje manualmente sin esperar al dia
    siguiente. Vuelve a mandar el mismo resumen de hoy si ya se habia
    enviado antes; no borra ni duplica nada en partidos_hoy.json, solo
    reenviar el mensaje a Telegram."""
    if not forzar and ya_se_hizo("resumen"):
        print("El resumen de hoy ya se envio antes. Nada que hacer.")
        return

    if not ARCHIVO.exists():
        print("Fase 1 todavia no ha generado partidos_hoy.json. Se reintentara en el proximo ciclo.")
        return

    datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    partidos = datos.get("partidos", [])

    if not partidos:
        exito = enviar_mensaje_telegram(
            "\U0001F4CB Hoy no hay favoritos de Google Sheets que se hayan podido localizar en ESPN."
        )
        if exito:
            marcar_hecho("resumen")
        print("Resumen enviado: 0 partidos hoy." if exito else "Fallo el envio del resumen.")
        return

    lineas = [f"\U0001F4CB <b>{len(partidos)} favorito(s) de la hoja ({datos.get('fecha','')})</b> (horas en tu horario local)"]

    for p in partidos:
        hora = _hora_local(p.get("hora_inicio"))
        estado = "\u2705" if p["fixture_id"] else "\u26A0\uFE0F sin vigilancia en vivo"
        emoji_tipo = EMOJI_TIPO_PRONOSTICO.get(p.get("tipo_pronostico"), EMOJI_TIPO_PRONOSTICO["favorito_directo"])
        marca_favorito = f" {emoji_tipo}{CORONA_FAVORITO}"
        corona_local = marca_favorito if p.get("favorito_es_local") else ""
        corona_visitante = marca_favorito if not p.get("favorito_es_local") else ""
        
        # Separador visual
        lineas.append("\n" + "=" * 35)
        
        # Hora y partido
        lineas.append(f"{hora} \u26BD {escapar_html(p['local'])}{corona_local} vs {escapar_html(p['visitante'])}{corona_visitante}")
        
        # Cuotas
        cuota_l = p.get("cuota_local_inicial")
        cuota_x = p.get("cuota_empate_inicial")
        cuota_v = p.get("cuota_visitante_inicial")
        if cuota_l or cuota_v:
            partes_cuota = [f"{cuota_l}" if cuota_l else None,
                             f"{cuota_x}" if cuota_x else None,
                             f"{cuota_v}" if cuota_v else None]
            lineas.append("Cuota: " + " | ".join(c for c in partes_cuota if c))
        
        # Poder de Match
        home_id = p.get('home_id')
        away_id = p.get('away_id')
        liga_slug = p.get('liga_slug')
        
        if home_id and away_id:
            try:
                historial_local = obtener_historial_equipo(home_id, liga_slug)
                historial_visitante = obtener_historial_equipo(away_id, liga_slug)
                
                poder_local, color_local, n_local = _calcular_nivel_actual(historial_local, True)
                poder_visitante, color_visitante, n_visitante = _calcular_nivel_actual(historial_visitante, False)
                
                if poder_local is not None or poder_visitante is not None:
                    if poder_local is not None:
                        marca_n = f" ({n_local})" if n_local < 5 else ""
                        ventana = historial_local[-6:] if len(historial_local) >= 6 else historial_local
                        gf_local = sum(p['goles_favor'] for p in ventana)
                        gc_local = sum(p['goles_contra'] for p in ventana)
                        lineas.append(f"{color_local} {escapar_html(p['local'])}: {poder_local:.1f}{marca_n} (GF:{gf_local} GC:{gc_local})")
                    if poder_visitante is not None:
                        marca_n = f" ({n_visitante})" if n_visitante < 5 else ""
                        ventana = historial_visitante[-6:] if len(historial_visitante) >= 6 else historial_visitante
                        gf_visitante = sum(p['goles_favor'] for p in ventana)
                        gc_visitante = sum(p['goles_contra'] for p in ventana)
                        lineas.append(f"{color_visitante} {escapar_html(p['visitante'])}: {poder_visitante:.1f}{marca_n} (GF:{gf_visitante} GC:{gc_visitante})")
                    
                    # Ultimos resultados
                    ultimos_local = historial_local[-6:] if len(historial_local) >= 6 else historial_local
                    ultimos_visitante = historial_visitante[-6:] if len(historial_visitante) >= 6 else historial_visitante
                    
                    resultados_local = ""
                    for r in ultimos_local:
                        if r['resultado'] == 'V':
                            resultados_local += "✅"
                        elif r['resultado'] == 'E':
                            resultados_local += "🟡"
                        else:
                            resultados_local += "❌"
                    
                    resultados_visitante = ""
                    for r in ultimos_visitante:
                        if r['resultado'] == 'V':
                            resultados_visitante += "✅"
                        elif r['resultado'] == 'E':
                            resultados_visitante += "🟡"
                        else:
                            resultados_visitante += "❌"
                    
                    if resultados_local:
                        lineas.append(f"  {escapar_html(p['local'])}: {resultados_local}")
                    if resultados_visitante:
                        lineas.append(f"  {escapar_html(p['visitante'])}: {resultados_visitante}")
            except Exception:
                pass
        
        # Estilo de Juego (solo si esta disponible en football-data.co.uk)
        if liga_slug:
            try:
                datos_estilo_local = _obtener_datos_estilo(p['local'], liga_slug)
                datos_estilo_visitante = _obtener_datos_estilo(p['visitante'], liga_slug)
                
                estilo_local, _ = _calcular_estilo_juego(datos_estilo_local)
                estilo_visitante, _ = _calcular_estilo_juego(datos_estilo_visitante)
                
                if estilo_local and estilo_visitante:
                    lineas.append(f"{estilo_local} vs {estilo_visitante}")
            except Exception:
                pass
        
        lineas.append("=" * 35)

    exito = enviar_mensaje_telegram("\n".join(lineas))
    if exito:
        marcar_hecho("resumen")
    print(f"Resumen enviado con {len(partidos)} partido(s)." if exito else "Fallo el envio del resumen.")


if __name__ == "__main__":
    enviar_resumen(forzar="--forzar" in sys.argv)
