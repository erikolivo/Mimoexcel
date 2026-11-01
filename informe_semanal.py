"""
informe_semanal.py
------------------
Resumen semanal de efectividad de las alertas, enviado por Telegram los
lunes a las 06:00 hora Ecuador.

Lee los dias archivados en data/historial_dias/ (los escribe el cierre de
cada dia) y calcula, sobre las alertas ya resueltas (acierto True/False):

- acierto global y por tipo de alerta,
- por tipo de pick (favorito directo vs doble oportunidad),
- por prioridad recalculada y por % de la hoja,
- por color del Nivel Actual del favorito (se guarda desde la v8),
- por movimiento de la cuota / CLV del partido (se guarda desde la v8),
- y como van las combinadas del dia (es_destacado).

No escribe nada: solo lee los JSON y manda el mensaje. Con --simular
imprime el informe sin enviarlo (util para revisarlo antes del lunes).
"""

import datetime
import json
import sys
from pathlib import Path

from telegram_utils import enviar_mensaje_telegram

DATA_DIR = Path(__file__).parent / "data"
HISTORIAL_DIR = DATA_DIR / "historial_dias"
ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))

DIAS_POR_DEFECTO = 7
MINIMO_PARA_TIPO = 5          # tipos con menos alertas se agrupan en "otros"
MAXIMO_TIPOS = 8


def _pct(aciertos, resueltas):
    if not resueltas:
        return None
    return round(aciertos * 100.0 / resueltas, 1)


def _texto_efectividad(aciertos, resueltas):
    porcentaje = _pct(aciertos, resueltas)
    if porcentaje is None:
        return "sin alertas resueltas"
    return f"{porcentaje:.1f} % ({aciertos}/{resueltas})"


def _bucket_pf(pf):
    if pf is None:
        return None
    if pf < 0.55:
        return "menos de 55 %"
    if pf < 0.65:
        return "55-65 %"
    if pf < 0.75:
        return "65-75 %"
    return "75 % o mas"


BUCKETS_PF = ["menos de 55 %", "55-65 %", "65-75 %", "75 % o mas"]


def _color_favorito(partido):
    """Color del Nivel Actual del equipo favorito, o None si no hay dato."""
    nivel = partido.get("nivel_actual")
    if not isinstance(nivel, dict):
        return None
    lado = "local" if partido.get("favorito_es_local") else "visitante"
    datos = nivel.get(lado)
    if not isinstance(datos, dict):
        return None
    return datos.get("color")


def _bucket_clv(clv):
    if clv is None:
        return None
    if clv > 0:
        return "cuota bajo (a favor)"
    if clv < 0:
        return "cuota subio (en contra)"
    return "sin movimiento"


def _agrupar(alertas, clave, orden=None):
    """Cuenta aciertos/resueltas por segmento. Devuelve lista de tuplas
    (segmento, aciertos, resueltas) ordenada por volumen."""
    conteo = {}
    for alerta, partido in alertas:
        segmento = clave(alerta, partido)
        if segmento is None:
            continue
        aciertos, resueltas = conteo.get(segmento, (0, 0))
        conteo[segmento] = (aciertos + (1 if alerta.get("acierto") is True else 0), resueltas + 1)
    items = list(conteo.items())
    if orden:
        items.sort(key=lambda item: orden.index(item[0]) if item[0] in orden else len(orden))
    else:
        items.sort(key=lambda item: -item[1][1])
    return [(segmento, aciertos, resueltas) for segmento, (aciertos, resueltas) in items]


def _linea_segmento(etiqueta, aciertos, resueltas):
    return f"  {etiqueta}: {_texto_efectividad(aciertos, resueltas)}"


def _cargar_dias(dias):
    """Ultimos `dias` dias archivados, ordenados del mas viejo al mas nuevo.

    Devuelve [] si no hay carpeta o si ningun archivo se puede leer: el
    informe nunca debe romper el workflow por un JSON dañado.
    """
    if not HISTORIAL_DIR.exists():
        return []
    cargados = []
    for ruta in HISTORIAL_DIR.glob("*.json"):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(datos, dict):
            continue
        fecha = str(datos.get("fecha") or ruta.stem)
        cargados.append((fecha, datos))
    cargados.sort(key=lambda item: item[0])
    return cargados[-dias:] if dias > 0 else []


def construir_informe(dias=DIAS_POR_DEFECTO):
    """Devuelve el texto del informe. Nunca lanza: ante un fallo devuelve
    un mensaje de error corto para que el workflow siga vivo."""
    try:
        return _construir(dias)
    except Exception as error:  # defensa: un informe no debe tumbar el job
        return f"⚠️ No se pudo construir el informe semanal: {error}"


