"""
resolucion_alertas.py
---------------------
Medicion de acierto/fallo de alertas (mejoras 2026-09, Fase A).

UNA SOLA FUENTE DE VERDAD: las mismas reglas se usan en vivo
(monitor.py, cada ciclo) y en la auditoria nocturna
(cerrar_resultados.py, _auditar_alertas). Antes habia dos criterios
distintos ("proximo gol sin ventana" en vivo vs "gol en 15 min" de
noche) y los numeros no coincidian.

Funciones puras (sin red): se pueden probar con snapshots sinteticos.

Modelo de datos (campos nuevos en alertas_enviadas, todos opcionales
para compatibilidad con JSON antiguos):
  lado: "fav" | "rival" | None (informativas)
  criterio: "siguiente_gol" | "ventana_15" | "fin_1t" | None
  estado: "pendiente" | "acierto" | "fallo" | "ambiguo" | "no_aplica"
  resuelta_minuto / resuelta_motivo / resolucion_notificada / acierto
"""

import momentum

# tipo -> (lado senalado, criterio). Un solo sitio (evita repetir el bug
# de TIPOS_PREDICCION_FAV, que no incluia varios tipos reales).
CRITERIO_POR_TIPO = {
    "posible_victoria_favorito": ("fav", "siguiente_gol"),
    "posible_empate": ("fav", "siguiente_gol"),       # alias de posible_descuento
    "posible_descuento": ("fav", "siguiente_gol"),
    "ampliacion_marcador": ("fav", "siguiente_gol"),
    "cuidado_rival_presiona": ("rival", "ventana_15"),
    "alerta_1er_tiempo": ("fav", "fin_1t"),
    "gol_de_cierre": ("fav", "siguiente_gol"),
    "fav_domina_no_gana": ("fav", "siguiente_gol"),
    "no_fav_domina": ("rival", "siguiente_gol"),
    "value_alert": ("fav", "siguiente_gol"),
    "siguen_empatados_22": ("fav", "siguiente_gol"),
    "siguen_empatados_55": ("fav", "siguiente_gol"),
    "siguen_empatados_70": ("fav", "siguiente_gol"),
    "cambio_momentum": ("fav", "siguiente_gol"),
    # tarjeta_roja: lado se setea al registrar = equipo SIN la tarjeta
    # (roja al rival → lado=fav; roja al fav → lado=rival). criterio:
    # siguiente_gol del equipo sin roja.
    "tarjeta_roja": (None, "siguiente_gol"),
    "penal": (None, None),                            # informativa (legado, desactivada 2026-09)
    "partido_resuelto": (None, None),                 # informativa (legado)
}

# Nombres antiguos -> nombre actual (une el historico en Excel/reportes).
TIPO_ALIAS = {
    "posible_empate": "posible_descuento",
}

# Etiqueta corta por tipo para los mensajes de resolucion.
ETIQUETA_TIPO = {
    "posible_victoria_favorito": "\U0001F7E2 Gana Fav",
    "posible_empate": "\U0001F7E0 Gana Fav",
    "posible_descuento": "\U0001F7E0 Posible descuento",
    "ampliacion_marcador": "\U0001F535 Pr\u00f3ximo gol: Fav",
    "cuidado_rival_presiona": "\u26A0\uFE0F Rival domina",
    "alerta_1er_tiempo": "\u23F1\uFE0F Alerta de primer tiempo",
    "gol_de_cierre": "\u23F0 Gol de cierre",
    "fav_domina_no_gana": "\U0001F526 Favorito domina",
    "no_fav_domina": "\U0001F4CA Mercado se equivoc\u00f3",
    "value_alert": "\U0001F4A1 IDV",
    "siguen_empatados_22": "\u23F1\uFE0F Siguen empatados",
    "siguen_empatados_55": "\u23F1\uFE0F Siguen empatados",
    "siguen_empatados_70": "\u23F1\uFE0F Siguen empatados",
    "cambio_momentum": "\U0001F504 Cambio de momentum",
    "tarjeta_roja": "\U0001F7E5 Tarjeta roja",
}


