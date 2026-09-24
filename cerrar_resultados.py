"""
cerrar_resultados.py
---------------------
FASE 4 -- migrada a ESPN.

CAMBIOS de esta version:
  1. obtener_resultado_fixture() ahora necesita el liga_slug guardado
     por seleccionar_partidos.py (ESPN lo exige en la URL). Si un
     partido viejo no lo tiene (quedo seleccionado antes de la
     migracion), se avisa en el log y se salta -- no se inventa.
  2. El contador de uso diario ahora viene de cuota_espn.py (ya no hay
     "disponibles" real -- ver ese modulo).

Todo lo demas (calculo de acierto, actualizacion de Glicko-2, auditoria
de cada alerta individual, archivo del dia, Excel) sigue igual.
"""

import json
from pathlib import Path

from fetch_data import obtener_resultado_fixture, obtener_estado_desde_scoreboard
from cuota_espn import uso_de_hoy
from estado_diario import ya_se_hizo, marcar_hecho
from resolucion_alertas import CRITERIO_POR_TIPO, TIPO_ALIAS, evaluar_alerta, nombre_normalizado, resolver_pendientes
import ratings_store

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_PARTIDOS = DATA_DIR / "partidos_hoy.json"
DIR_HISTORIAL_DIAS = DATA_DIR / "historial_dias"
ARCHIVO_EXCEL = DATA_DIR / "estadisticas.xlsx"

ESTADOS_TERMINADO = ("FT", "AET", "PEN")
VENTANA_ACIERTO_MINUTOS = 15


def calcular_acierto(p, goles_local, goles_visitante):
    """
    CAMBIO (agosto 2026, a pedido explicito): el criterio de acierto
    ahora depende del tipo de pronostico:
      - favorito_directo: acierto SOLO si gana el favorito (empate o
        derrota = fallo). Sin cambios respecto a como funcionaba antes.
      - doble_oportunidad: acierto si el favorito gana O EMPATA -- solo
        falla si gana el rival (el pronostico original ya cubria esas
        dos posibilidades, "empate o gana", asi que un empate cuenta
        como acierto igual que una victoria).
    """
    goles_favorito = goles_local if p["favorito_es_local"] else goles_visitante
    goles_rival = goles_visitante if p["favorito_es_local"] else goles_local
    if p.get("tipo_pronostico") == "doble_oportunidad":
        return goles_favorito >= goles_rival
    return goles_favorito > goles_rival


def _actualizar_rating_propio(p, goles_local, goles_visitante):
    if goles_local > goles_visitante:
        resultado_local, resultado_visitante = 1.0, 0.0
    elif goles_local < goles_visitante:
        resultado_local, resultado_visitante = 0.0, 1.0
    else:
        resultado_local, resultado_visitante = 0.5, 0.5

    llave_local = ratings_store.llave_equipo(p.get("home_id"), nombre=p["local"])
    llave_visitante = ratings_store.llave_equipo(p.get("away_id"), nombre=p["visitante"])

    eq_local = ratings_store.obtener_o_crear(llave_local, nombre=p["local"])
    eq_visitante = ratings_store.obtener_o_crear(llave_visitante, nombre=p["visitante"])

    rating_local_antes, rd_local_antes = eq_local["rating"], eq_local["rd"]
    rating_visitante_antes, rd_visitante_antes = eq_visitante["rating"], eq_visitante["rd"]

    ratings_store.actualizar_tras_partido(llave_local, rating_visitante_antes, rd_visitante_antes,
                                           resultado_local, es_bootstrap=False)
    ratings_store.actualizar_tras_partido(llave_visitante, rating_local_antes, rd_local_antes,
                                           resultado_visitante, es_bootstrap=False)


def _auditar_alertas(p):
    """Una sola fuente de verdad (X1): si la alerta ya se resolvio en
    vivo se copia su acierto; si esta pendiente o es antigua (sin
    estado), se evalua con las reglas compartidas de
    resolucion_alertas.evaluar_alerta (siguiente gol / 15 min / fin 1T).
    Ya no se usa _hubo_gol_en_ventana salvo dentro de ventana_15."""
    for alerta in p.get("alertas_enviadas", []):
        if alerta.get("estado") in ("acierto", "fallo", "ambiguo", "no_aplica"):
            continue  # resuelto en vivo o sin criterio aplicable; no se recalcula
        tipo = nombre_normalizado(alerta.get("tipo"))
        lado, criterio = CRITERIO_POR_TIPO.get(tipo, (None, None))
        if criterio is None:
            alerta["acierto"] = None
            continue
        marcador_final = None
        rf = p.get("resultado_final")
        if rf and rf != "sin resolver":
            try:
                a, b = [int(x) for x in str(rf).split("-")]
                marcador_final = (a, b)
            except Exception:
                marcador_final = None
        alerta["acierto"] = evaluar_alerta(
            p.get("historial_snapshots", []), alerta,
            p.get("favorito_es_local", True), marcador_final)


