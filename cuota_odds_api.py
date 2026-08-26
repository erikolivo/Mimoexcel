"""
cuota_odds_api.py
------------------
SIN CAMBIOS -- lleva la cuenta del cupo de The Odds API (plan free),
que sigue siendo relevante como respaldo secundario tras la migracion a
ESPN. The Odds API SI devuelve el cupo real en los headers de cada
respuesta -- se usa como AUTORIDAD, en vez de contar peticiones a ciegas.
"""

import json
import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_USO = DATA_DIR / "uso_odds_api.json"

LIMITE_MENSUAL_RESPALDO = 500


def _mes_actual():
    return datetime.date.today().strftime("%Y-%m")


def _cargar_estado():
    mes = _mes_actual()
    if ARCHIVO_USO.exists():
        try:
            estado = json.loads(ARCHIVO_USO.read_text(encoding="utf-8"))
            if estado.get("mes") == mes:
                return estado
        except Exception:
            pass
    return {"mes": mes, "usadas_estimadas": 0, "restante_conocido": None, "ultima_actualizacion": None}


def _guardar_estado(estado):
    DATA_DIR.mkdir(exist_ok=True)
    ARCHIVO_USO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def registrar_peticion_sin_headers():
    estado = _cargar_estado()
    estado["usadas_estimadas"] = estado.get("usadas_estimadas", 0) + 1
    _guardar_estado(estado)


def actualizar_desde_headers(headers):
    restante = headers.get("x-requests-remaining")
    usadas = headers.get("x-requests-used")
    if restante is None:
        registrar_peticion_sin_headers()
        return

    estado = _cargar_estado()
    try:
        estado["restante_conocido"] = int(restante)
    except (TypeError, ValueError):
        pass
    if usadas is not None:
        try:
            estado["usadas_estimadas"] = int(usadas)
        except (TypeError, ValueError):
            pass
    estado["ultima_actualizacion"] = datetime.datetime.now().isoformat()
    _guardar_estado(estado)


def cupo_restante():
    estado = _cargar_estado()
    if estado.get("restante_conocido") is not None:
        return estado["restante_conocido"]
    return max(0, LIMITE_MENSUAL_RESPALDO - estado.get("usadas_estimadas", 0))


def hay_cupo_suficiente(margen=30):
    return cupo_restante() > margen
