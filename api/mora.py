# -*- coding: utf-8 -*-
"""Mora y descuento de certificados: interés simple y compuesto, lado a lado.

Juan, 2026-09-10: *«vamos a poner una nueva pestaña de cálculo de mora en pago
de certificados y descuento de certificados»*, y después: *«vamos a poner
considerar interés simple, considerar compuesto, y vemos la diferencia»*.

⚠⚠ LA DECISIÓN QUE HACE QUE EL NÚMERO SEA CIERTO
─────────────────────────────────────────────────
Se acumula la tasa **DÍA POR DÍA COMO FUE**, no una tasa promedio del período.

La tentación es tomar la TNA de hoy y multiplicarla por los días. Con tasas
argentinas eso puede errar por mucho: entre marzo y septiembre de 2026 la
BADLAR se movió varios puntos, y un certificado impago de seis meses calculado
con la tasa del último día cobra de más todos los meses en que la tasa fue más
baja — o de menos, si subió. El dato diario ya está en la base; usar un
promedio seria tirarlo.

⚠⚠ HAY DOS FAMILIAS DE SERIE Y NO SE CALCULAN IGUAL
────────────────────────────────────────────────────
    ÍNDICE   (USO_JUSTICIA, CER, UVA)   ya viene capitalizado
    TASA     (BADLAR, TAMAR, TM20, …)   es una TNA por día

Un índice YA es el resultado compuesto: `fin / inicio` da el coeficiente y no
hay nada que capitalizar. Aplicarle la fórmula de capitalización encima seria
capitalizar dos veces.

Para poder ofrecer «simple» sobre un índice hay que ir al revés: del
coeficiente se despeja la tasa diaria promedio que lo produjo, y ESA se
multiplica por los días. Es una derivación, no un dato — y se dice.

⚠ EL SIMPLE Y EL COMPUESTO NO SON DOS OPINIONES: uno es lo que dice el
contrato. La pantalla muestra los dos para que se vea cuánto está en juego,
no para elegir el que más conviene.
"""
from __future__ import annotations

import datetime as dt

# Series que son ÍNDICE ACUMULADO. Todo lo demás se trata como TNA diaria.
# ⚠ USO_JUSTICIA entra acá aunque el BCRA la etiquete «tasa de interés, en
# porcentaje»: al 2026-09-10 vale 26.984,26. Ver la nota metodologica del BCRA
# (tasmet.pdf, Comunicado 14.290) — capitaliza a diario desde el 01/04/1991.
INDICES = {"USO_JUSTICIA", "CER", "UVA", "UVI", "ICL"}

# La convención argentina para pasar de TNA a tasa diaria. Se deja explícito
# porque 360 vs 365 cambia el resultado ~1,4 % y algunos contratos dicen 360.
DIAS_ANIO = 365


def _f(x):
    if isinstance(x, dt.date):
        return x
    return dt.date.fromisoformat(str(x)[:10])


def _serie_en_rango(valores, desde, hasta):
    """[(fecha, valor)] ordenado, solo el tramo pedido."""
    d, h = _f(desde), _f(hasta)
    out = []
    for fila in valores:
        f = _f(fila["fecha"] if "fecha" in fila else fila["FECHA"])
        v = fila.get("valor", fila.get("VALOR"))
        if v is None or not (d <= f <= h):
            continue
        try:
            out.append((f, float(v)))
        except (TypeError, ValueError):
            continue
    out.sort()
    return out


