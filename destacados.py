"""
destacados.py
--------------
NUEVO (agosto 2026, a pedido explicito) -- Fase 2.5: a las 7:30am, de
los partidos del dia que SI tienen seguimiento en vivo disponible
(fixture_id ya localizado en ESPN), elige los9 MEJORES partidos
basados en Poder de Match y Estilo de Juego, divididos en3 grupos de3.

Cada partido elegido queda marcado en partidos_hoy.json con
"es_destacado": True y "grupo_destacado": 1,2 o3 -- reporte_diario.py
usa esa marca para mostrar el % de acierto de este grupo por separado
del total general.

Reintenta cada 5 min dentro de una ventana corta (igual filosofia que
Fase 2), y se autoprotege con estado_diario ("destacados") para no
repetir el sorteo si ya se hizo hoy -- salvo que se llame con
--forzar (util para pruebas manuales desde Actions).
"""

import json
import sys
import datetime
from pathlib import Path

from telegram_utils import enviar_mensaje_telegram, escapar_html
from estado_diario import ya_se_hizo, marcar_hecho
from fetch_data import obtener_historial_equipo
from resumen import _calcular_nivel_actual, _calcular_estilo_juego, _obtener_datos_estilo

ARCHIVO = Path(__file__).parent / "data" / "partidos_hoy.json"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))

EMOJI_TIPO_PRONOSTICO = {
    "favorito_directo": "\U0001F3AF",   # 🎯
    "doble_oportunidad": "\U0001F500",  # 🔀
}
CORONA_FAVORITO = "\U0001F451"  # 👑

CANTIDAD_DESTACADOS = 9
CANTIDAD_GRUPOS = 3
PARTIDS_POR_GRUPO = 3


