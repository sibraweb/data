"""
Lógica de ajuste/comparación de series — un solo componente reutilizado
por las 5 ventanas del frontend (UOCRA, RIPTE, Dólar, Materiales, Construcción).

ajustar(base, indice) hace un merge "asof" (última fecha conocida del
índice, no exige que las fechas coincidan exacto — necesario porque el
dólar/CER son diarios y UOCRA/RIPTE/materiales son mensuales) y devuelve
la serie base dividida por el índice, reindexada a 100 en el primer punto
en común.
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
    return df[["fecha", "valor"]]


def ajustar(
    base: list[dict],
    indice: list[dict] | None,
    base_fecha_col: str = "FECHA",
    base_valor_col: str = "VALOR",
    indice_fecha_col: str = "FECHA",
    indice_valor_col: str = "VALOR",
    modo: str = "ratio",
) -> list[dict]:
    """
    modo="ratio"   -> valor_base / valor_indice (términos reales, ej. salario/dólar)
    modo="nominal" -> devuelve la base sin tocar (cuando el usuario elige "ninguno")
    """
    df_base = _to_df(base, base_fecha_col, base_valor_col)
    if df_base.empty:
        return []

    if modo == "nominal" or indice is None:
        return [
            {"fecha": f.date().isoformat(), "valor": v}
            for f, v in zip(df_base["fecha"], df_base["valor"])
        ]

    df_idx = _to_df(indice, indice_fecha_col, indice_valor_col)
    if df_idx.empty:
        return []

    merged = pd.merge_asof(df_base, df_idx, on="fecha", suffixes=("_base", "_idx"))
    merged = merged.dropna(subset=["valor_idx"])
    merged = merged[merged["valor_idx"] != 0]
    merged["resultado"] = merged["valor_base"] / merged["valor_idx"]

    return [
        {"fecha": f.date().isoformat(), "valor": round(v, 6)}
        for f, v in zip(merged["fecha"], merged["resultado"])
    ]