def calcular(monto, desde, hasta, serie, valores, es_indice=None,
             dias_anio=DIAS_ANIO):
    """Devuelve simple y compuesto para el mismo período, con su detalle.

    `valores` es la serie cruda de la base: [{fecha, valor}, ...].
    """
    d, h = _f(desde), _f(hasta)
    if h < d:
        return {"error": "la fecha de pago es anterior a la de vencimiento"}
    dias = (h - d).days
    monto = float(monto or 0)
    if es_indice is None:
        es_indice = serie.upper() in INDICES

    tramo = _serie_en_rango(valores, d, h)
    if len(tramo) < 2:
        return {"error": "no hay datos de %s en ese rango (hacen falta al "
                         "menos dos días)" % serie}

    faltan = []
    if tramo[0][0] > d:
        faltan.append("la serie arranca el %s" % tramo[0][0])
    if tramo[-1][0] < h:
        faltan.append("el último dato es del %s" % tramo[-1][0])

    if es_indice:
        v0, v1 = tramo[0][1], tramo[-1][1]
        if not v0:
            return {"error": "el índice vale 0 en la fecha inicial"}
        coef_comp = v1 / v0
        # ⚠ DERIVADA, no un dato: la tasa diaria promedio que produjo ese
        # coeficiente. Es la única forma de ofrecer «simple» sobre un índice.
        dias_reales = (tramo[-1][0] - tramo[0][0]).days or 1
        tasa_diaria = coef_comp ** (1.0 / dias_reales) - 1
        coef_simple = 1 + tasa_diaria * dias_reales
        detalle = {
            "tipo": "indice",
            "valor_inicial": v0, "valor_final": v1,
            "tasa_diaria_promedio_pct": tasa_diaria * 100,
            "tna_equivalente_pct": tasa_diaria * dias_anio * 100,
            "nota": ("El compuesto sale directo del índice (fin ÷ inicio). El "
                     "simple es DERIVADO: se despeja la tasa diaria promedio "
                     "que produjo ese coeficiente y se multiplica por los días."),
        }
    else:
        # ⚠ Se recorre día por día. Entre dos datos consecutivos se sostiene el
        # último valor conocido (asi publica el BCRA: fines de semana y feriados
        # no traen dato nuevo, la tasa del viernes rige sábado y domingo).
        suma, prod = 0.0, 1.0
        for i in range(len(tramo) - 1):
            f_i, tna = tramo[i]
            f_j = tramo[i + 1][0]
            n = (f_j - f_i).days
            r = (tna / 100.0) / dias_anio
            suma += r * n
            prod *= (1 + r) ** n
        coef_simple = 1 + suma
        coef_comp = prod
        tnas = [v for _f_, v in tramo]
        detalle = {
            "tipo": "tasa",
            "tna_primera_pct": tnas[0], "tna_ultima_pct": tnas[-1],
            "tna_min_pct": min(tnas), "tna_max_pct": max(tnas),
            "tna_promedio_pct": sum(tnas) / len(tnas),
            "dias_con_dato": len(tramo),
            "nota": ("Se acumula la tasa de CADA día como fue publicada, no un "
                     "promedio: entre %.2f %% y %.2f %% en el período."
                     % (min(tnas), max(tnas))),
        }

    interes_simple = monto * (coef_simple - 1)
    interes_comp = monto * (coef_comp - 1)
    return {
        "serie": serie, "desde": d.isoformat(), "hasta": h.isoformat(),
        "dias": dias, "monto": monto, "dias_anio": dias_anio,
        "simple": {"coeficiente": coef_simple, "interes": interes_simple,
                   "total": monto + interes_simple,
                   "pct": (coef_simple - 1) * 100},
        "compuesto": {"coeficiente": coef_comp, "interes": interes_comp,
                      "total": monto + interes_comp,
                      "pct": (coef_comp - 1) * 100},
        # lo que está en juego entre una lectura y la otra
        "diferencia": {"interes": interes_comp - interes_simple,
                       "pct_sobre_simple": ((interes_comp / interes_simple - 1) * 100)
                       if interes_simple else 0.0},
        "detalle": detalle,
        "avisos": faltan,
    }


def descontar(monto, desde, hasta, serie, valores, es_indice=None,
              dias_anio=DIAS_ANIO):
    """Descuento de un certificado: cuánto te dan HOY por cobrarlo después.

    ⚠ NO ES LA MORA AL REVÉS CON EL MISMO SIGNO. La mora se SUMA sobre lo que
    te deben; el descuento se RESTA de lo que vas a cobrar. Con la misma tasa y
    los mismos días, el descuento da menos que la mora — porque uno se calcula
    sobre el valor de hoy y el otro sobre el del futuro.

        mora        valor_hoy * coef            (crece)
        descuento   valor_futuro / coef         (achica)

    Confundirlos hace que un certificado descontado parezca más caro (o más
    barato) de lo que es, y la diferencia crece con el plazo.
    """
    r = calcular(monto, desde, hasta, serie, valores, es_indice, dias_anio)
    if "error" in r:
        return r
    for modo in ("simple", "compuesto"):
        coef = r[modo]["coeficiente"]
        hoy = r["monto"] / coef if coef else 0.0
        r[modo] = {**r[modo], "valor_hoy": hoy,
                   "costo_del_descuento": r["monto"] - hoy,
                   "pct_del_nominal": (1 - hoy / r["monto"]) * 100 if r["monto"] else 0.0}
    r["operacion"] = "descuento"
    return r
