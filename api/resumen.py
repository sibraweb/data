"""
Resumen de variaciones por serie: MTD/YTD/1A/5A (siempre contra la última
fecha disponible de cada serie, no contra "hoy" — las series semanales o
mensuales como UOCRA/RIPTE/CAC quedan rezagadas respecto al calendario real)
más variación entre dos fechas cualquiera elegidas a mano.

Mismo criterio "asof" que ajuste.py: se busca el último valor conocido en
o antes de la fecha de referencia, necesario porque las series tienen
frecuencias distintas entre sí.
"""

from __future__ import annotations

import pandas as pd


def _to_df(records: list[dict], fecha_col: str, valor_col: str) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["fecha", "valor"])
    df = df.rename(columns={fecha_col: "fecha", valor_col: "valor"})
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df = df.dropna(subset=["valor"]).sort_values("fecha")
    # CER (y algunas otras series del BCRA) se publican con proyección a
    # futuro (hasta el 15 del mes próximo) — nunca usar esos puntos como "lo
    # último disponible", si no el MoM/YTD terminan comparados contra un
    # valor que todavía no pasó.
    df = df[df["fecha"] <= pd.Timestamp.now().normalize()]
    return df[["fecha", "valor"]]


def _en_o_antes(df: pd.DataFrame, fecha: pd.Timestamp):
    sub = df[df["fecha"] <= fecha]
    if sub.empty:
        return None
    fila = sub.iloc[-1]
    return fila["fecha"], float(fila["valor"])


def variacion(records: list[dict], fecha_col: str, valor_col: str, desde: str, hasta: str) -> dict | None:
    """% de variación entre el valor más cercano (hacia atrás) a `desde` y a
    `hasta`, más la tasa anualizada (equivalente al XIRR de Excel para un
    flujo de 2 puntos: -valor_desde en `desde`, +valor_hasta en `hasta` —
    mismo cálculo que la "redeterminación" del Excel de Juan: Gap + TIR)."""
    df = _to_df(records, fecha_col, valor_col)
    if df.empty:
        return None

    ini = _en_o_antes(df, pd.Timestamp(desde))
    fin = _en_o_antes(df, pd.Timestamp(hasta))
    if ini is None or fin is None or ini[1] == 0:
        return None

    f_ini, v_ini = ini
    f_fin, v_fin = fin
    dias = (f_fin - f_ini).days
    tir = None
    if dias > 0:
        tir = round(((v_fin / v_ini) ** (365 / dias) - 1) * 100, 2)

    return {
        "desde": f_ini.date().isoformat(),
        "hasta": f_fin.date().isoformat(),
        "valor_desde": round(v_ini, 6),
        "valor_hasta": round(v_fin, 6),
        "dias": dias,
        "variacion_pct": round((v_fin / v_ini - 1) * 100, 2),
        "tir_anualizada_pct": tir,
    }


def resumen_serie(records: list[dict], fecha_col: str, valor_col: str) -> dict | None:
    """Réplica de la hoja "Resumen Indices" del Excel de Juan — todas las
    métricas se calculan contra la última fecha disponible de la serie
    (no contra "hoy": UOCRA/RIPTE/CAC quedan rezagadas del calendario):

      mom  = acum del mes   -> v(corte) / v(fin mes anterior) - 1
      d30  = últimos 30 días -> v(corte) / v(corte - 30 días) - 1
      ytd  = acum anual      -> v(corte) / v(31-dic año anterior) - 1
      yoy  = inter-anual     -> v(corte) / v(corte - 12 meses) - 1
      yoy_anualizada = TIR no periódica -> (v(corte)/v(corte-12m))^(365/días) - 1
      a5   = 5 años          -> v(corte) / v(corte - 5 años) - 1
    """
    df = _to_df(records, fecha_col, valor_col)
    if df.empty:
        return None

    ultima_fecha = df["fecha"].max()
    ultimo_valor = float(df.iloc[-1]["valor"])

    periodos = {
        "mom": ultima_fecha.replace(day=1) - pd.Timedelta(days=1),
        "d30": ultima_fecha - pd.Timedelta(days=30),
        "ytd": pd.Timestamp(year=ultima_fecha.year - 1, month=12, day=31),
        "yoy": ultima_fecha - pd.DateOffset(years=1),
        "a5": ultima_fecha - pd.DateOffset(years=5),
    }

    resultado = {
        "ultima_fecha": ultima_fecha.date().isoformat(),
        "ultimo_valor": round(ultimo_valor, 6),
    }
    for clave, fecha_ini in periodos.items():
        ini = _en_o_antes(df, fecha_ini)
        if ini is None or ini[1] == 0:
            resultado[clave] = None
            continue
        f_ini, v_ini = ini
        resultado[clave] = round((ultimo_valor / v_ini - 1) * 100, 2)

    # TIR no periódica: anualiza el inter-anual por los días reales entre la
    # fecha "hace 12 meses" encontrada (asof) y el corte — corrige cuando la
    # serie es mensual y el punto más cercano no cae justo a 365 días.
    ini_yoy = _en_o_antes(df, periodos["yoy"])
    if ini_yoy and ini_yoy[1] > 0:
        f_ini, v_ini = ini_yoy
        dias = (ultima_fecha - f_ini).days
        if dias > 0:
            resultado["yoy_anualizada"] = round(((ultimo_valor / v_ini) ** (365 / dias) - 1) * 100, 2)
        else:
            resultado["yoy_anualizada"] = None
    else:
        resultado["yoy_anualizada"] = None

    return resultado
