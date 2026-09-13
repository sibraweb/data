# -*- coding: utf-8 -*-
"""Descuento de Certificados de Obra Pública — el índice diario, como lo arma
el Banco Nación (y como lo publica CAMARCO).

Juan, 2026-09-10, después de ver que la pestaña de Mora daba distinto a la
planilla de CAMARCO: *«hagamos entonces una tabla especifica de esto»*.

⚠⚠ POR QUÉ ESTO NO PODÍA SER UNA TASA MÁS DE LA PESTAÑA DE MORA
────────────────────────────────────────────────────────────────
Porque la conversión de TNA a tasa diaria es OTRA. `mora.py` usa la
convención bancaria común:

    i_d = TNA / 365

y esta serie usa la del Banco Nación, que pasa primero por una tasa MENSUAL:

    TNM = TNA * 30 / 365
    i_d = (1 + TNM) ** (1/30) - 1

Con TNA 30 % la primera da 0,0821918 % diario y la segunda 0,0812278 %. La
diferencia es una diezmilésima por día — y sobre los 1.478 días que van de
abril 2022 a abril 2026 se convierte en 1,4 % a 10 % del interés, según el
nivel de tasa. No es un redondeo: es la diferencia entre que el número cierre
con el de la contraparte o no cierre.

La fórmula está VERIFICADA contra una fila publicada de CAMARCO (Grandes
Inversores, TNA 30 %, TNM 2,47 %):

    28/02   índice 168,768895
    29/02   índice 168,905982
    168,768895 * (1 + 0,000812278) = 168,905982   ✓ a seis decimales

⚠ DE DÓNDE SALE LA TASA — Y POR QUÉ NO DEPENDEMOS DE CAMARCO
─────────────────────────────────────────────────────────────
Ley 13.064 art. 48: ante atraso en el pago de certificados corresponde «la
tasa fijada por el Banco de la Nación Argentina para los descuentos sobre
certificados de obra». No dice CAMARCO. CAMARCO COMPILA la serie y la publica
tras un login de socios; la tasa de origen es pública (BCRA) y la regla que
la convierte también (BNA / Boletín Oficial).

Así que el índice se reconstruye acá: TAMAR del BCRA + el spread que fijó el
BNA, capitalizado día por día. Sale el mismo número, sin login.

⚠ EL ÍNDICE CORRE POR DÍAS CALENDARIO, NO POR HÁBILES. Sábados, domingos y
feriados capitalizan con la última tasa vigente. Lo que sí se cuenta en
hábiles es el DESFASAJE de 5 días con que se lee la TAMAR.

⚠ ANTES DEL 09/12/2024 NO TENEMOS RÉGIMEN CONFIRMADO. Y no se inventa: el
motor avisa y pide que el tramo viejo se declare a mano (ver `REGIMENES` y el
parámetro `regimen_previo`). Un número calculado con una regla supuesta es
peor que no tener número, porque después nadie se acuerda de que era supuesta.
"""
from __future__ import annotations

import bisect
import datetime as dt

# Convención del BNA. Se dejan nombrados y no incrustados porque son
# exactamente los dos números que hacen que esto difiera de `mora.py`.
DIAS_MES = 30
DIAS_ANIO = 365