def _minuto_int(valor):
    try:
        return momentum._minuto_a_entero(valor)
    except Exception:
        return None


def _goles_lado(snap, favorito_es_local, lado):
    """Goles de 'fav' o 'rival' en un snapshot."""
    gl = snap.get("goles_local", 0) or 0
    gv = snap.get("goles_visitante", 0) or 0
    if lado == "fav":
        return gl if favorito_es_local else gv
    return gv if favorito_es_local else gl


def es_primer_tiempo(snap):
    """True si el snapshot es del 1T. Usa periodo si existe; si no,
    el minuto (<=45 o texto '45+...'). El descanso cuenta como 1T."""
    if not isinstance(snap, dict):
        return False
    periodo = snap.get("periodo")
    if periodo is not None:
        try:
            return int(periodo) == 1
        except (TypeError, ValueError):
            pass
    detalle = str(snap.get("estado_detalle") or "")
    if "half" in detalle.lower():
        return True
    minuto_txt = str(snap.get("minuto") or "")
    m = _minuto_int(minuto_txt)
    if m is None:
        return False
    return m <= 45 or minuto_txt.startswith("45'")


def nombre_normalizado(tipo):
    return TIPO_ALIAS.get(tipo, tipo)


def _resolver_una(alerta, lado, criterio, dfav, driv, minuto_actual,
                  snap_es_1t, terminado, cambio_final, sin_gol_es_fallo):
    """Aplica las reglas a UNA alerta pendiente. Devuelve True si cambio
    de estado. dfav/driv = goles nuevos entre snapshots. cambio_final =
    (df, dr) entre ultimo snapshot y marcador final (solo terminado)."""
    minuto_alerta = alerta.get("minuto_int")
    if minuto_alerta is None:
        minuto_alerta = _minuto_int(alerta.get("minuto"))

    if criterio == "siguiente_gol":
        if dfav > 0 or driv > 0:
            if dfav > 0 and driv > 0:
                _marcar(alerta, "ambiguo", None, minuto_actual, "ambos_marcaron")
            else:
                marco = "fav" if dfav > 0 else "rival"
                _marcar(alerta, "acierto" if marco == lado else "fallo",
                        marco == lado, minuto_actual,
                        "gol_fav" if marco == "fav" else "gol_rival")
            return True
        if terminado:
            if cambio_final is None:
                return False
            df, dr = cambio_final
            if df > 0 and dr > 0:
                _marcar(alerta, "ambiguo", None, minuto_actual, "ambos_marcaron")
            elif df > 0 or dr > 0:
                marco = "fav" if df > 0 else "rival"
                _marcar(alerta, "acierto" if marco == lado else "fallo",
                        marco == lado, minuto_actual,
                        "gol_fav" if marco == "fav" else "gol_rival")
            elif sin_gol_es_fallo:
                _marcar(alerta, "fallo", False, minuto_actual, "sin_mas_goles")
            else:
                return False
            return True
        return False

    if criterio == "ventana_15":
        if driv > 0 and minuto_actual is not None and minuto_alerta is not None \
                and minuto_actual <= minuto_alerta + 15:
            _marcar(alerta, "acierto", True, minuto_actual, "gol_rival")
            return True
        if minuto_actual is not None and minuto_alerta is not None \
                and minuto_actual > minuto_alerta + 15:
            _marcar(alerta, "fallo", False, minuto_actual, "ventana_vencida")
            return True
        if terminado:
            # Fallo, salvo gol del rival tras el ultimo snapshot dentro
            # de la ventana (comparado contra el marcador final).
            acierto = False
            if cambio_final is not None and cambio_final[1] > 0 \
                    and minuto_actual is not None and minuto_alerta is not None \
                    and minuto_actual <= minuto_alerta + 15:
                acierto = True
            _marcar(alerta, "acierto" if acierto else "fallo", acierto,
                    minuto_actual, "gol_rival" if acierto else "ventana_vencida")
            return True
        return False

    if criterio == "fin_1t":
        if dfav > 0 and snap_es_1t:
            _marcar(alerta, "acierto", True, minuto_actual, "gol_fav")
            return True
        # Los goles del primer snapshot del 2T no cuentan: si ya no es
        # 1T, fallo aunque haya gol en este snapshot.
        if not snap_es_1t:
            _marcar(alerta, "fallo", False, minuto_actual, "fin_1t")
            return True
        if terminado:
            _marcar(alerta, "fallo", False, minuto_actual, "fin_1t")
            return True
        return False

    return False


