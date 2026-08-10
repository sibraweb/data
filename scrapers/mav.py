# -*- coding: utf-8 -*-
"""Tasas de MAV (Mercado Argentino de Valores) — cheques/echeqs, pagarés y FCE,
por rango de plazo, segmento y MONEDA.

API pública mavdata.mav-sa.com.ar (descubierta 2026-07-28, sin auth — portada
de `Vinculacion bancos/servicio/financiamiento.py`). Da tasa promedio ponderada
TNA/TEA/TEM por rango de plazo (0-30 / 31-60 / 61-90 / 91-120) y segmento
(avalado / garantizado / no garantizado).

📝 **Relevado contra la API el 2026-08-09** — dos cosas que este módulo daba
por sentado y estaban mal:

1. **El endpoint SÍ acepta `fecha` para días pasados.** Se creía que era una
   foto del día y que lo no capturado se perdía; por eso `series_valores`
   tenía 6 filas de CHEQUES. **Hay al menos dos años de histórico disponible**
   (probado desde ago-2024), así que se puede backfillear — ver `serie_diaria()`.
2. **Los valores válidos de `moneda` e `instrumento` los declara la propia
   API** cuando se le manda uno inválido. No hay que adivinarlos.

Los combos que existen de verdad (probados el 2026-08-09; la API responde
`{"detail": "..."}` a los que no):

    Cheques   ->  $                            (dólar: NO EXISTE en MAV)
    Pagares   ->  $ · dol · dollar linked
    FCE       ->  $ · dollar linked
    Pagaré TAMAR / BADLAR / Soja  ->  $        (casi siempre sin datos)

⚠ **No hay cheques en dólares.** Es del mercado, no del scraper: MAV contesta
"Datos no encontrados" para `Cheques` + `dol`, y para `dollar linked` avisa que
no es una opción válida de ese instrumento.

Dos destinos, como cauciones:
  · `mercado_tasas_mav`      — foto completa de hoy, se PISA entera
  · `series_valores/CHEQUES` y `/PAGARES` — histórico, una fila por día
"""
from __future__ import annotations

import datetime as dt
import unicodedata

import requests
import urllib3

urllib3.disable_warnings()

URL = "https://mavdata.mav-sa.com.ar/api/segregacion-rangos-segmentos"

# moneda de la API -> sufijo de columna en series_valores.
# Pesos va SIN sufijo a propósito: son las columnas que ya existen cargadas
# (AVALADO_CORTO, etc.) y renombrarlas rompería el histórico.
MONEDAS = {
    "$": "",
    "dol": "_USD",
    "dollar linked": "_DL",
}

# instrumento -> (tab de series_valores, monedas que ese instrumento acepta).
# Los nombres van como los declara la API (con mayúscula), no en minúscula.
INSTRUMENTOS = {
    "Cheques": ("CHEQUES", ["$"]),
    "Pagares": ("PAGARES", ["$", "dol", "dollar linked"]),
}

# Existen en la API pero todavía no se persisten: FCE ($ y dollar linked) y los
# pagarés indexados (TAMAR / BADLAR / Soja), que casi nunca traen datos.
# Agregarlos acá cuando haga falta — el resto del módulo no cambia.


def tasas_instrumento(instrumento: str = "Cheques", moneda: str = "$",
                      fecha: str | dt.date | None = None) -> list[dict]:
    """[{instrumento, moneda, fecha, segmento, rango, tna, tea, tem, monto}].

    `fecha` en ISO (o `date`); por defecto hoy. Devuelve `[]` si MAV no
    responde, si el combo instrumento/moneda no existe, o si ese día no operó
    (fin de semana o feriado) — los tres casos son "no hay dato", no error.
    """
    if fecha is None:
        fecha = dt.date.today()
    f = fecha.isoformat() if isinstance(fecha, dt.date) else str(fecha)
    try:
        r = requests.get(URL, params={"instrumento": instrumento, "moneda": moneda,
                                      "fecha": f},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=25, verify=False)
        data = r.json()
    except Exception:
        return []
    # La API contesta 200 con {"detail": "..."} cuando el combo no existe o no
    # hay datos — no es una excepción, hay que mirarlo.
    if not isinstance(data, dict) or "resultados" not in data:
        return []
    out = []
    for seg in data.get("resultados", []):
        segmento = seg.get("segmento")
        for x in seg.get("datos", []):
            out.append({
                "instrumento": instrumento, "moneda": moneda, "fecha": f,
                "segmento": segmento, "rango": x.get("rango"),
                "tna": x.get("tasa_prom_pond"), "tea": x.get("tasa_tea_pond"),
                "tem": x.get("tasa_tem_pond"), "monto": x.get("monto"),
            })
    return out