# ── LOS REGÍMENES DE TASA ───────────────────────────────────────────────────
# Cada tramo dice: sobre qué serie del BCRA se para, cuánto spread le suma el
# BNA, con cuántos días hábiles de atraso se lee la serie, y CON QUÉ COLOR se
# pinta en la pantalla.
#
# ⚠ `norma` y `fuente` no son decorativos: son lo que se contesta cuando
# alguien pregunta "de dónde sacaste el 6,50". Si un tramo no tiene fuente,
# no va.
#
# ⚠ `confirmado` es la diferencia entre un número que se defiende y uno que se
# aclara. True = el aviso del BNA está verificado. False = está relevado pero
# no lo vimos publicado; el número sale igual, con cartel.
#
# ⚠ EL COLOR ES DEL RÉGIMEN, NO DE LA SERIE. Dos tramos sobre la misma TAMAR
# con distinto spread son dos reglas distintas y tienen que verse distintas:
# lo que se audita es el día en que cambió la regla, no la serie.
REGIMENES = [
    {
        "id": "badlar-28",
        "desde": "2018-12-06", "hasta": "2019-08-25",
        "base": "BADLAR",
        "base_detalle": "BADLAR bancos privados, TNA — BCRA variable 7",
        "spread_pp": 28.00, "spread_pp_mipyme": 25.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (2)",
        "color": "#7C4A0F",
    },
    {
        "id": "badlar-23",
        "desde": "2019-08-26", "hasta": "2021-03-14",
        "base": "BADLAR",
        "base_detalle": "BADLAR bancos privados, TNA — BCRA variable 7",
        "spread_pp": 23.00, "spread_pp_mipyme": 20.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (3)",
        "color": "#A6691A",
    },
    {
        "id": "badlar-10",
        "desde": "2021-03-15", "hasta": "2024-12-08",
        "base": "BADLAR",
        "base_detalle": "BADLAR bancos privados, TNA — BCRA variable 7",
        "spread_pp": 10.00, "spread_pp_mipyme": 5.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (4)",
        "color": "#C9902F",
    },
    {
        "id": "tamar-7",
        "desde": "2024-12-09", "hasta": "2025-08-19",
        "base": "TAMAR",
        "base_detalle": "TAMAR bancos privados, TNA — BCRA variable 44",
        "spread_pp": 7.00, "spread_pp_mipyme": 2.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (5)",
        "color": "#1F5FB7",
    },
    {
        "id": "tamar-9",
        "desde": "2025-08-20", "hasta": "2025-09-30",
        "base": "TAMAR",
        "base_detalle": "TAMAR bancos privados, TNA — BCRA variable 44",
        "spread_pp": 9.00, "spread_pp_mipyme": 7.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (6)",
        "color": "#3C7FD4",
    },
    {
        "id": "tamar-19",
        "desde": "2025-10-01", "hasta": "2025-11-19",
        "base": "TAMAR",
        "base_detalle": "TAMAR bancos privados, TNA — BCRA variable 44",
        "spread_pp": 19.00, "spread_pp_mipyme": 17.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (7)",
        "color": "#6B3FA0",
    },
    {
        "id": "tamar-17",
        "desde": "2025-11-20", "hasta": "2025-12-02",
        "base": "TAMAR",
        "base_detalle": "TAMAR bancos privados, TNA — BCRA variable 44",
        "spread_pp": 17.00, "spread_pp_mipyme": 15.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (8)",
        "color": "#8B5FB8",
    },
    {
        "id": "tamar-15",
        "desde": "2025-12-03", "hasta": "2026-01-27",
        "base": "TAMAR",
        "base_detalle": "TAMAR bancos privados, TNA — BCRA variable 44",
        "spread_pp": 15.00, "spread_pp_mipyme": 13.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (9)",
        "color": "#A87FCF",
    },
    {
        "id": "tamar-650",
        "desde": "2026-01-28", "hasta": None,
        "base": "TAMAR",
        "base_detalle": "TAMAR bancos privados, TNA — BCRA variable 44",
        "spread_pp": 6.50, "spread_pp_mipyme": 6.00,
        "lag_habiles": 5, "confirmado": True,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1 — tasa del BNA para préstamos con caución de certificados de obra",
        "fuente": "CAMARCO, «Evolución histórica de tasas Banco Nación 2018 – septiembre 2026», notas al pie — elaboración propia en base a BCRA y BNA, nota (10)",
        "color": "#1A7A4A",
    },
]

# Color de los días que caen fuera de todo régimen. No es un régimen más: es
# el hueco, y se tiene que ver como hueco.
COLOR_SIN_REGIMEN = "#c02020"

# ⚠ LAS VARIANTES QUE LOS AVISOS NO DEFINEN (relevado 2026-09-11)
# El aviso del BNA dice "TAMAR" y no dice cuál. El BCRA publica dos, y el
# desfasaje tampoco está escrito como promedio o como valor puntual:
#
#   44  TAMAR bancos privados            ← la que usamos
#   135 TAMAR bancos públicos y privados
#   7   BADLAR bancos privados           ← la que usamos
#   138 BADLAR bancos públicos y privados
#
# Se eligió "bancos privados" y "valor puntual del quinto día hábil" porque
# esa combinación es la que reproduce exacto el dato público de CAMARCO
# (ver el punto de control de abajo). Si algún día deja de cerrar, ESTA es la
# lista de las cuatro cosas que hay que probar antes de tocar la fórmula.
VARIANTES_ABIERTAS = [
    "TAMAR de bancos privados (44) vs. públicos y privados (135)",
    "el quinto día hábil como valor puntual vs. promedio de los 5 hábiles",
    "BADLAR de bancos privados (7) vs. públicos y privados (138)",
    "período por mes calendario vs. los cortes que usa CAMARCO (27/01, 24/02…)",
]

