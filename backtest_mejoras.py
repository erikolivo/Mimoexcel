#!/usr/bin/env python3
"""
backtest_mejoras.py -- prueba, sobre el historial real (data/historial_dias/*.json),
el efecto de las mejoras propuestas a cada alerta de Mimoexcel.

USO (desde la raiz del repo):
    python backtest_mejoras.py            # tabla resumen
    python backtest_mejoras.py --detalle  # + desglose y pruebas de IDV / cambio_momentum

QUE HACE
  1. Toma las alertas que el sistema realmente envio (alertas_enviadas de cada partido).
  2. Les aplica los filtros NUEVOS (REGLAS_NUEVAS). Todos los cambios propuestos son
     mas estrictos que los actuales, asi que "despues" es un subconjunto de "antes".
     (Aproximacion: no re-simula el antiduplicado de 10/30 min, que podria dejar pasar
     alguna alerta posterior que hoy se suprime.)
  3. Mide acierto con los criterios acordados:
       - "sig"  : el siguiente gol del partido lo marca el equipo señalado.
                  Si ya no hay mas goles -> FALLO (SIN_GOL_ES_FALLO=True).
       - "v15"  : (solo cuidado_rival_presiona) el rival marca en los 15 min siguientes.
       - "1T"   : (solo alerta_1er_tiempo) el favorito marca antes del fin del 1er tiempo.
  4. Calcula la BASE: probabilidad de ese mismo resultado en la misma situacion
     (marcador / tramo de minutos / tipo de pronostico) SIN alerta, usando todos los
     snapshots de los mismos partidos. Una alerta solo aporta si supera su base.
  5. Prueba aparte dos alertas que hoy estan rotas: IDV (value_alert) con el z corregido y
     cambio_momentum con el historial recortado.

DEPENDE de momentum.py del repo (solo stdlib + pandas/numpy).
"""
import ast
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.getcwd())
import momentum as M  # noqa: E402

SIN_GOL_ES_FALLO = True
VENTANA_V15 = 15
DIR_HIST = "data/historial_dias"
mi = M._minuto_a_entero


# --------------------------------------------------------------------------- utilidades
def es_1t(minstr):
    m = mi(minstr)
    return m is not None and (m <= 45 or (minstr or "").startswith("45'+"))


def goles(s, fl):
    """(goles favorito, goles rival)"""
    return (s["goles_local"], s["goles_visitante"]) if fl else (s["goles_visitante"], s["goles_local"])


def idx_en(h, m):
    r = None
    for i, s in enumerate(h):
        x = mi(s.get("minuto"))
        if x is not None and x <= m:
            r = i
    return r


def resultado_final(p, fl):
    rf = p.get("resultado_final")
    if rf in (None, "sin resolver"):
        return None
    try:
        a, b = [int(x) for x in rf.split("-")]
    except Exception:
        return None
    return (a, b) if fl else (b, a)


def siguiente_gol(h, i0, fl, final):
    """'fav' | 'rival' | 'ninguno' | 'ambiguo' | 'incompleto'"""
    for j in range(i0 + 1, len(h)):
        a, b = h[j - 1], h[j]
        dl = b["goles_local"] - a["goles_local"]
        dv = b["goles_visitante"] - a["goles_visitante"]
        if dl > 0 or dv > 0:
            if dl > 0 and dv > 0:
                return "ambiguo"
            return "fav" if ((dl > 0) if fl else (dv > 0)) else "rival"
    u = goles(h[-1], fl)
    if final:
        df_, dr_ = final[0] - u[0], final[1] - u[1]
        if df_ <= 0 and dr_ <= 0:
            return "ninguno"
        if df_ > 0 and dr_ > 0:
            return "ambiguo"
        return "fav" if df_ > 0 else "rival"
    return "ninguno" if (mi(h[-1].get("minuto")) or 0) >= 88 else "incompleto"


def gol_en_ventana(h, i0, fl, minutos=VENTANA_V15):
    m0 = mi(h[i0]["minuto"])
    lim = i0
    for j in range(i0, len(h)):
        x = mi(h[j].get("minuto"))
        if x is not None and x <= m0 + minutos:
            lim = j
    f0, r0 = goles(h[i0], fl)
    f1, r1 = goles(h[lim], fl)
    return f1 > f0, r1 > r0


