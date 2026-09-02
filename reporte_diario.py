"""
reporte_diario.py
------------------
Lee los resultados de Hoja2 del Google Sheet y envía el resumen por Telegram
a las 08:30 hora Ecuador.
"""

import datetime

from telegram_utils import enviar_mensaje_telegram, escapar_html
from google_favoritos import obtener_resultados_hoja2

ZONA_HORARIA_LOCAL = datetime.timezone(datetime.timedelta(hours=-5))


def enviar_reporte():
    ahora = datetime.datetime.now(ZONA_HORARIA_LOCAL)
    ayer = (ahora.date() - datetime.timedelta(days=1)).isoformat()

    resultados = obtener_resultados_hoja2(fecha_str=ayer)

    if not resultados:
        msg = f"📋 <b>Resultados de ayer ({ayer})</b>\n\nNo hay resultados en Hoja2 para esta fecha."
        enviar_mensaje_telegram(msg)
        print(f"Reporte enviado sin resultados para {ayer}.")
        return

    lineas = [f"📋 <b>Resultados de ayer ({ayer})</b>\n"]

    total = len(resultados)
    aciertos = sum(1 for r in resultados if r["acierto"] is True)
    fallos = sum(1 for r in resultados if r["acierto"] is False)
    sin_evaluar = total - aciertos - fallos

    for r in resultados:
        if r["acierto"] is True:
            marca = "✅"
        elif r["acierto"] is False:
            marca = "❌"
        else:
            marca = "➖"
        pron = r.get("pronostico", "") or "?"
        res = r.get("resultado", "") or "-"
        linea = f'{marca} {escapar_html(r["local"])} vs {escapar_html(r["visitante"])}'
        linea += f' → {res}'
        if pron and pron != "?":
            linea += f' (pron: {escapar_html(pron)})'
        lineas.append(linea)

    lineas.append("")
    lineas.append(f"📊 <b>Total:</b> {aciertos}✅ {fallos}❌ {sin_evaluar}➖ de {total}")
    if aciertos + fallos > 0:
        pct = round((aciertos / (aciertos + fallos)) * 100, 1)
        lineas.append(f"🎯 <b>Efectividad:</b> {pct}%")

    exito = enviar_mensaje_telegram("\n".join(lineas))
    print(f"Reporte enviado ({total} resultados, {aciertos} aciertos)." if exito else "Fallo el envío del reporte.")


if __name__ == "__main__":
    enviar_reporte()