# Antes de esta fecha no hay régimen confirmado en el repo. Ver el aviso de
# arriba: se declara a mano o no se calcula.
PRIMER_REGIMEN = REGIMENES[0]["desde"]


def _f(x) -> dt.date:
    if isinstance(x, dt.date):
        return x
    return dt.date.fromisoformat(str(x)[:10])


def _serie_dict(valores):
    """[{FECHA, VALOR}] -> (fechas ordenadas, {fecha: valor}).

    Las fechas que la serie TRAE son los días hábiles: el BCRA no publica
    sábados, domingos ni feriados. Por eso no hace falta un calendario de
    feriados para contar «5 días hábiles antes» — se cuenta sobre esta lista.
    """
    d = {}
    for fila in valores or []:
        f = fila.get("FECHA", fila.get("fecha"))
        v = fila.get("VALOR", fila.get("valor"))
        if f is None or v is None:
            continue
        try:
            d[_f(f)] = float(v)
        except (TypeError, ValueError):
            continue
    return sorted(d), d


def _tna_con_lag(fecha, fechas, valores, lag_habiles):
    """TNA base vigente para `fecha`, leída `lag_habiles` hábiles antes.

    Devuelve (tna, fecha_del_dato) o (None, None) si no hay historia
    suficiente hacia atrás.
    """
    i = bisect.bisect_right(fechas, fecha) - 1  # último hábil <= fecha
    if i < 0:
        return None, None
    j = i - lag_habiles
    if j < 0:
        return None, None
    f = fechas[j]
    return valores[f], f


def _regimen_de(fecha, regimenes):
    for r in regimenes:
        d = _f(r["desde"])
        h = _f(r["hasta"]) if r.get("hasta") else None
        if fecha >= d and (h is None or fecha <= h):
            return r
    return None


def tasa_diaria(tna_pct):
    """La conversión del BNA: TNA -> TNM -> tasa efectiva diaria.

    ⚠ Es ESTA función la que separa este módulo de `mora.py`. Tocarla cambia
    todos los números; verificarla contra la fila de CAMARCO del encabezado.
    """
    tnm = (tna_pct / 100.0) * DIAS_MES / DIAS_ANIO
    return (1 + tnm) ** (1.0 / DIAS_MES) - 1, tnm


def _spread_de(r, mipyme):
    """Spread del tramo, con el de MiPyME si corresponde.

    ⚠ El spread MiPyME solo está confirmado desde el 28/01/2026. Para el tramo
    anterior se usa el de no-MiPyME y SE AVISA: es preferible un número con
    cartel que un número calculado con un spread inventado.
    """
    if not mipyme:
        return float(r.get("spread_pp") or 0), None
    s = r.get("spread_pp_mipyme")
    if s is None:
        return float(r.get("spread_pp") or 0), (
            "el spread MiPyME del tramo que arranca el %s no está confirmado: "
            "se usó el de no-MiPyME (+%.2f)" % (r["desde"], r.get("spread_pp") or 0))
    return float(s), None


# Color de los días que se calculan con TNA relevada en vez de reconstruida.
COLOR_TNA_RELEVADA = "#7A5CA8"