def _marcar(alerta, estado, acierto, minuto, motivo):
    alerta["estado"] = estado
    alerta["acierto"] = acierto
    alerta["resuelta_minuto"] = minuto
    alerta["resuelta_motivo"] = motivo
    alerta["resolucion_notificada"] = False


def resolver_pendientes(partido, snap_anterior, snap_actual,
                        terminado=False, marcador_final=None,
                        sin_gol_es_fallo=True):
    """Resuelve las alertas pendientes del partido con el ultimo ciclo.
    Se llama ANTES de evaluar alertas nuevas, asi una alerta enviada en
    este ciclo nunca se resuelve con un gol anterior. Devuelve la lista
    de alertas que cambiaron de estado. Muta cada alerta."""
    resueltas = []
    alertas = partido.get("alertas_enviadas", [])
    if not alertas:
        return resueltas
    favorito_es_local = partido.get("favorito_es_local", True)
    minuto_actual = _minuto_int((snap_actual or {}).get("minuto"))

    if snap_anterior is not None and snap_actual is not None:
        dfav = _goles_lado(snap_actual, favorito_es_local, "fav") \
            - _goles_lado(snap_anterior, favorito_es_local, "fav")
        driv = _goles_lado(snap_actual, favorito_es_local, "rival") \
            - _goles_lado(snap_anterior, favorito_es_local, "rival")
    else:
        dfav, driv = 0, 0
    snap_es_1t = es_primer_tiempo(snap_actual) if snap_actual else False

    cambio_final = None
    if terminado and marcador_final is not None and snap_actual is not None:
        try:
            gl_f, gv_f = marcador_final
            df = (gl_f or 0) - (snap_actual.get("goles_local", 0) or 0)
            dr = (gv_f or 0) - (snap_actual.get("goles_visitante", 0) or 0)
            if favorito_es_local:
                cambio_final = (max(0, df), max(0, dr))
            else:
                cambio_final = (max(0, dr), max(0, df))
        except Exception:
            cambio_final = None

    for alerta in alertas:
        if alerta.get("estado", "pendiente") != "pendiente":
            continue
        # Preferir lado/criterio ya guardados en la alerta (p.ej. tarjeta_roja
        # con lado dinámico = equipo sin roja); si no, caer a CRITERIO_POR_TIPO.
        lado = alerta.get("lado")
        criterio = alerta.get("criterio")
        if criterio is None:
            lado, criterio = CRITERIO_POR_TIPO.get(alerta.get("tipo"), (None, None))
        if criterio is None:
            alerta["estado"] = "no_aplica"
            alerta["acierto"] = None
            alerta["resolucion_notificada"] = True
            continue
        if _resolver_una(alerta, lado, criterio, dfav, driv, minuto_actual,
                         snap_es_1t, terminado, cambio_final, sin_gol_es_fallo):
            resueltas.append(alerta)
    return resueltas


def evaluar_alerta(historial, alerta, favorito_es_local, marcador_final=None,
                   sin_gol_es_fallo=True):
    """Version compartida para la auditoria nocturna (cerrar_resultados):
    reproduce la resolucion sobre el historial completo y devuelve
    True/False/None. No muta la alerta original."""
    import copy
    copia = copy.deepcopy(alerta)
    copia["estado"] = "pendiente"
    copia.pop("acierto", None)
    falso_partido = {"favorito_es_local": favorito_es_local,
                     "alertas_enviadas": [copia]}
    anterior = None
    for snap in historial or []:
        resolver_pendientes(falso_partido, anterior, snap,
                            sin_gol_es_fallo=sin_gol_es_fallo)
        if copia.get("estado") != "pendiente":
            break
        anterior = snap
    if copia.get("estado") == "pendiente" and historial:
        resolver_pendientes(falso_partido, anterior, historial[-1],
                            terminado=True, marcador_final=marcador_final,
                            sin_gol_es_fallo=sin_gol_es_fallo)
    return copia.get("acierto")


