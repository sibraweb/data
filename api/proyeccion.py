"""
Proyección de series (UOCRA, Construcción, RIPTE, ...) a partir de su
relación histórica con inflación (CER como proxy de IPC) y tipo de cambio
oficial, extrapolada hacia adelante con la curva de previsiones del REM.

Modelo: regresión lineal simple (OLS, sin dependencias extra —
numpy.linalg.lstsq) de la variación % mensual de la serie contra la
variación % mensual de CER y de dólar oficial:

    var_serie(t) = a + b_ipc * var_cer(t) + b_fx * var_dolar(t) + error

Es un ajuste simple e histórico, no un modelo econométrico riguroso —
sirve para tener un orden de magnitud, no una certeza. Por eso siempre
se devuelve el R² junto con la proyección, para que se pueda juzgar
qué tan bien explica el pasado esa relación antes de confiar en la
extrapolación.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _serie_mensual(records: list[dict], fecha_col: str, valor_col: str) -> pd.Series:
    df = pd.DataFrame(records)
    if df.empty:
        return pd.Series(dtype=float)
    df["fecha"] = pd.to_datetime(df[fecha_col])
    df["valor"] = pd.to_numeric(df[valor_col], errors="coerce")
    df = df.dropna(subset=["valor"]).sort_values("fecha")
    mensual = df.set_index("fecha")["valor"].resample("ME").last().dropna()
    return mensual


def estimar_modelo(
    objetivo: list[dict], objetivo_fecha_col: str, objetivo_valor_col: str,
    cer: list[dict], dolar: list[dict], dolar_valor_col: str = "OFICIAL_VENTA",
) -> dict | None:
    s_obj = _serie_mensual(objetivo, objetivo_fecha_col, objetivo_valor_col)
    s_cer = _serie_mensual(cer, "FECHA", "VALOR")
    s_fx = _serie_mensual(dolar, "FECHA", dolar_valor_col)

    if len(s_obj) < 6 or s_cer.empty or s_fx.empty:
        return None

    var_obj = s_obj.pct_change().dropna()
    var_cer = s_cer.pct_change().dropna()
    var_fx = s_fx.pct_change().dropna()

    df = pd.concat(
        {"obj": var_obj, "cer": var_cer, "fx": var_fx}, axis=1, join="inner"
    ).dropna()

    if len(df) < 6:
        return None

    X = np.column_stack([np.ones(len(df)), df["cer"].to_numpy(), df["fx"].to_numpy()])
    y = df["obj"].to_numpy()
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    a, b_ipc, b_fx = coef

    y_hat = X @ coef
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {
        "a": float(a), "b_ipc": float(b_ipc), "b_fx": float(b_fx),
        "r2": round(r2, 4), "n_obs": int(len(df)),
        "ultimo_valor": float(s_obj.iloc[-1]), "ultima_fecha": s_obj.index[-1].date().isoformat(),
        "ultimo_fx": float(s_fx.iloc[-1]),
    }


def proyectar(modelo: dict, rem_ipc_curva: list[dict], rem_fx_curva: list[dict]) -> list[dict]:
    """rem_ipc_curva: filas de /api/rem/ipc (MEDIANA ya es var. % mensual).
    rem_fx_curva: filas de /api/rem/fx (MEDIANA es nivel $/USD; se deriva var. % mensual)."""
    if not rem_ipc_curva or not rem_fx_curva:
        return []

    # float() explícito: desde que el REM vive en Postgres, MEDIANA llega como
    # decimal.Decimal (la columna es numeric) y no como el float que daba
    # Sheets. Decimal no se puede dividir por float, así que esta ruta venía
    # rompiendo con TypeError — /api/proyectar tiraba 500 y la proyección no
    # se veía en UOCRA/RIPTE/Construcción.
    ipc_por_periodo = {r["PERIODO"]: float(r["MEDIANA"]) for r in rem_ipc_curva
                       if r.get("MEDIANA") is not None}
    fx_niveles = sorted(rem_fx_curva, key=lambda r: r["PERIODO"])

    valor = float(modelo["ultimo_valor"])
    resultado = []
    fx_anterior = modelo.get("ultimo_fx")
    fx_anterior = None if fx_anterior is None else float(fx_anterior)
    for fila in fx_niveles:
        periodo = fila["PERIODO"]
        if fila.get("MEDIANA") is None:
            continue
        nivel_fx = float(fila["MEDIANA"])
        var_ipc = ipc_por_periodo.get(periodo)
        if var_ipc is None or fx_anterior is None:
            fx_anterior = nivel_fx
            continue
        var_fx = (nivel_fx / fx_anterior) - 1
        var_ipc_frac = var_ipc / 100.0
        var_estimada = modelo["a"] + modelo["b_ipc"] * var_ipc_frac + modelo["b_fx"] * var_fx
        valor = valor * (1 + var_estimada)
        resultado.append({"fecha": periodo, "valor": round(valor, 4)})
        fx_anterior = nivel_fx

    return resultado