def serie_indice(desde, hasta, series_base, regimenes=None, base=100.0,
                 regimen_previo=None, mipyme=False, tna_relevada=None):
    """Arma el índice diario acumulado entre dos fechas, día por día.

    `series_base` es {"TAMAR": [{FECHA, VALOR}...], "BADLAR": [...]} — se le
    acercan las series crudas de la base y el motor elige según el régimen.

    `regimen_previo`, si viene, cubre lo anterior al 09/12/2024. Queda marcado
    `confirmado: False` para que la pantalla lo diga.

    Devuelve {filas, avisos, regimenes_usados}. Cada fila:
        {fecha, tna, tnm_pct, tasa_diaria_pct, indice, base, fecha_tasa}

    ⚠ La fila de la fecha `d` muestra el índice AL INICIO de `d` y la tasa que
    rige DE `d` A `d+1` — así lo publica CAMARCO (la fila del 28/02 lleva el
    índice del 28 y la tasa que produce el del 29).
    """
    d, h = _f(desde), _f(hasta)
    if h < d:
        return {"error": "la fecha final es anterior a la inicial"}

    regs = list(regimenes or REGIMENES)
    if regimen_previo:
        regs = [regimen_previo] + regs

    cache = {}
    for clave, valores in (series_base or {}).items():
        cache[clave.upper()] = _serie_dict(valores)
    _, rel = _serie_dict(tna_relevada or [])

    filas, avisos, usados = [], [], []
    indice = float(base)
    sin_regimen = sin_dato = 0
    dia = d
    while dia <= h:
        r = _regimen_de(dia, regs)
        # ⚠⚠ LA TASA Y EL ÍNDICE SON DOS COSAS DISTINTAS, y separarlas es lo que
        # permite tener serie propia desde el 01/01/2018. La TACG no se puede
        # RECONSTRUIR (no hay fórmula: la fija el BNA), pero sí está RELEVADA
        # como serie de TNA. Entonces el insumo se lee y el índice lo calculamos
        # nosotros con nuestra fórmula, desde base 100, igual que el resto.
        # No es lo mismo que copiar el índice de CAMARCO: ese ya viene calculado
        # y acumulado desde 1991. Acá la única cosa que ponen ellos es la tasa
        # del día, que es un dato, no un cálculo.
        tna_rel = rel.get(dia) if rel else None
        if r is None and tna_rel is not None:
            i_d, tnm = tasa_diaria(tna_rel)
            filas.append({
                "fecha": dia.isoformat(), "tna": tna_rel, "tnm_pct": tnm * 100,
                "tasa_diaria_pct": i_d * 100, "indice": indice,
                "base": "TNA RELEVADA", "fecha_tasa": dia.isoformat(),
                "spread_pp": None, "confirmado": True,
                "regimen_id": "tna-relevada", "color": COLOR_TNA_RELEVADA,
            })
            if dia < h:
                indice *= (1 + i_d)
            dia += dt.timedelta(days=1)
            continue
        if r is None:
            sin_regimen += 1
            filas.append({"fecha": dia.isoformat(), "tna": None, "tnm_pct": None,
                          "tasa_diaria_pct": None, "indice": indice,
                          "base": None, "fecha_tasa": None, "confirmado": None,
                          "regimen_id": None, "color": COLOR_SIN_REGIMEN})
            dia += dt.timedelta(days=1)
            continue

        clave = str(r["base"]).upper()
        if clave not in cache:
            avisos.append("falta la serie %s en la base" % clave)
            break
        fechas, valores = cache[clave]
        tna_base, f_tasa = _tna_con_lag(dia, fechas, valores,
                                        int(r.get("lag_habiles", 0)))
        if tna_base is None:
            sin_dato += 1
            filas.append({"fecha": dia.isoformat(), "tna": None, "tnm_pct": None,
                          "tasa_diaria_pct": None, "indice": indice,
                          "base": clave, "fecha_tasa": None,
                          "confirmado": r.get("confirmado", True),
                          "regimen_id": r.get("id"),
                          "color": r.get("color", COLOR_SIN_REGIMEN)})
            dia += dt.timedelta(days=1)
            continue

        spread, aviso_spread = _spread_de(r, mipyme)
        if aviso_spread and aviso_spread not in avisos:
            avisos.append(aviso_spread)
        tna = tna_base + spread
        i_d, tnm = tasa_diaria(tna)
        filas.append({
            "fecha": dia.isoformat(), "tna": tna, "tnm_pct": tnm * 100,
            "tasa_diaria_pct": i_d * 100, "indice": indice,
            "base": clave, "fecha_tasa": f_tasa.isoformat(),
            "spread_pp": spread,
            "confirmado": r.get("confirmado", True) and not aviso_spread,
            "regimen_id": r.get("id"),
            "color": r.get("color", COLOR_SIN_REGIMEN),
        })
        if r not in usados:
            usados.append(r)
        if dia < h:            # el último día no capitaliza: ese día se cobra
            indice *= (1 + i_d)
        dia += dt.timedelta(days=1)

    if filas:
        filas[-1]["indice"] = indice

    if sin_regimen:
        avisos.append(
            "%d días sin régimen de tasa confirmado (anteriores al %s). Esos "
            "días NO capitalizan: el coeficiente está incompleto."
            % (sin_regimen, PRIMER_REGIMEN))
    if sin_dato:
        avisos.append("%d días sin dato de la serie base (no alcanza la "
                      "historia hacia atrás para el desfasaje)" % sin_dato)

    return {"filas": filas, "avisos": avisos, "regimenes_usados": usados}