def fav_marca_1t(h, i0, fl):
    g0 = goles(h[i0], fl)[0]
    ult = i0
    for j in range(i0 + 1, len(h)):
        if es_1t(h[j].get("minuto")):
            ult = j
        else:
            break
    hit = goles(h[ult], fl)[0] > g0
    if ult + 1 < len(h) and (mi(h[ult + 1].get("minuto")) or 99) <= 47:
        hit = goles(h[ult + 1], fl)[0] > g0
    return hit


def stat(s, lado, clave):
    try:
        return float(s.get("stats_" + lado, {}).get(clave, 0) or 0)
    except Exception:
        return 0.0


def zpf(hh, m, lf, lr):
    pf = M.presion_ponderada_por_tiempo(hh, m, lf)
    pr = M.presion_ponderada_por_tiempo(hh, m, lr)
    nf, sf = M.eventos_ponderados_por_tiempo(hh, m, lf)
    nr, sr = M.eventos_ponderados_por_tiempo(hh, m, lr)
    z, dom = M.z_score_dominancia(pf, pr, nf, nr, sf, sr)
    return z, pf, pr


# --------------------------------------------------------------------------- configuracion
# tipo -> (lado señalado, criterio)
TIPOS = {
    "posible_victoria_favorito": ("fav", "sig"),
    "posible_empate": ("fav", "sig"),          # pasa a llamarse posible_descuento
    "ampliacion_marcador": ("fav", "sig"),
    "cuidado_rival_presiona": ("rival", "v15"),
    "alerta_1er_tiempo": ("fav", "1T"),
    "gol_de_cierre": ("fav", "sig"),
    "fav_domina_no_gana": ("fav", "sig"),
    "no_fav_domina": ("rival", "sig"),
    "value_alert": ("fav", "sig"),
    "siguen_empatados_22": ("fav", "sig"),
    "siguen_empatados_55": ("fav", "sig"),
    "siguen_empatados_70": ("fav", "sig"),
}

# Filtros NUEVOS (r = fila de la alerta). True = la alerta se sigue enviando.
# pf/pr = presion ponderada del favorito / del rival (momentum.presion_ponderada_por_tiempo)
# z = z-score de dominancia del favorito (positivo = domina el favorito)
REGLAS_NUEVAS = {
    "posible_victoria_favorito": lambda r: r.pf >= 8,
    "posible_empate": lambda r: r.tp == "favorito_directo" and r.min <= 40,
    "ampliacion_marcador": lambda r: r.pf >= 14,
    "cuidado_rival_presiona": lambda r: (-r.z) >= 2.0 and r.sot_riv >= 2,
    "alerta_1er_tiempo": lambda r: r.tp == "favorito_directo" and r.min <= 30 and r.z >= 1.8,
    "gol_de_cierre": lambda r: r.dif in (-1, 0) and r.min <= 80 and r.z >= 3.8,
    "fav_domina_no_gana": lambda r: r.dif >= -2,
    "no_fav_domina": lambda r: r.pr >= 11 and r.dif >= 0,
    "value_alert": lambda r: False,           # apagada hasta corregir el bug del z
}

# Situacion (sin alerta) contra la que se compara cada tipo: (antes, despues) sobre la tabla BASE
def _sit(dmin, dmax, pred=None):
    def f(b):
        x = (b["min"] >= dmin) & (b["min"] <= dmax)
        return x & pred(b) if pred is not None else x
    return f

BASES = {
    "posible_victoria_favorito": (_sit(15, 74, lambda b: b.dif == 0), _sit(15, 74, lambda b: b.dif == 0)),
    "posible_empate": (_sit(15, 74, lambda b: b.dif == -1),
                       _sit(15, 40, lambda b: (b.dif == -1) & (b.tp == "favorito_directo"))),
    "ampliacion_marcador": (_sit(15, 74, lambda b: b.dif > 0), _sit(15, 74, lambda b: b.dif > 0)),
    "cuidado_rival_presiona": (_sit(15, 74), _sit(15, 74)),
    "alerta_1er_tiempo": (_sit(15, 40, lambda b: (b.gf0 == 0) & (b.gr0 == 0)),
                          _sit(15, 30, lambda b: (b.gf0 == 0) & (b.gr0 == 0) & (b.tp == "favorito_directo"))),
    "gol_de_cierre": (_sit(75, 89), _sit(75, 80, lambda b: b.dif.isin([-1, 0]))),
    "fav_domina_no_gana": (_sit(15, 74, lambda b: b.dif <= 0), _sit(15, 74, lambda b: (b.dif <= 0) & (b.dif >= -2))),
    "no_fav_domina": (_sit(15, 74), _sit(15, 74, lambda b: b.dif >= 0)),
    "value_alert": (_sit(5, 74), _sit(5, 74)),
    "siguen_empatados_22": (_sit(22, 54, lambda b: b.dif == 0), _sit(22, 54, lambda b: b.dif == 0)),
    "siguen_empatados_55": (_sit(55, 69, lambda b: b.dif == 0), _sit(55, 69, lambda b: b.dif == 0)),
    "siguen_empatados_70": (_sit(70, 89, lambda b: b.dif == 0), _sit(70, 89, lambda b: b.dif == 0)),
}


