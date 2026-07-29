"""
Migración completa (correr una sola vez, se puede repetir sin duplicar):
copia todas las pestañas de SIBRATECH_INDICES (Sheets) a Postgres (Supabase),
Fase 6 del roadmap (ver SIBRA_SERVER/PROCESO.md).

Requiere:
  - .env con INDICES_SHEET_ID (o credentials.json + token.pickle ya logueado)
  - .env con SUPABASE_DB_URL

Uso: python migrar_a_supabase.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import db
import sheets

# ── series_valores: simples (una sola columna VALOR) ────────────────────────
TABS_SIMPLES = [
    "CER", "UVA", "UVI", "ICL", "INFLACION_INDEC", "BADLAR", "TAMAR", "BAIBAR",
    "DEPOSITOS_30D", "ADELANTOS_CTA_CTE", "PRESTAMOS_PERSONALES", "TIM",
    "RIESGO_PAIS", "MERVAL",
]

# ── series_valores: anchas (multi-columna) ──────────────────────────────────
TABS_ANCHAS = {
    "DOLAR": [
        "OFICIAL_COMPRA", "OFICIAL_VENTA", "BLUE_COMPRA", "BLUE_VENTA",
        "MEP_COMPRA", "MEP_VENTA", "CCL_COMPRA", "CCL_VENTA",
        "MAYORISTA_COMPRA", "MAYORISTA_VENTA", "CRIPTO_COMPRA", "CRIPTO_VENTA",
        "TARJETA_COMPRA", "TARJETA_VENTA",
    ],
    "UOCRA": [
        "OFICIAL_ESPECIALIZADO", "OFICIAL", "MEDIO_OFICIAL", "AYUDANTE", "SERENO",
        "OFICIAL_ESPECIALIZADO_NO_REM", "OFICIAL_NO_REM", "MEDIO_OFICIAL_NO_REM",
        "AYUDANTE_NO_REM", "SERENO_NO_REM",
    ],
    "CONSTRUCCION": ["INDICE_GENERAL", "MATERIALES", "MANO_DE_OBRA", "PROVISIONES"],
    "CAC": ["COSTO_CONSTRUCCION", "MATERIALES", "MANO_DE_OBRA"],
    "SALARIOS": ["PRIVADO_REGISTRADO", "PUBLICO", "TOTAL_REGISTRADO", "NO_REGISTRADO", "INDICE_TOTAL"],
    "ICC_CABA": ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"],
    "ICC_BUENOS_AIRES": ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"],
    "ICC_CORDOBA": ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"],
    "ICC_SANTA_FE": ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"],
    "ALQUILER_CABA": ["PROMEDIO", "PRECIO_2_AMBIENTES", "PRECIO_3_AMBIENTES"],
    "RIPTE": ["RIPTE", "VARIACION_MENSUAL"],  # PERIODO no se migra: derivable de FECHA
}


def migrar_simple(tab: str) -> None:
    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()
    registros = sheets.read_records(sid, tab)
    n = db.upsert_valores_simple(tab, registros)
    print(f"[migrar] {tab}: {len(registros)} filas leídas de Sheets, {n} insertadas/consideradas en Postgres")


def migrar_ancha(tab: str, headers: list[str]) -> None:
    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()
    registros = sheets.read_records(sid, tab)
    total = db.upsert_valores_ancha_bulk(tab, registros, headers)
    print(f"[migrar] {tab}: {len(registros)} filas (fechas) leídas de Sheets, {total} pares columna-valor insertados/considerados en Postgres")


def migrar_rem() -> None:
    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()
    for tipo, tab in (("ipc", "REM_IPC"), ("fx", "REM_FX")):
        registros = sheets.read_records(sid, tab)
        n = db.upsert_rem_bulk(tipo, registros)
        print(f"[migrar] {tab}: {len(registros)} filas leídas de Sheets, {n} insertadas/consideradas en Postgres")
    registros = sheets.read_records(sid, "REM_IPC_INTERANUAL")
    n = db.upsert_rem_bulk("ipc_interanual", registros)
    print(f"[migrar] REM_IPC_INTERANUAL: {len(registros)} filas leídas de Sheets, {n} insertadas/consideradas en Postgres")


def migrar_uocra_adicionales() -> None:
    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()
    registros = sheets.read_records(sid, "UOCRA_ADICIONALES")
    n = db.upsert_uocra_adicionales_bulk(registros)
    print(f"[migrar] UOCRA_ADICIONALES: {len(registros)} filas leídas de Sheets, {n} insertadas/consideradas en Postgres")


def migrar_materiales_historico() -> None:
    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()
    registros = sheets.read_records(sid, "MATERIALES_HISTORICO")
    n = db.upsert_materiales_historico_bulk(registros)
    print(f"[migrar] MATERIALES_HISTORICO: {len(registros)} filas leídas de Sheets, {n} insertadas/consideradas en Postgres")


if __name__ == "__main__":
    print("Migrando TODO indices (series_valores + REM + UOCRA_ADICIONALES + MATERIALES_HISTORICO) de Sheets a Supabase...")
    for tab in TABS_SIMPLES:
        migrar_simple(tab)
    for tab, headers in TABS_ANCHAS.items():
        migrar_ancha(tab, headers)
    migrar_rem()
    migrar_uocra_adicionales()
    migrar_materiales_historico()
    print("Listo. Revisar en el Table Editor de Supabase que los conteos tengan sentido.")