def _plata(monto, coef, modo):
    """La misma plata, leída en los dos sentidos.

    `modo="descuento"` divide en vez de multiplicar: el certificado vale
    `monto` EN LA FECHA FINAL y se quiere saber cuánto dan hoy. No es la mora
    al revés con el mismo signo — sobre el mismo coeficiente, descontar da
    menos que la mora, porque uno se aplica sobre el valor de hoy y el otro
    sobre el del futuro.
    """
    monto = float(monto or 0)
    if modo == "descuento":
        hoy = monto / coef if coef else 0.0
        return {"coeficiente": coef, "valor_hoy": hoy, "costo": monto - hoy,
                "pct_del_nominal": (1 - hoy / monto) * 100 if monto else 0.0,
                "interes": monto - hoy, "total": hoy,
                "pct": (1 - hoy / monto) * 100 if monto else 0.0}
    interes = monto * (coef - 1)
    return {"coeficiente": coef, "interes": interes, "total": monto + interes,
            "pct": (coef - 1) * 100, "valor_hoy": monto + interes,
            "costo": interes, "pct_del_nominal": (coef - 1) * 100}


def _tramos(filas):
    """Corta la serie en los tramos de régimen y le pone plata a cada uno.

    ⚠ ES EL DESGLOSE QUE HACE QUE LOS COLORES SIGNIFIQUEN ALGO. Pintar filas
    de tres colores sin decir cuánto aportó cada tramo es decoración; con el
    coeficiente al lado, la pantalla contesta "de este 4,18 final, 3,21 lo
    puso BADLAR+10 antes de diciembre de 2024".

    El coeficiente del tramo va del índice al INICIO de su primer día al
    índice al inicio del primer día del tramo siguiente — así los tramos
    multiplicados dan exacto el coeficiente total, sin días contados dos
    veces ni días perdidos en el borde.
    """
    if not filas:
        return []
    cortes, ini = [], 0
    for k in range(1, len(filas)):
        if filas[k].get("regimen_id") != filas[ini].get("regimen_id"):
            cortes.append((ini, k - 1))
            ini = k
    cortes.append((ini, len(filas) - 1))

    out = []
    for a, b in cortes:
        f0 = filas[a]
        i0 = f0["indice"]
        i1 = filas[b + 1]["indice"] if b + 1 < len(filas) else filas[-1]["indice"]
        # El último día del rango no capitaliza: no suma su tasa al simple.
        hasta_simple = min(b, len(filas) - 2)
        simple = sum((filas[k]["tasa_diaria_pct"] or 0) / 100.0
                     for k in range(a, hasta_simple + 1)) if hasta_simple >= a else 0.0
        tnas = [filas[k]["tna"] for k in range(a, b + 1) if filas[k]["tna"] is not None]
        out.append({
            "regimen_id": f0.get("regimen_id"),
            "color": f0.get("color"),
            "desde": f0["fecha"], "hasta": filas[b]["fecha"],
            "dias": b - a + 1,
            "base": f0.get("base"), "spread_pp": f0.get("spread_pp"),
            "confirmado": f0.get("confirmado"),
            "indice_inicial": i0, "indice_final": i1,
            "coeficiente": (i1 / i0) if i0 else 1.0,
            "coeficiente_sin_capitalizar": 1 + simple,
            "aporte_simple_pct": simple * 100,
            "tna_primera": tnas[0] if tnas else None,
            "tna_ultima": tnas[-1] if tnas else None,
            "tna_min": min(tnas) if tnas else None,
            "tna_max": max(tnas) if tnas else None,
        })
    return out


