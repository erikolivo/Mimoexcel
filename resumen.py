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


def _obtener_datos_estilo(equipo, liga_slug):
    """
    Obtiene datos de football-data.co.uk para calcular estilo de juego.
    """
    try:
        if liga_slug not in MAPA_LIGA_SLUG_A_CODIGO:
            return None
        
        codigo_liga = MAPA_LIGA_SLUG_A_CODIGO[liga_slug]
        resultados = obtener_resultados_liga(codigo_liga)
        
        if not resultados:
            return None
        
        # Filtrar por equipo y tomar ultimas6 fechas
        datos_equipo = []
        for r in resultados[-18:]:  # Ultimas6 jornadas approx
            if r.get('local') == equipo or r.get('visitante') == equipo:
                es_local = r.get('local') == equipo
                datos_equipo.append({
                    'tiros_totales': r.get('HS' if es_local else 'AS', 0),
                    'tiros_puerta': r.get('HST' if es_local else 'AST', 0),
                    'corners': r.get('HC' if es_local else 'AC', 0),
                    'faltas': r.get('HF' if es_local else 'AF', 0),
                    'amarillas': r.get('HY' if es_local else 'AY', 0),
                    'goles_1t': r.get('FTHG' if es_local else 'FTAG', 0) // 2,  # Aprox
                })
        
        return datos_equipo[-6:] if datos_equipo else None
    except Exception:
        return None


def _calcular_nivel_actual(historial_equipo, es_local):
    """
    Calcula el Nivel Actual (0-10) basado en el historial del equipo.
    idealmente5-6 partidos, pero acepta desde3 para mostrar algo.
    Retorna (poder, color, n_partidos) o (None, None, 0) si no hay datos.
    """
    if not historial_equipo:
        return None, None, 0
    
    partidos = historial_equipo[-6:] if len(historial_equipo) >=6 else historial_equipo
    
    if len(partidos) <3:
        return None, None, 0
    
    gf_total = sum(p['goles_favor'] for p in partidos)
    gc_total = sum(p['goles_contra'] for p in partidos)
    victorias = sum(1 for p in partidos if p['resultado'] == 'V')
    empates = sum(1 for p in partidos if p['resultado'] == 'E')
    
    n = len(partidos)
    ataque = gf_total / n
    defensa = 1 - (gc_total / n)
    forma = (victorias *3 + empates) /18
    
    poder = (ataque *0.45 + defensa *0.3 + forma *0.25) *10
    poder = max(0, min(10, poder))
    
    if poder >=8:
        color = "🔵"
    elif poder >=6:
        color = "🟢"
    elif poder >=4:
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
                        gf_local = sum(p['goles_favor'] for p in historial_local[-6:])
                        gc_local = sum(p['goles_contra'] for p in historial_local[-6:])
                        lineas.append(f"{color_local} {escapar_html(p['local'])}: {poder_local:.1f}{marca_n} (GF:{gf_local} GC:{gc_local})")
                    if poder_visitante is not None:
                        marca_n = f" ({n_visitante})" if n_visitante < 5 else ""
                        gf_visitante = sum(p['goles_favor'] for p in historial_visitante[-6:])
                        gc_visitante = sum(p['goles_contra'] for p in historial_visitante[-6:])
                        lineas.append(f"{color_visitante} {escapar_html(p['visitante'])}: {poder_visitante:.1f}{marca_n} (GF:{gf_visitante} GC:{gc_visitante})")
                    
                    # Ultimos resultados
                    ultimos_local = historial_local[-5:] if len(historial_local) >=5 else historial_local
                    ultimos_visitante = historial_visitante[-5:] if len(historial_visitante) >=5 else historial_visitante
                    
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
