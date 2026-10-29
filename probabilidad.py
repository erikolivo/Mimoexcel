"""Probabilidad calibrada del favorito a partir de "% Local" / "% Visitante".

Calibracion hecha con 9.336 partidos unicos de la hoja Seguimiento
(26-ago a 4-oct 2026), comparando el % que publica la hoja para el favorito
contra lo que realmente paso. Validada con corte temporal (calibrar con lo
anterior al 14-sep, probar con lo posterior): los tramos siguen ordenados.

Hallazgos que justifican este modulo:
- El % del favorito de la hoja esta bien calibrado para "el favorito gana"
  (error tipico de 1-3 puntos). Las cuotas no aportan informacion extra
  (correlacion 0,99 con ese %).
- La "Prioridad" de la hoja NO mide que tan probable es el resultado: solo
  27 % de las ALTA tienen favorito >= 75 %, y las ALTA aciertan 67 % de
  victorias del favorito. Por eso se recalcula aqui.
"""

# (pf_min, pf_max, p_gana_fav, p_no_pierde_fav) -- frecuencia real por tramo
TRAMOS = [
    (0.00, 0.50, 0.426, 0.696),
    (0.50, 0.55, 0.488, 0.759),
    (0.55, 0.60, 0.553, 0.790),
    (0.60, 0.65, 0.589, 0.809),
    (0.65, 0.70, 0.664, 0.862),
    (0.70, 0.75, 0.723, 0.895),
    (0.75, 0.80, 0.758, 0.904),
    (0.80, 0.90, 0.816, 0.943),
    (0.90, 1.01, 0.928, 0.987),
]

# Prioridad segun el % del favorito (probabilidad de que GANE el favorito).
# Resultado real: ALTA ~81 % (n=970), MEDIA ~68 % (n=1263), BAJA ~57 % (n=2297).
UMBRAL_ALTA = 0.75
UMBRAL_MEDIA = 0.65
UMBRAL_BAJA = 0.55

# Por debajo de este % del favorito el partido NO se vigila.
# 0.65 = "favorito claro" (gana ~74 % de las veces, ~24 % de los partidos).
# Bajalo a 0.55 si quieres incluir tambien el tramo BAJA (gana ~57 %).
PF_MIN_SEGUIMIENTO = 0.65


def a_fraccion(valor):
    """Convierte '0.80', '0,80', '80%', 80 o 0.8 a fraccion 0-1. None si no se puede."""
    if valor is None:
        return None
    try:
        numero = float(str(valor).strip().replace("%", "").replace(",", "."))
    except ValueError:
        return None
    if numero > 1:
        numero /= 100
    return numero if 0 <= numero <= 1 else None


def _tramo(pf):
    for minimo, maximo, p_gana, p_no_pierde in TRAMOS:
        if minimo <= pf < maximo:
            return p_gana, p_no_pierde
    return TRAMOS[-1][2], TRAMOS[-1][3]


def prioridad_desde_pf(pf):
    if pf >= UMBRAL_ALTA:
        return "ALTA"
    if pf >= UMBRAL_MEDIA:
        return "MEDIA"
    return "BAJA"


def evaluar(pct_local, pct_visitante, lado_favorito):
    """Devuelve un dict con la probabilidad real del favorito, o None si la
    hoja no trae los porcentajes (el llamador decide que hacer en ese caso).

    lado_favorito: 'local' o 'visitante' (el lado del pronostico de la hoja).
    """
    pl, pv = a_fraccion(pct_local), a_fraccion(pct_visitante)
    if pl is None or pv is None or lado_favorito not in {"local", "visitante"}:
        return None
    pf, pu = (pl, pv) if lado_favorito == "local" else (pv, pl)
    p_gana, p_no_pierde = _tramo(pf)
    return {
        "pf_hoja": round(pf, 3),
        "ventaja": round(pf - pu, 3),          # distancia al rival: que tan "claro" es
        "p_gana_fav": p_gana,
        "p_no_pierde_fav": p_no_pierde,
        "prioridad": prioridad_desde_pf(pf),
        "seguir": pf >= PF_MIN_SEGUIMIENTO,
    }


if __name__ == "__main__":
    casos = [("0.80", "0.09", "local"), ("0,69", "0,16", "local"), ("43%", "38%", "local"),
             ("0.25", "0.62", "visitante"), ("0.55", "0.27", "local"), (None, "0.3", "local")]
    for caso in casos:
        print(caso, "->", evaluar(*caso))
