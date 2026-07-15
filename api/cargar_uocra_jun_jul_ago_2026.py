"""
Carga puntual de UOCRA jun/jul/ago-2026 (CCT 76/75, Zona A) — el PDF oficial
de uocra.org para este período es una imagen escaneada sin capa de texto
(ni el parser normal ni el fallback OCR pudieron leerlo con confianza, ver
scrapers/uocra.py). Se usó como fuente alternativa:

    https://convenios.lannis.app/escalas/uocra-cct-76-75

que transcribe y revisa a mano el mismo acuerdo homologado (cita
"acuerdo-uocra-76-75-jun-ago-2026.pdf, p. 1"). Los 3 meses pasan la misma
validación de sanidad que usa el scraper (Of.Esp >= Of >= Med.Of >= Ayud.,
Sereno >> Ayudante x10) — no se guarda nada que no la pase.

Uso: python cargar_uocra_jun_jul_ago_2026.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets
from scrapers.uocra import _fila_valida

HEADERS = [
    "FECHA", "OFICIAL_ESPECIALIZADO", "OFICIAL", "MEDIO_OFICIAL", "AYUDANTE", "SERENO",
    "OFICIAL_ESPECIALIZADO_NO_REM", "OFICIAL_NO_REM", "MEDIO_OFICIAL_NO_REM",
    "AYUDANTE_NO_REM", "SERENO_NO_REM",
]

# Básico Zona A (jornal) + suma no remunerativa Zona A, tal cual la tabla del sitio
FILAS = [
    {
        "FECHA": "2026-06-01",
        "OFICIAL_ESPECIALIZADO": 6666.00, "OFICIAL": 5703.00, "MEDIO_OFICIAL": 5270.00,
        "AYUDANTE": 4851.00, "SERENO": 881193.00,
        "OFICIAL_ESPECIALIZADO_NO_REM": 63300.00, "OFICIAL_NO_REM": 58300.00,
        "MEDIO_OFICIAL_NO_REM": 53400.00, "AYUDANTE_NO_REM": 50300.00, "SERENO_NO_REM": 50300.00,
    },
    {
        "FECHA": "2026-07-01",
        "OFICIAL_ESPECIALIZADO": 6800.00, "OFICIAL": 5817.00, "MEDIO_OFICIAL": 5375.00,
        "AYUDANTE": 4948.00, "SERENO": 898817.00,
        "OFICIAL_ESPECIALIZADO_NO_REM": 72900.00, "OFICIAL_NO_REM": 67100.00,
        "MEDIO_OFICIAL_NO_REM": 61500.00, "AYUDANTE_NO_REM": 57900.00, "SERENO_NO_REM": 57900.00,
    },
    {
        "FECHA": "2026-08-01",
        "OFICIAL_ESPECIALIZADO": 7420.00, "OFICIAL": 6348.00, "MEDIO_OFICIAL": 5866.00,
        "AYUDANTE": 5399.00, "SERENO": 980858.00,
        # agosto no tiene suma no remunerativa (se absorbe en el básico, según la fuente)
    },
]


def main():
    for fila in FILAS:
        if not _fila_valida(fila):
            raise SystemExit(f"Fila {fila['FECHA']} no pasa la validación de sanidad — no se carga.")

    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()
    n = sheets.upsert_series(sid, "UOCRA", HEADERS, "FECHA", FILAS)
    print(f"UOCRA -> {n} filas nuevas (jun/jul/ago 2026, fuente: convenios.lannis.app)")


if __name__ == "__main__":
    main()