def cerrar():
    if ya_se_hizo("cierre"):
        print("El cierre de hoy ya se hizo antes. Nada que hacer.")
        return

    if not ARCHIVO_PARTIDOS.exists():
        print("No hay partidos_hoy.json todavia. Se reintentara en el proximo ciclo.")
        return

    datos = json.loads(ARCHIVO_PARTIDOS.read_text(encoding="utf-8"))
    cambios = False

    for p in datos["partidos"]:
        if p.get("acierto") is not None or not p.get("fixture_id"):
            continue

        liga_slug = p.get("liga_slug")
        if not liga_slug or liga_slug == "all":
            # F1/F4: para liga_slug "all" se usa el scoreboard global
            try:
                estado_info = obtener_estado_desde_scoreboard(
                    p["fixture_id"], datos.get("fecha", ""))
            except Exception as e:
                print(f"[AVISO] No se pudo consultar scoreboard global para {p['partido']}: {e}")
                continue
            if not estado_info:
                continue
            if estado_info.get("estado") != "post":
                continue
            gh = estado_info.get("goles_local")
            ga = estado_info.get("goles_visitante")
            if gh is None or ga is None:
                continue
            p["resultado_final"] = f"{gh}-{ga}"
            p["acierto"] = calcular_acierto(p, gh, ga)
            _actualizar_rating_propio(p, gh, ga)
            _auditar_alertas(p)
            cambios = True
            continue

        try:
            info = obtener_resultado_fixture(p["fixture_id"], liga_slug)
        except Exception as e:
            print(f"[AVISO] No se pudo consultar el resultado de {p['partido']}: {e}")
            continue
        if not info:
            continue

        estado = info["fixture"]["status"]["short"]
        if estado not in ESTADOS_TERMINADO:
            continue

        gh, ga = info["goals"]["home"], info["goals"]["away"]
        if gh is None or ga is None:
            continue
        p["resultado_final"] = f"{gh}-{ga}"
        p["acierto"] = calcular_acierto(p, gh, ga)

        _actualizar_rating_propio(p, gh, ga)

        # F4: resolver alertas pendientes que nunca se procesaron en
        # vivo (p.ej. liga_slug "all" sin monitoreo en tiempo real).
        snap_fin = {"minuto": None, "goles_local": gh, "goles_visitante": ga,
                    "stats_local": {}, "stats_visitante": {}}
        resueltas = resolver_pendientes(
            p, None, snap_fin, terminado=True,
            marcador_final=(gh, ga), sin_gol_es_fallo=True)
        if resueltas:
            for alerta in resueltas:
                if alerta.get("estado") == "acierto":
                    alerta["acierto"] = True
                elif alerta.get("estado") == "fallo":
                    alerta["acierto"] = False
                else:
                    alerta["acierto"] = None
            print(f"  F4: {len(resueltas)} alerta(s) resuelta(s) en cierre para {p['partido']}")

        _auditar_alertas(p)

        cambios = True

    if cambios:
        ARCHIVO_PARTIDOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")

    usadas, disponibles = uso_de_hoy()

    DIR_HISTORIAL_DIAS.mkdir(exist_ok=True, parents=True)
    archivo_dia = DIR_HISTORIAL_DIAS / f"{datos['fecha']}.json"
    archivo_dia.write_text(json.dumps({
        "fecha": datos["fecha"],
        "partidos": datos["partidos"],
        "espn_peticiones_usadas": usadas,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Dia archivado en {archivo_dia}")

    _actualizar_excel(datos["fecha"], datos["partidos"], usadas)
    marcar_hecho("cierre")


def _actualizar_excel(fecha, partidos, usadas):
    try:
        import openpyxl
    except ImportError:
        print("[AVISO] openpyxl no esta instalado, no se pudo actualizar el Excel "
              "(agrega 'openpyxl' a requirements.txt).")
        return

    if ARCHIVO_EXCEL.exists():
        wb = openpyxl.load_workbook(ARCHIVO_EXCEL)
    else:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        hoja1 = wb.create_sheet("Resultados diarios")
        hoja1.append(["Fecha", "Partido", "Favorito", "Local/Visitante", "Cuota inicial (proxy)",
                      "Prob. inicial %", "Marcador final", "Acierto", "Alertas enviadas",
                      "Rating propio local (n)", "Rating propio visitante (n)", "Pais verificado"])
        hoja2 = wb.create_sheet("Resumen por dia")
        hoja2.append(["Fecha", "Total partidos", "Aciertos", "% Aciertos", "Peticiones a ESPN usadas"])
        hoja3 = wb.create_sheet("Acierto por tipo de alerta")
        hoja3.append(["Fecha", "Tipo de alerta", "Enviadas", "Aciertos", "% Acierto"])

    hoja1 = wb["Resultados diarios"]
    hoja2 = wb["Resumen por dia"]
    hoja3 = wb["Acierto por tipo de alerta"] if "Acierto por tipo de alerta" in wb.sheetnames \
        else wb.create_sheet("Acierto por tipo de alerta")
    if hoja3.max_row == 1 and hoja3["A1"].value is None:
        hoja3.append(["Fecha", "Tipo de alerta", "Enviadas", "Aciertos", "% Acierto",
                      "Fallos", "Sin determinar"])

    ya_registrado = any(fila[0].value == fecha for fila in hoja2.iter_rows(min_row=2) if fila[0].value)
    if ya_registrado:
        print(f"El dia {fecha} ya estaba registrado en el Excel, no se duplica.")
        return

    total = len(partidos)
    aciertos = sum(1 for p in partidos if p.get("acierto") is True)
    resueltos = sum(1 for p in partidos if p.get("acierto") is not None)

    conteo_por_tipo = {}
    for p in partidos:
        hoja1.append([
            fecha, p["partido"], p["favorito"],
            "Local" if p["favorito_es_local"] else "Visitante",
            p.get("cuota_inicial", ""), p.get("probabilidad_inicial", ""),
            p.get("resultado_final") or "sin resolver",
            "SI" if p.get("acierto") is True else ("NO" if p.get("acierto") is False else "?"),
            len(p.get("alertas_enviadas", [])),
            p.get("rating_propio_partidos_local", 0), p.get("rating_propio_partidos_visitante", 0),
            "si" if p.get("pais_verificado") else "no",
        ])
        # Agrupación por tipo dentro del partido (mejora 2026-09): varias
        # alertas del mismo tipo en el mismo partido cuentan COMO UNA sola
        # fila/resultado en "Acierto por tipo de alerta".
        grupos = {}
        for alerta in p.get("alertas_enviadas", []):
            tipo = nombre_normalizado(alerta.get("tipo"))
            grupos.setdefault(tipo, []).append(alerta)
        for tipo, alertas_grupo in grupos.items():
            conteo = conteo_por_tipo.setdefault(tipo, {"enviadas": 0, "aciertos": 0, "fallos": 0, "sin_det": 0})
            conteo["enviadas"] += 1
            estados = [a.get("acierto") for a in alertas_grupo if a.get("acierto") is not None]
            if not estados:
                conteo["sin_det"] += 1
            elif all(estados):
                conteo["aciertos"] += 1
            elif not any(estados):
                conteo["fallos"] += 1
            else:
                # Mixto: mayoría decide
                if sum(1 for e in estados if e) * 2 > len(estados):
                    conteo["aciertos"] += 1
                else:
                    conteo["fallos"] += 1

    for tipo, c in conteo_por_tipo.items():
        denom = c["aciertos"] + c["fallos"]
        pct = round((c["aciertos"] / denom) * 100, 1) if denom else None
        hoja3.append([fecha, tipo, c["enviadas"], c["aciertos"], pct, c["fallos"], c["sin_det"]])

    pct_aciertos = round((aciertos / resueltos) * 100, 1) if resueltos else None
    hoja2.append([fecha, total, aciertos, pct_aciertos, usadas])

    DATA_DIR.mkdir(exist_ok=True)
    wb.save(ARCHIVO_EXCEL)
    print(f"Excel actualizado: {ARCHIVO_EXCEL} ({total} partidos, {aciertos} aciertos)")


if __name__ == "__main__":
    cerrar()