def fetch_todo(fecha=None) -> list[dict]:
    """Todas las filas de todos los combos instrumento×moneda que existen.
    `[]` si MAV no responde a ninguno (el llamador NO debe borrar la tabla
    snapshot si viene vacío — ver `refrescar_mav` en server.py)."""
    out = []
    for instrumento, (_tab, monedas) in INSTRUMENTOS.items():
        for moneda in monedas:
            out += tasas_instrumento(instrumento, moneda, fecha)
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rango_dias(rango):
    """'0-30' -> 0 (extremo corto, para ordenar y elegir la referencia)."""
    try:
        return int(str(rango).split("-")[0])
    except (ValueError, IndexError):
        return 10**9


def _col(segmento, moneda):
    s = unicodedata.normalize("NFKD", str(segmento)).encode("ascii", "ignore").decode()
    return s.strip().upper().replace(" ", "_") + "_CORTO" + MONEDAS.get(moneda, "")


def referencia_por_segmento(filas: list[dict], fecha=None) -> dict:
    """De las filas YA obtenidas (sin pegarle de nuevo a MAV): para cada
    segmento Y moneda, la TNA del rango de plazo más corto — la punta de la
    curva, mismo criterio que el plazo de 1 día en cauciones.

    {"FECHA": "YYYY-MM-DD", "AVALADO_CORTO": .., "AVALADO_CORTO_USD": .., ...}
    Devuelve `{}` (sin la clave FECHA) si no hay ni un valor usable, así el
    llamador puede saltear el día sin escribir una fila vacía.
    """
    mejor = {}  # (segmento, moneda) -> (rango_dias, tna)
    for f in filas:
        tna = _num(f.get("tna"))
        if tna is None:
            continue
        clave = (f.get("segmento") or "SIN_SEGMENTO", f.get("moneda") or "$")
        rd = _rango_dias(f.get("rango"))
        if clave not in mejor or rd < mejor[clave][0]:
            mejor[clave] = (rd, tna)
    if not mejor:
        return {}
    if fecha is None:
        # Todas las filas de una corrida son del mismo día; si vinieron con
        # fecha propia (backfill), se respeta esa y no la de hoy.
        fecha = next((f.get("fecha") for f in filas if f.get("fecha")), None) \
            or dt.date.today().isoformat()
    f_iso = fecha.isoformat() if isinstance(fecha, dt.date) else str(fecha)
    fila = {"FECHA": f_iso}
    for (seg, moneda), (_, tna) in mejor.items():
        fila[_col(seg, moneda)] = tna
    return fila


def columnas_posibles(instrumento: str) -> list[str]:
    """Todas las columnas que ese instrumento puede llegar a producir. Se usa
    para declarar los headers de la serie ancha sin depender de qué segmentos
    hayan operado justo hoy (si un día no opera 'garantizado', la columna
    tiene que seguir existiendo)."""
    _tab, monedas = INSTRUMENTOS[instrumento]
    segmentos = ("avalado", "garantizado", "no garantizado")
    return [_col(s, m) for m in monedas for s in segmentos]


def serie_diaria(instrumento: str, desde: dt.date, hasta: dt.date,
                 pausa: float = 0.25) -> list[dict]:
    """Backfill: una fila de referencia por día hábil entre `desde` y `hasta`.

    Saltea fines de semana sin pegarle a la API, y saltea los días que MAV
    devuelve vacío (feriados). Probado con dos años de historia — MAV sirve
    fechas pasadas, que es lo que hace posible este backfill.
    """
    import time

    _tab, monedas = INSTRUMENTOS[instrumento]
    out, d = [], desde
    while d <= hasta:
        if d.weekday() < 5:                       # 5=sáb, 6=dom
            filas = []
            for moneda in monedas:
                filas += tasas_instrumento(instrumento, moneda, d)
                time.sleep(pausa)
            fila = referencia_por_segmento(filas, fecha=d)
            if fila:
                out.append(fila)
        d += dt.timedelta(days=1)
    return out


if __name__ == "__main__":
    for instrumento in INSTRUMENTOS:
        filas = []
        for moneda in INSTRUMENTOS[instrumento][1]:
            filas += tasas_instrumento(instrumento, moneda)
        print(instrumento, "->", referencia_por_segmento(filas))