# ── LA FUENTE PUBLICADA ─────────────────────────────────────────────────────
# Juan, 2026-09-11: *«desde enero de 2018 podemos mirar??»*. Sí, pero NO
# reconstruyendo.
#
# ⚠⚠ DEL 01/01/2018 AL 05/12/2018 NO HAY NADA QUE RECONSTRUIR. La base de esos
# días es la Tasa Activa de Cartera General del BNA (TACG), y la TACG no se
# arma con una fórmula: la fija el banco y la publica porque el decreto
# 13.477/56 art. 1º lo obliga. Se probaron siete series del BCRA contra esos
# 197 días (BADLAR privados y total, TM20, adelantos, personales, plazo fijo)
# y NINGUNA la explica: todas dan ~10 p.p. de desvío, o sea que no existe un
# spread constante que la reproduzca. Es tasa administrada, no de mercado.
#
# Por eso, para ese tramo, la única fuente posible es el índice PUBLICADO. Y ya
# que está, el publicado es mejor que la reconstrucción en todo el resto
# también: es exacto y es lo que la contraparte puede mirar.
#
# **El reparto:** publicado manda mientras haya dato; la reconstrucción extiende
# más allá de la última fecha publicada y hace de control cruzado.
# La reconstrucción cierra contra el publicado con 0,06 %–0,13 % en ocho años,
# y 0,00 % en el régimen vigente.
#
# ⚠ EL ÍNDICE PUBLICADO NO ARRANCA EN 100. Al 01/01/2018 vale 220,933113
# (MiPyME) y 270,902723 (Grandes): viene acumulando desde 1991. No importa —
# solo se usa el COCIENTE entre dos fechas. Pero no se puede mostrar como si
# fuera base 100 ni compararlo contra el reconstruido en valor absoluto.

FUENTE_PUBLICADA = "CAMARCO — índice T.E.M. publicado (Ley 13.064 art. 48)"
COLOR_PUBLICADA = "#0F766E"


def serie_publicada(desde, hasta, indices, tnas=None, mipyme=False):
    """Las mismas filas que `serie_indice`, pero leídas del índice publicado.

    `indices` y `tnas` son [{FECHA, VALOR}] — las series CERT_BNA_IND_* y
    CERT_BNA_TNA_* que carga `cargar_camarco_certificados.py`.

    ⚠ LA TASA DIARIA SE DERIVA DE LA TNA, NO SE LEE. El PDF publica la TNM
    redondeada a dos decimales (2,47 %) y con ese redondeo el índice NO cierra:
    daría 168,906216 donde el publicado dice 168,905982. La TNA sí viene con
    los decimales que hacen falta, así que se recalcula TNM e i_d con la
    fórmula del BNA — y así reproduce el índice publicado a 4e-4.
    """
    d, h = _f(desde), _f(hasta)
    if h < d:
        return {"error": "la fecha final es anterior a la inicial"}
    f_idx, v_idx = _serie_dict(indices)
    if not f_idx:
        return {"error": "no hay índice publicado cargado en la base"}
    f_tna, v_tna = _serie_dict(tnas or [])

    filas, avisos = [], []
    sin_dato = 0
    dia = d
    while dia <= h:
        i = v_idx.get(dia)
        if i is None:
            sin_dato += 1
            filas.append({"fecha": dia.isoformat(), "tna": None, "tnm_pct": None,
                          "tasa_diaria_pct": None, "indice": None,
                          "base": None, "fecha_tasa": None, "confirmado": None,
                          "regimen_id": None, "color": COLOR_SIN_REGIMEN})
            dia += dt.timedelta(days=1)
            continue
        tna = v_tna.get(dia)
        i_d = tnm = None
        if tna is not None:
            i_d, tnm = tasa_diaria(tna)
        filas.append({
            "fecha": dia.isoformat(), "tna": tna,
            "tnm_pct": tnm * 100 if tnm is not None else None,
            "tasa_diaria_pct": i_d * 100 if i_d is not None else None,
            "indice": i, "base": "PUBLICADO",
            "fecha_tasa": dia.isoformat(), "spread_pp": None,
            "confirmado": True, "regimen_id": "publicada",
            "color": COLOR_PUBLICADA,
        })
        dia += dt.timedelta(days=1)

    if sin_dato:
        avisos.append(
            "%d días sin índice publicado en el rango. El índice es ACUMULADO: "
            "un hueco no se ve roto, se ve como un coeficiente más chico. "
            "Recargar con cargar_camarco_certificados.py." % sin_dato)
    return {"filas": filas, "avisos": avisos, "regimenes_usados": [{
        "id": "publicada", "desde": filas[0]["fecha"] if filas else None,
        "hasta": filas[-1]["fecha"] if filas else None,
        "base": "PUBLICADO", "base_detalle": FUENTE_PUBLICADA,
        "spread_pp": None, "spread_pp_mipyme": None, "lag_habiles": None,
        "confirmado": True, "color": COLOR_PUBLICADA,
        "norma": "Ley 13.064 art. 48 · decreto 13.477/56 art. 1",
        "fuente": FUENTE_PUBLICADA + (" — columna MiPyME" if mipyme
                                      else " — columna Grandes Inversores"),
    }]}