def tiene_trabajo_pendiente(partido):
    """True si hay alertas pendientes o resueltas sin notificar."""
    for alerta in partido.get("alertas_enviadas", []):
        if alerta.get("estado", "pendiente") == "pendiente":
            return True
        if alerta.get("estado") in ("acierto", "fallo", "ambiguo") \
                and not alerta.get("resolucion_notificada"):
            return True
    return False


def efectividad_hoy(partidos, tipo):
    """(aciertos, fallos) del tipo en los partidos dados. Unifica el
    alias posible_empate/descuento. Excluye ambiguas y pendientes."""
    clave = nombre_normalizado(tipo)
    ok = nok = 0
    for p in partidos or []:
        for a in p.get("alertas_enviadas", []):
            if nombre_normalizado(a.get("tipo")) != clave:
                continue
            if a.get("estado") == "acierto" and a.get("acierto") is True:
                ok += 1
            elif a.get("estado") == "fallo" and a.get("acierto") is False:
                nok += 1
    return ok, nok


def linea_efectividad(partidos, tipo):
    ok, nok = efectividad_hoy(partidos, tipo)
    total = ok + nok
    if not total:
        return ""
    return f"\U0001F4CA Hoy en esta alerta: {ok}/{total} ({round(ok * 100 / total)}%)"


def mensaje_resolucion(alerta, partido, contexto_marcador="", linea_stats=""):
    """Texto del mensaje de acierto/fallo/ambiguo. Todo nombre de equipo
    pasa por escapar_html (Telegram usa parse_mode HTML)."""
    from telegram_utils import escapar_html
    estado = alerta.get("estado")
    etiqueta = ETIQUETA_TIPO.get(alerta.get("tipo"), alerta.get("tipo", "alerta"))
    minuto_alerta = alerta.get("minuto", "?")
    if estado == "acierto":
        cabeza = f"\u2705 <b>ACIERTO</b> \u2014 {etiqueta} (alerta min {minuto_alerta}')"
    elif estado == "fallo":
        cabeza = f"\u274C <b>FALLO</b> \u2014 {etiqueta} (alerta min {minuto_alerta}')"
    else:
        cabeza = f"\u2796 <b>SIN DETERMINAR</b> \u2014 {etiqueta} (alerta min {minuto_alerta}')"
    local = escapar_html(partido.get("local", "?"))
    visitante = escapar_html(partido.get("visitante", "?"))
    lineas = [cabeza, f"\u26BD <b>{local}</b> vs <b>{visitante}</b>"]
    motivo = alerta.get("resuelta_motivo", "")
    if motivo in ("gol_fav", "gol_rival"):
        quien = escapar_html(partido.get("favorito", "?")) if motivo == "gol_fav" \
            else escapar_html(partido.get("no_favorito", "?"))
        res_min = alerta.get("resuelta_minuto", "?")
        lineas.append(f"Siguiente gol: {quien} (min {res_min}') \u00b7 Marcador {contexto_marcador}")
    elif motivo == "sin_mas_goles":
        lineas.append(f"Termin\u00f3 sin m\u00e1s goles \u00b7 Final {contexto_marcador}")
    elif motivo == "ventana_vencida":
        lineas.append(f"El rival no marc\u00f3 en 15 min \u00b7 Marcador {contexto_marcador}")
    elif motivo == "fin_1t":
        lineas.append(f"Lleg\u00f3 el descanso sin gol del favorito \u00b7 Marcador {contexto_marcador}")
    elif motivo == "ambos_marcaron":
        lineas.append(f"Marcaron ambos equipos entre dos lecturas \u00b7 Marcador {contexto_marcador}")
    elif contexto_marcador:
        lineas.append(f"Marcador {contexto_marcador}")
    if linea_stats:
        lineas.append(linea_stats)
    return "\n".join(lineas)