# --------------------------------------------------------------------------- carga
def cargar():
    alertas, base, partidos = [], [], []
    for f in sorted(glob.glob(f"{DIR_HIST}/*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for p in d["partidos"]:
            h = p.get("historial_snapshots", [])
            if len(h) < 2:
                continue
            fl = p["favorito_es_local"]
            lf, lr = ("local", "visitante") if fl else ("visitante", "local")
            fin = resultado_final(p, fl)
            partidos.append((d["fecha"], p, h, fl, fin))
            for i, s in enumerate(h):
                m = mi(s.get("minuto"))
                if m is None or m < 5 or m > 89:
                    continue
                gf, gr = goles(s, fl)
                f15, r15 = gol_en_ventana(h, i, fl)
                d1 = fav_marca_1t(h, i, fl) if (gf == 0 and gr == 0 and es_1t(s["minuto"]) and m <= 40) else np.nan
                base.append(dict(min=m, dif=gf - gr, gf0=gf, gr0=gr, r=siguiente_gol(h, i, fl, fin),
                                 fav15=f15, riv15=r15, d1=d1, tp=p.get("tipo_pronostico")))
            for a in p.get("alertas_enviadas", []):
                t = a["tipo"]
                if t not in TIPOS:
                    continue
                m = mi(a["minuto"])
                i0 = idx_en(h, m) if m is not None else None
                if i0 is None:
                    continue
                s0 = h[i0]
                gf, gr = goles(s0, fl)
                z, pf, pr = zpf(h[: i0 + 1], m, lf, lr)
                lado, crit = TIPOS[t]
                if crit == "sig":
                    r = siguiente_gol(h, i0, fl, fin)
                    if r in ("ambiguo", "incompleto"):
                        hit = np.nan
                    elif r == "ninguno":
                        hit = 0.0 if SIN_GOL_ES_FALLO else np.nan
                    else:
                        hit = float(r == lado)
                elif crit == "v15":
                    f15, r15 = gol_en_ventana(h, i0, fl)
                    hit = float(r15 if lado == "rival" else f15)
                else:
                    hit = float(fav_marca_1t(h, i0, fl))
                alertas.append(dict(fecha=d["fecha"], partido=p["partido"], tipo=t, min=m, dif=gf - gr, z=z, pf=pf, pr=pr,
                                    sot_fav=stat(s0, lf, "shotsOnTarget"), sot_riv=stat(s0, lr, "shotsOnTarget"),
                                    tp=p.get("tipo_pronostico"), prio=p.get("prioridad"), hit=hit))
    return pd.DataFrame(alertas), pd.DataFrame(base), partidos


def base_hit(B, t, sit):
    lado, crit = TIPOS[t]
    b = B[sit(B)]
    if crit == "sig":
        b = b[b.r.isin(["fav", "rival", "ninguno"])]
        return (b.r == lado).mean() if len(b) else np.nan, len(b)
    if crit == "v15":
        return b.riv15.mean() if len(b) else np.nan, len(b)
    b = b[b.d1.notna()]
    return b.d1.astype(float).mean() if len(b) else np.nan, len(b)


def pct(x):
    return "  -  " if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:4.0f}%"


# --------------------------------------------------------------------------- tabla principal
def tabla(A, B):
    A = A[A.hit.notna()].copy()
    fechas = sorted(A.fecha.unique())
    nd = len(fechas)
    mitad = set(fechas[: nd // 2])
    filas = []
    for t in TIPOS:
        a = A[A.tipo == t]
        if a.empty:
            continue
        regla = REGLAS_NUEVAS.get(t)
        d = a[[bool(regla(r)) if regla else True for r in a.itertuples()]]
        # Límite global de minuto (mejora 2026-09): nada después del 80
        # salvo gol_de_cierre (ventana propia hasta 80 con CIERRE_MAX_MINUTO).
        d = d[(d["min"] <= 80) | (d.tipo == "gol_de_cierre")]
        b_ant = base_hit(B, t, BASES[t][0])[0]
        b_des = base_hit(B, t, BASES[t][1])[0]
        h1 = d[d.fecha.isin(mitad)].hit
        h2 = d[~d.fecha.isin(mitad)].hit
        filas.append(dict(tipo=t, n_ant=len(a), n_des=len(d), dia_ant=len(a) / nd, dia_des=len(d) / nd,
                          hit_ant=a.hit.mean(), hit_des=d.hit.mean() if len(d) else np.nan,
                          base_ant=b_ant, base_des=b_des,
                          h1=h1.mean() if len(h1) else np.nan, n1=len(h1),
                          h2=h2.mean() if len(h2) else np.nan, n2=len(h2)))
    T = pd.DataFrame(filas)
    print(f"Dias analizados: {nd}  ({fechas[0]} a {fechas[-1]})   sin gol = {'FALLO' if SIN_GOL_ES_FALLO else 'excluido'}\n")
    print(f"{'alerta':28s} {'alertas/dia':>13s} {'acierto':>13s} {'base (situacion)':>17s} {'lift':>5s}   1a mitad / 2a mitad (despues)")
    for r in T.itertuples():
        lift = r.hit_des / r.base_des if r.n_des and r.base_des else float("nan")
        print(f"{r.tipo:28s} {r.dia_ant:5.1f} -> {r.dia_des:4.1f}   {pct(r.hit_ant)} -> {pct(r.hit_des)}   "
              f"{pct(r.base_ant)} -> {pct(r.base_des)}  {lift:4.2f}x   {pct(r.h1)} (n={r.n1}) / {pct(r.h2)} (n={r.n2})")
    tot_a, tot_d = T.dia_ant.sum(), T.dia_des.sum()
    print(f"\nTOTAL alertas/dia (solo estos tipos): {tot_a:.1f} -> {tot_d:.1f}  ({(1 - tot_d / tot_a) * 100:.0f}% menos)")
    return T


# --------------------------------------------------------------------------- IDV y cambio_momentum
def _cargar_idv(src):
    """Extrae _to_float y _calcular_idv de monitor.py SIN importar monitor (evita efectos secundarios)."""
    tree = ast.parse(src)
    ns = {"momentum": M, "UMBRAL_IDV_BAJO": 2, "UMBRAL_IDV_MEDIO": 5, "UMBRAL_IDV_ALTO": 10, "MINUTOS_MINIMOS_IDV": 5}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in ns for t in node.targets):
            exec(ast.get_source_segment(src, node), ns)
    codigo = {n.name: ast.get_source_segment(src, n) for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in ("_to_float", "_calcular_idv")}
    exec(codigo["_to_float"], ns)
    buggy = dict(ns); exec(codigo["_calcular_idv"], buggy)
    fixed_src = codigo["_calcular_idv"].replace("dominancia_pct, z = momentum.z_score_dominancia(",
                                                "z, dominancia_pct = momentum.z_score_dominancia(")
    assert fixed_src != codigo["_calcular_idv"], "no se encontro el desempaquetado a corregir"
    fixed = dict(ns); exec(fixed_src, fixed)
    return buggy["_calcular_idv"], fixed["_calcular_idv"]


def prueba_idv(partidos, B):
    try:
        f_bug, f_fix = _cargar_idv(open("monitor.py", encoding="utf-8").read())
    except Exception as e:  # pragma: no cover
        print(f"[IDV] no se pudo cargar _calcular_idv: {e}")
        return
    print("\n=== IDV (value_alert): version actual (bug) vs z corregido ===")
    for nombre, fn in (("actual (bug)", f_bug), ("z corregido", f_fix)):
        res = []
        for fecha, p, h, fl, fin in partidos:
            ultimo = -999
            for i, s in enumerate(h):
                m = mi(s.get("minuto"))
                if m is None or m < 5 or m >= 75:
                    continue
                try:
                    d = fn(p, s, h[: i + 1], m)
                except Exception:
                    d = None
                if d and abs(m - ultimo) > 30:
                    ultimo = m
                    r = siguiente_gol(h, i, fl, fin)
                    if r not in ("ambiguo", "incompleto"):
                        res.append((d["idv"], float(r == "fav")))
        R = pd.DataFrame(res, columns=["idv", "hit"])
        nd = len({x[0] for x in partidos})
        if R.empty:
            print(f"  {nombre:14s}: 0 alertas")
            continue
        print(f"  {nombre:14s}: {len(R) / nd:4.1f} alertas/dia  acierto {R.hit.mean() * 100:.0f}% (n={len(R)})   "
              f"IDV>=5: {R[R.idv >= 5].hit.mean() * 100 if (R.idv >= 5).any() else float('nan'):.0f}% (n={(R.idv >= 5).sum()})")
    b = B[(B["min"] >= 5) & (B["min"] <= 74) & B.r.isin(["fav", "rival", "ninguno"])]
    print(f"  base (min 5-74, el fav marca el siguiente gol; sin gol = fallo): {(b.r == 'fav').mean() * 100:.0f}%")


def prueba_cambio_momentum(partidos, B):
    print("\n=== cambio_momentum: historial recortado a minuto-5 (version corregida) ===")
    res = []
    for fecha, p, h, fl, fin in partidos:
        lf, lr = ("local", "visitante") if fl else ("visitante", "local")
        ultimo = -999
        for i, s in enumerate(h):
            m = mi(s.get("minuto"))
            if m is None or m < 15 or m >= 75 or i < 2:
                continue
            hp = [x for x in h[: i + 1] if (mi(x.get("minuto")) or 0) <= m - 5]
            if len(hp) < 1:
                continue
            z_act = zpf(h[: i + 1], m, lf, lr)[0]
            z_prev = zpf(hp, m - 5, lf, lr)[0]
            if abs(z_act - z_prev) >= 1.5 and abs(m - ultimo) > 10:
                ultimo = m
                lado = "fav" if z_act > z_prev else "rival"
                r = siguiente_gol(h, i, fl, fin)
                if r not in ("ambiguo", "incompleto"):
                    res.append((lado, float(r == lado)))
    R = pd.DataFrame(res, columns=["lado", "hit"])
    nd = len({x[0] for x in partidos})
    if R.empty:
        print("  0 alertas")
        return
    print(f"  {len(R) / nd:.1f} alertas/dia, acierto {R.hit.mean() * 100:.0f}% (n={len(R)})")
    for lado, g in R.groupby("lado"):
        b = B[(B['min'].between(15, 74)) & B.r.isin(['fav', 'rival', 'ninguno'])]
        print(f"   señala {lado:5s}: acierto {g.hit.mean() * 100:.0f}% (n={len(g)})  base {(b.r == lado).mean() * 100:.0f}%")


def detalle(A):
    A = A[A.hit.notna()]
    print("\n=== desglose fav_domina_no_gana por marcador (despues del tope dif>=-2) ===")
    g = A[(A.tipo == "fav_domina_no_gana") & (A.dif >= -2)]
    print(g.groupby("dif").hit.agg(["size", "mean"]).round(2).T.to_string())
    print("\n=== gol_de_cierre: antes vs reglas parciales ===")
    g = A[A.tipo == "gol_de_cierre"]
    for nombre, f in [("actual", lambda x: x.z >= 0), ("solo dif -1/0", lambda x: x.dif.isin([-1, 0])),
                      ("+ min<=80", lambda x: x.dif.isin([-1, 0]) & (x["min"] <= 80)),
                      ("+ z>=3.8 (regla nueva)", lambda x: x.dif.isin([-1, 0]) & (x["min"] <= 80) & (x.z >= 3.8))]:
        s = g[f(g)]
        print(f"  {nombre:26s} n={len(s):2d}  acierto={s.hit.mean() * 100:3.0f}%")


if __name__ == "__main__":
    A, B, partidos = cargar()
    T = tabla(A, B)
    if "--detalle" in sys.argv:
        detalle(A)
        prueba_idv(partidos, B)
        prueba_cambio_momentum(partidos, B)