def _filas_empalmadas(desde, hasta, series_base, regimenes, base,
                      regimen_previo, mipyme, fuente, publicado):
    """Las filas del rango, con el índice publicado mandando donde lo hay.

    ⚠ EL EMPALME RE-ESCALA, NO CONCATENA. El índice publicado viene acumulando
    desde 1991 (vale 220,93 el 01/01/2018) y la reconstrucción arranca en 100.
    Pegar las dos listas daría un salto de 120 puntos el día de la junta y un
    coeficiente disparatado. Se reescala el tramo reconstruido para que empiece
    donde termina el publicado, y así el cociente punta a punta sigue valiendo.

    ⚠ EL DÍA DEL CORTE NO SE CUENTA DOS VECES: el publicado entrega su última
    fila como el índice AL INICIO de ese día, y la reconstrucción arranca
    justo ahí.
    """
    avisos, regs = [], []
    pub = publicado or {}
    idx = pub.get("indices") or []

    # ⚠⚠ EL DEFAULT ES **NUESTRO** CÁLCULO, NO EL DE CAMARCO (Juan, 2026-09-11:
    # *«nosotros vamos a tener nuestros propios valores, lo de CAMARCO es
    # backtesting nomás»*). Es una decisión de independencia, no de precisión:
    # si el número que damos sale de republicar la planilla de otro, dependemos
    # de que la republiquen, de que no la muevan y de que no la corrijan sin
    # avisar. Calculándolo nosotros, CAMARCO pasa a ser lo que conviene que sea:
    # el banco de pruebas contra el que se verifica — 3.174 días de dato
    # publicado para contrastar, que es muchísimo más de lo que se consigue
    # normalmente para validar un cálculo.
    #
    # ⚠ LA EXCEPCIÓN QUE NO SE PUEDE EVITAR: del 01/01/2018 al 05/12/2018 la base
    # es la TACG y NO hay forma de reconstruirla (ver el encabezado). Para ese
    # tramo, o se usa `fuente="publicada"`, o el motor avisa que no capitaliza.
    # No se tapa el hueco con una tasa inventada.
    if fuente in ("reconstruida", "propia") or not idx:
        if fuente == "publicada" and not idx:
            return {"error": "no hay índice publicado cargado: correr "
                             "api/cargar_camarco_certificados.py"}
        s = serie_indice(desde, hasta, series_base, regimenes, base,
                         regimen_previo, mipyme=mipyme,
                         tna_relevada=pub.get("tnas"))
        return s if "error" in s else {**s, "fuente": "propia"}

    f_idx, _ = _serie_dict(idx)
    ultima = f_idx[-1]
    corte = min(_f(hasta), ultima)

    sp = serie_publicada(desde, corte.isoformat(), idx, pub.get("tnas"), mipyme)
    if "error" in sp:
        return sp
    filas = sp["filas"]; avisos += sp["avisos"]; regs += sp["regimenes_usados"]

    if fuente == "publicada" or _f(hasta) <= ultima:
        if fuente == "publicada" and _f(hasta) > ultima:
            avisos.append("el índice publicado llega hasta el %s; se cortó ahí"
                          % ultima.isoformat())
        return {"filas": filas, "avisos": avisos, "regimenes_usados": regs,
                "fuente": "publicada"}

    # Hay que estirar más allá de lo publicado: se reconstruye y se reescala.
    sr = serie_indice(corte.isoformat(), hasta, series_base, regimenes, base,
                      regimen_previo, mipyme=mipyme,
                      tna_relevada=pub.get("tnas"))
    if "error" in sr:
        return sr
    ancla = filas[-1]["indice"] if filas else base
    k = (ancla / sr["filas"][0]["indice"]) if sr["filas"] and sr["filas"][0]["indice"] else 1.0
    extra = []
    for f in sr["filas"][1:]:          # la fila del corte ya está en `filas`
        g = dict(f)
        if g.get("indice") is not None:
            g["indice"] = g["indice"] * k
        extra.append(g)
    # la última fila publicada pasa a llevar la tasa con la que arranca el tramo
    # reconstruido, porque es la que produce el índice del día siguiente
    if filas and sr["filas"]:
        for c in ("tna", "tnm_pct", "tasa_diaria_pct", "spread_pp"):
            if sr["filas"][0].get(c) is not None:
                filas[-1][c] = sr["filas"][0][c]
    avisos += sr["avisos"]
    avisos.append("desde el %s no hay índice publicado: ese tramo va "
                  "reconstruido con BCRA + spread del BNA." % ultima.isoformat())
    return {"filas": filas + extra, "avisos": avisos,
            "regimenes_usados": regs + sr["regimenes_usados"],
            "fuente": "mixta"}