def _construir(dias):
    cargados = _cargar_dias(dias)
    if not cargados:
        return "📈 <b>Informe semanal de alertas</b>\n\nTodavia no hay dias archivados para resumir."

    alertas, partidos = [], []
    for fecha, datos in cargados:
        for partido in datos.get("partidos", []) or []:
            if not isinstance(partido, dict):
                continue
            partidos.append(partido)
            for alerta in partido.get("alertas_enviadas", []) or []:
                if not isinstance(alerta, dict) or alerta.get("acierto") is None:
                    continue
                alertas.append((alerta, partido))

    rango = f"{cargados[0][0]} a {cargados[-1][0]}"
    lineas = ["📈 <b>Informe semanal de alertas</b>",
              f"<i>{rango} · {len(cargados)} dia(s) con datos</i>", ""]

    if not alertas:
        lineas.append("No hay alertas resueltas en el periodo.")
        return "\n".join(lineas)

    total = len(alertas)
    aciertos = sum(1 for alerta, _ in alertas if alerta.get("acierto") is True)
    lineas.append(f"🎯 <b>Efectividad global:</b> {_texto_efectividad(aciertos, total)}")
    lineas.append("")

    # --- Por tipo de alerta ---
    por_tipo = _agrupar(alertas, lambda a, p: a.get("tipo") or "sin tipo")
    principales = [item for item in por_tipo if item[2] >= MINIMO_PARA_TIPO][:MAXIMO_TIPOS]
    resto = [item for item in por_tipo if item not in principales]
    if principales:
        lineas.append("<b>Por tipo de alerta</b>")
        for tipo, ac, res in principales:
            lineas.append(_linea_segmento(tipo, ac, res))
        if resto:
            ac = sum(item[1] for item in resto)
            res = sum(item[2] for item in resto)
            lineas.append(_linea_segmento(f"otros ({len(resto)} tipos)", ac, res))
        lineas.append("")

    # --- Por tipo de pick ---
    lineas.append("<b>Por tipo de pick</b>")
    for segmento, ac, res in _agrupar(
            alertas, lambda a, p: "doble oportunidad" if p.get("tipo_pronostico") == "doble_oportunidad" else "favorito directo"):
        lineas.append(_linea_segmento(segmento, ac, res))
    lineas.append("")

    # --- Por prioridad recalculada ---
    lineas.append("<b>Por prioridad</b>")
    for segmento, ac, res in _agrupar(
            alertas, lambda a, p: p.get("prioridad") or "sin prioridad", orden=["ALTA", "MEDIA", "BAJA"]):
        lineas.append(_linea_segmento(segmento, ac, res))
    lineas.append("")

    # --- Por % de la hoja (solo v8+) ---
    con_pf = [(a, p) for a, p in alertas if p.get("pf_hoja") is not None]
    if con_pf:
        lineas.append("<b>Por % de la hoja (favorito)</b>")
        for segmento, ac, res in _agrupar(con_pf, lambda a, p: _bucket_pf(p.get("pf_hoja")), orden=BUCKETS_PF):
            lineas.append(_linea_segmento(segmento, ac, res))
        lineas.append("")
    else:
        lineas.append("<i>El % de la hoja se guarda desde la seleccion v8; aun no hay dias con ese dato.</i>")
        lineas.append("")

    # --- Por color del Nivel Actual (solo alertas nuevas) ---
    con_color = [(a, p) for a, p in alertas if _color_favorito(p)]
    if con_color:
        lineas.append("<b>Por color del favorito</b>")
        for segmento, ac, res in _agrupar(con_color, lambda a, p: _color_favorito(p)):
            lineas.append(_linea_segmento(segmento, ac, res))
        lineas.append("")
    else:
        lineas.append("<i>El color del Nivel Actual se guarda desde hoy; aun no hay alertas resueltas con ese dato.</i>")
        lineas.append("")

    # --- Por CLV del partido (solo alertas nuevas) ---
    con_clv = [(a, p) for a, p in alertas if p.get("clv") is not None]
    if con_clv:
        lineas.append("<b>Por movimiento de la cuota (CLV)</b>")
        for segmento, ac, res in _agrupar(
                con_clv, lambda a, p: _bucket_clv(p.get("clv")),
                orden=["cuota bajo (a favor)", "sin movimiento", "cuota subio (en contra)"]):
            lineas.append(_linea_segmento(segmento, ac, res))
        lineas.append("")
    else:
        lineas.append("<i>El CLV se guarda desde hoy; aun no hay dias con ese dato.</i>")
        lineas.append("")

    # --- Combinadas del dia ---
    marcados = [p for p in partidos if p.get("es_destacado")]
    resueltos = [p for p in marcados if p.get("acierto") is not None]
    if resueltos:
        ac = sum(1 for p in resueltos if p.get("acierto") is True)
        lineas.append("<b>Combinadas del dia</b>")
        lineas.append(_linea_segmento("partidos elegidos", ac, len(resueltos)))
        lineas.append("")

    return "\n".join(lineas).rstrip()


def enviar_informe(dias=DIAS_POR_DEFECTO, simular=False):
    texto = construir_informe(dias)
    if simular:
        print(texto)
        return True
    exito = enviar_mensaje_telegram(texto)
    print("Informe semanal enviado." if exito else "Fallo el envio del informe semanal.")
    return exito


if __name__ == "__main__":
    dias = DIAS_POR_DEFECTO
    if "--dias" in sys.argv:
        try:
            dias = int(sys.argv[sys.argv.index("--dias") + 1])
        except (IndexError, ValueError):
            print(f"[AVISO] --dias invalido, se usan {DIAS_POR_DEFECTO} dias.")
    enviar_informe(dias, simular="--simular" in sys.argv)