def _hora_local(hora_inicio_utc_iso):
    if not hora_inicio_utc_iso:
        return "?"
    try:
        dt_utc = datetime.datetime.fromisoformat(hora_inicio_utc_iso.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(ZONA_HORARIA_LOCAL)
        return dt_local.strftime("%H:%M")
    except Exception:
        return hora_inicio_utc_iso


def _titulo_partido(p):
    emoji_tipo = EMOJI_TIPO_PRONOSTICO.get(p.get("tipo_pronostico"), EMOJI_TIPO_PRONOSTICO["favorito_directo"])
    marca_favorito = f" {emoji_tipo}{CORONA_FAVORITO}"
    corona_local = marca_favorito if p.get("favorito_es_local") else ""
    corona_visitante = marca_favorito if not p.get("favorito_es_local") else ""
    return f"{escapar_html(p['local'])}{corona_local} vs {escapar_html(p['visitante'])}{corona_visitante}"


def _calcular_probabilidad_exito(partido):
    """
    Calcula la probabilidad de exito de un partido basado en:
    1. Diferencia de cuotas (fav vs no fav)
    2. Poder de Match del favorito
    3. Estilo de Juego favorable
    Retorna un score de0 a100
    """
    score = 0
    
    #1. Diferencia de cuotas (40% del peso)
    cuota_local = partido.get("cuota_local_inicial", 0) or 0
    cuota_visitante = partido.get("cuota_visitante_inicial", 0) or 0
    
    if cuota_local >0 and cuota_visitante >0:
        if partido.get("favorito_es_local"):
            ratio_cuota = cuota_visitante / cuota_local
        else:
            ratio_cuota = cuota_local / cuota_visitante
        
        # A mayor ratio, mas favorito es
        score_cuota = min(ratio_cuota * 20, 40)
        score += score_cuota
    
    #2. Poder de Match del favorito (40% del peso)
    home_id = partido.get('home_id')
    away_id = partido.get('away_id')
    liga_slug = partido.get('liga_slug')
    
    if home_id and away_id:
        try:
            historial_local = obtener_historial_equipo(home_id, liga_slug)
            historial_visitante = obtener_historial_equipo(away_id, liga_slug)
            
            poder_local, _ = _calcular_nivel_actual(historial_local, True)
            poder_visitante, _ = _calcular_nivel_actual(historial_visitante, False)
            
            if poder_local is not None and poder_visitante is not None:
                if partido.get("favorito_es_local"):
                    poder_fav = poder_local
                else:
                    poder_fav = poder_visitante
                
                score_poder = (poder_fav / 10) * 40
                score += score_poder
        except Exception:
            pass
    
    #3. Estilo de Juego favorable (20% del peso)
    if liga_slug:
        try:
            datos_estilo_local = _obtener_datos_estilo(partido['local'], liga_slug)
            datos_estilo_visitante = _obtener_datos_estilo(partido['visitante'], liga_slug)
            
            estilo_local, _ = _calcular_estilo_juego(datos_estilo_local)
            estilo_visitante, _ = _calcular_estilo_juego(datos_estilo_visitante)
            
            if partido.get("favorito_es_local"):
                estilo_fav = estilo_local
            else:
                estilo_fav = estilo_visitante
            
            # Ofensivo y Presión Alta son estilos favorables
            if "Ofensivo" in str(estilo_fav) or "Presión" in str(estilo_fav):
                score += 20
            elif "Equilibrado" in str(estilo_fav):
                score += 10
        except Exception:
            pass
    
    return score


def elegir_destacados(partidos):
    """Devuelve (grupos, elegidos) -- grupos es una lista de listas de
    partidos, elegidos es la lista plana (para marcar en el JSON).
    Selecciona los9 MEJORES partidos basados en probabilidad de exito."""
    disponibles = [p for p in partidos if p.get("fixture_id")]
    
    # Calcular score de probabilidad para cada partido
    partidos_con_score = []
    for p in disponibles:
        score = _calcular_probabilidad_exito(p)
        partidos_con_score.append((p, score))
    
    # Ordenar por score (mayor a menor)
    partidos_con_score.sort(key=lambda x: x[1], reverse=True)
    
    # Tomar los9 mejores (sin repetir)
    elegidos = [p for p, score in partidos_con_score[:CANTIDAD_DESTACADOS]]
    
    # Dividir en3 grupos
    grupos = [[] for _ in range(CANTIDAD_GRUPOS)]
    for i, p in enumerate(elegidos):
        grupo_idx = i % CANTIDAD_GRUPOS
        p["es_destacado"] = True
        p["grupo_destacado"] = grupo_idx + 1
        grupos[grupo_idx].append(p)
    
    return grupos, elegidos


def enviar_destacados(forzar=False):
    if not forzar and ya_se_hizo("destacados"):
        print("Los destacados de hoy ya se enviaron antes. Nada que hacer.")
        return

    if not ARCHIVO.exists():
        print("Fase 1 todavia no ha generado partidos_hoy.json. Se reintentara en el proximo ciclo.")
        return

    datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    partidos = datos.get("partidos", [])

    grupos, elegidos = elegir_destacados(partidos)

    if not elegidos:
        exito = enviar_mensaje_telegram(
            "\U0001F3B2 Hoy no hay partidos con seguimiento en vivo disponible para destacar."
        )
        if exito:
            marcar_hecho("destacados")
        print("Destacados: 0 partidos disponibles hoy." if exito else "Fallo el envio de destacados.")
        return

    lineas = [f"\U0001F3B2 <b>Selección destacada de hoy</b>"]
    
    for idx, grupo in enumerate(grupos, start=1):
        if not grupo:
            continue
        
        # Separador visual
        lineas.append("\n" + "=" * 35)
        lineas.append(f"<b>Grupo {idx}</b>")
        lineas.append("=" * 35)
        
        for i, p in enumerate(grupo, start=1):
            emoji_tipo = EMOJI_TIPO_PRONOSTICO.get(p.get("tipo_pronostico"), EMOJI_TIPO_PRONOSTICO["favorito_directo"])
            corona_local = emoji_tipo + CORONA_FAVORITO if p.get("favorito_es_local") else ""
            corona_visitante = emoji_tipo + CORONA_FAVORITO if not p.get("favorito_es_local") else ""
            
            titulo = f"{escapar_html(p['local'])}{corona_local} vs {escapar_html(p['visitante'])}{corona_visitante}"
            lineas.append(f"{i}. {titulo}")
        
        lineas.append("=" * 35)

    exito = enviar_mensaje_telegram("\n".join(lineas))
    if exito:
        ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        marcar_hecho("destacados")
    print(f"Destacados enviados: {len(elegidos)} partido(s) en {CANTIDAD_GRUPOS} grupos." if exito else "Fallo el envio de destacados.")


if __name__ == "__main__":
    enviar_destacados(forzar="--forzar" in sys.argv)