def calcular(monto, desde, hasta, series_base, capitalizar=True,
             modo="mora", regimenes=None, regimen_previo=None, base=100.0,
             mipyme=False, fuente="propia", publicado=None):
    """Lo que se muestra en pantalla: los DOS coeficientes, su plata y el
    desglose por tramo de régimen.

    ⚠ COMPUESTO Y SIMPLE SE DEVUELVEN SIEMPRE LOS DOS (Juan, 2026-09-11:
    *«vamos a armar considerando y no considerando interés compuesto»*).
    Antes era un botón: se elegía uno y el otro aparecía en chico al pie. El
    problema no era estético — es que la lectura que corresponde depende del
    pliego, y con un botón el que mira la pantalla ve un número sin saber que
    había otro. Los dos al mismo tamaño obligan a elegir a ojos abiertos.

    Las dos lecturas usan LA MISMA tasa diaria i_d. La única diferencia es
    que una la multiplica día a día y la otra la suma:

        compuesto = Π (1 + i_d)          simple = 1 + Σ i_d

    `capitalizar` sigue existiendo y sigue eligiendo cuál va en las claves
    planas (`coeficiente`, `interes`, `total`) — para no romper a quien ya
    consume este endpoint. Pero `compuesto` y `simple` vienen completos
    siempre, no importa cómo venga.
    """
    s = _filas_empalmadas(desde, hasta, series_base, regimenes, base,
                          regimen_previo, mipyme, fuente, publicado)
    if "error" in s:
        return s
    filas = s["filas"]
    if len(filas) < 2:
        return {"error": "el rango tiene que ser de al menos un día"}

    i0, i1 = filas[0]["indice"], filas[-1]["indice"]
    coef_comp = (i1 / i0) if i0 else 1.0
    coef_simple = 1 + sum((f["tasa_diaria_pct"] or 0) / 100.0 for f in filas[:-1])

    compuesto = _plata(monto, coef_comp, modo)
    simple = _plata(monto, coef_simple, modo)
    elegida = compuesto if capitalizar else simple

    tnas = [f["tna"] for f in filas if f["tna"] is not None]
    return {
        "desde": filas[0]["fecha"], "hasta": filas[-1]["fecha"],
        "dias": len(filas) - 1, "monto": float(monto or 0), "modo": modo,
        "capitalizar": bool(capitalizar), "mipyme": bool(mipyme),
        "fuente": s.get("fuente", "reconstruida"),
        "indice_inicial": i0, "indice_final": i1,

        # Las dos lecturas, completas y al mismo nivel.
        "compuesto": compuesto,
        "simple": simple,
        # Cuánto separa una de la otra. Es el número que contesta "¿importa?".
        "brecha": {
            "coeficiente": coef_comp - coef_simple,
            "plata": (compuesto.get("interes") or 0) - (simple.get("interes") or 0),
            "pct_sobre_simple": ((coef_comp / coef_simple - 1) * 100
                                 if coef_simple else 0.0),
        },

        # Compat: la lectura elegida, plana, como venía saliendo antes.
        "coeficiente": elegida["coeficiente"],
        "coeficiente_capitalizado": coef_comp,
        "coeficiente_sin_capitalizar": coef_simple,
        **{k: v for k, v in elegida.items() if k != "coeficiente"},

        "tramos": _tramos(filas),
        "tna_min": min(tnas) if tnas else None,
        "tna_max": max(tnas) if tnas else None,
        "tna_primera": tnas[0] if tnas else None,
        "tna_ultima": tnas[-1] if tnas else None,
        "dias_con_tasa": len(tnas),
        "regimenes": [dict(r) for r in s["regimenes_usados"]],
        "variantes_abiertas": list(VARIANTES_ABIERTAS),
        "avisos": s["avisos"],
    }
