"""
cuota_espn.py
--------------
Reemplaza a cuota_api_football.py tras la migracion a ESPN.

POR QUE CAMBIO DE FORMA: ESPN no publica ningun limite diario oficial
(a diferencia de API-Football, 100/dia documentado). La documentacion
comunitaria dice textual: "no official limits published, but excessive
requests may be blocked" -- y los reportes de otros desarrolladores
varian tanto (de "un par de cientos/dia" a "2500/dia", ninguno
verificado) que no hay ningun numero confiable contra el cual medir un
"cupo restante" real.

Por eso este modulo YA NO calcula "disponibles" -- solo cuenta cuantas
peticiones se hicieron hoy, para diagnostico en el reporte de las 6am
(ver tendencias, no tomar decisiones automaticas con ese numero). El
principio de fondo ("nunca gastar una peticion si se puede evitar") se
mantiene en el codigo que consume este contador -- lo que cambio es que
ya no hay un semaforo numerico que avise antes de tiempo.

RIESGO ADICIONAL documentado (ver MIGRACION_ESPN.md): sin autenticacion,
un eventual bloqueo probablemente actua por IP -- y los runners de
GitHub Actions comparten rangos de IP entre miles de proyectos ajenos.
No hay forma de blindarse del todo contra esto; se acepta como
limitacion real del proyecto, igual que ya se acepto el limite de
cuenta unica de API-Football en su momento.
"""

import json
import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ARCHIVO_USO = DATA_DIR / "uso_espn.json"


def _fecha_local_hoy():
    zona = datetime.timezone(datetime.timedelta(hours=-5))
    return datetime.datetime.now(zona).date().isoformat()


def _cargar_estado():
    hoy = _fecha_local_hoy()
    if ARCHIVO_USO.exists():
        try:
            estado = json.loads(ARCHIVO_USO.read_text(encoding="utf-8"))
            if estado.get("fecha") == hoy:
                return estado
        except Exception:
            pass
    return {"fecha": hoy, "usadas": 0}


def _guardar_estado(estado):
    DATA_DIR.mkdir(exist_ok=True)
    ARCHIVO_USO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def registrar_uso():
    estado = _cargar_estado()
    estado["usadas"] += 1
    _guardar_estado(estado)


def uso_de_hoy():
    """Devuelve (usadas, None). El segundo valor ya no es 'disponibles'
    -- no hay techo conocido contra el cual restar. Se mantiene la
    tupla de 2 valores por compatibilidad con codigo que la desempaqueta."""
    estado = _cargar_estado()
    return estado["usadas"], None
