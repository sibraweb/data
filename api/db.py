"""
Acceso a Postgres (Supabase) para las series ya migradas (Fase 6 completa —
ver SIBRA_SERVER/PROCESO.md y docs/MARKET.md).

Mismo shape de salida que sheets.read_records(): lista de dicts, un dict por
fecha con las columnas como llaves ("FECHA", "VALOR" o el nombre de columna
que corresponda) — así ajuste.py/resumen.py no necesitan cambios, no importa
si el dato vino de Sheets o de acá.

Mismo comportamiento de guardado que sheets.upsert_series(): append-only,
nunca corrige un valor ya cargado (ON CONFLICT DO NOTHING) — decisión
explícita, no un descuido (ver PROCESO.md, "Upsert: agregar vs corregir").
"""

from __future__ import annotations

import os
import time
from collections import defaultdict

import psycopg
from psycopg.rows import dict_row

# Cache en memoria TTL 90s — mismo mecanismo y mismo TTL que ya usaba
# sheets.py. Sin esto cada lectura reconecta a Supabase (~1.4s solo de
# conexión, la base está en Ohio) y corre la query de nuevo, siempre —
# perdíamos el cache que Sheets ya tenía sin agregar uno nuevo acá (bug
# real: la migración "no mejoraba nada" porque no había cache, no porque
# Postgres sea lento).
_CACHE: dict = {}
_CACHE_TTL = 90  # segundos


def _cache_get(key: str):
    e = _CACHE.get(key)
    if e and (time.time() - e[1]) < _CACHE_TTL:
        return e[0]
    return None


def _cache_set(key: str, data):
    _CACHE[key] = (data, time.time())


def _cache_bust(*prefixes: str):
    for k in list(_CACHE.keys()):
        if any(k.startswith(p) for p in prefixes):
            del _CACHE[k]


def _conectar():
    # Se lee al momento de conectar, no al importar el módulo: server.py
    # importa `db` antes de llamar a `load_dotenv()`, así que leer la env var
    # a nivel de módulo (en el import) la capturaba vacía.
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        raise RuntimeError(
            "Falta SUPABASE_DB_URL en .env — connection string de Postgres "
            "(Project Settings -> Database -> Connection string, modo 'URI') "
            "del proyecto de Supabase."
        )
    return psycopg.connect(db_url, row_factory=dict_row)


def _num(v):
    """Normaliza a float o None; '' y None quedan como None (NUMERIC no acepta '')."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def leer_serie_simple(serie: str) -> list[dict]:
    """Series de una sola columna (ej. CER) -> [{"FECHA": "YYYY-MM-DD", "VALOR": ...}, ...]."""
    key = f"simple:{serie}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fecha, valor FROM series_valores "
                "WHERE serie = %s AND columna = '_' ORDER BY fecha",
                (serie,),
            )
            rows = cur.fetchall()
    resultado = [{"FECHA": r["fecha"].isoformat(), "VALOR": r["valor"]} for r in rows]
    _cache_set(key, resultado)
    return resultado


def leer_serie_ancha(serie: str) -> list[dict]:
    """Series multi-columna (DOLAR, UOCRA) -> un dict por fecha con todas las
    columnas encontradas ese día como llaves, misma forma que devolvía Sheets
    (una fila ancha por fecha, no una fila por columna)."""
    key = f"ancha:{serie}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fecha, columna, valor FROM series_valores "
                "WHERE serie = %s ORDER BY fecha",
                (serie,),
            )
            rows = cur.fetchall()
    por_fecha: dict = defaultdict(dict)
    for r in rows:
        fila = por_fecha[r["fecha"]]
        fila["FECHA"] = r["fecha"].isoformat()
        fila[r["columna"]] = r["valor"]
    resultado = [por_fecha[f] for f in sorted(por_fecha.keys())]
    _cache_set(key, resultado)
    return resultado


def upsert_valores_simple(serie: str, rows: list[dict], fecha_col: str = "FECHA", valor_col: str = "VALOR") -> int:
    """Para series de una sola columna (ej. CER): rows = [{"FECHA":.., "VALOR":..}, ...]."""
    tuplas = [(serie, r[fecha_col], _num(r.get(valor_col))) for r in rows if r.get(fecha_col)]
    if not tuplas:
        return 0
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO series_valores (serie, columna, fecha, valor)
                   VALUES (%s, '_', %s, %s)
                   ON CONFLICT (serie, columna, fecha) DO NOTHING""",
                tuplas,
            )
        conn.commit()
    _cache_bust(f"simple:{serie}")
    return len(tuplas)


def upsert_resumen_publico(filas: list[dict]) -> int:
    """Snapshot diario del Resumen para la pagina publica.

    Reemplaza a la Sheet publica desde 2026-08-02: el front (Vercel) lee esta
    tabla directo con la publishable key. `indices_resumen_publico` es la unica
    tabla con policy de lectura para `anon` — ver el comentario en server.py.

    Idempotente por `clave` (= fecha|familia): correr el job dos veces el mismo
    dia actualiza la fila, no la duplica."""
    if not filas:
        return 0
    cols = ["clave", "fecha_publicacion", "familia", "nombre", "ultimo_valor",
            "ultima_fecha", "mom", "d30", "ytd", "yoy", "yoy_anualizada", "a5"]
    def _fecha(v):
        return v or None
    tuplas = [tuple(_num(f.get(c)) if c not in ("clave", "fecha_publicacion",
                                                "familia", "nombre", "ultima_fecha")
                    else _fecha(f.get(c)) for c in cols) for f in filas]
    ph = ",".join(["%s"] * len(cols))
    setter = ",".join(f"{c}=excluded.{c}" for c in cols[1:])
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                f"""INSERT INTO indices_resumen_publico ({",".join(cols)})
                    VALUES ({ph})
                    ON CONFLICT (clave) DO UPDATE SET {setter}, actualizado = now()""",
                tuplas,
            )
        conn.commit()
    return len(tuplas)


def upsert_valores_ancha(serie: str, fecha: str, valores: dict) -> int:
    """Para una fila 'ancha' (ej. un día de DOLAR con 14 columnas, o un mes de
    UOCRA con 10): inserta una fila por columna con valor presente.
    Uso normal: el scheduler llama esto una vez por ciclo (un solo día/mes
    nuevo) - una conexión por llamada es aceptable acá. Para cargas masivas
    (migración histórica) usar upsert_valores_ancha_bulk en su lugar, que
    hace UNA sola conexión para todas las filas en vez de una por fecha."""
    tuplas = [(serie, col, fecha, _num(val)) for col, val in valores.items() if val not in (None, "")]
    if not tuplas:
        return 0
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO series_valores (serie, columna, fecha, valor)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (serie, columna, fecha) DO NOTHING""",
                tuplas,
            )
        conn.commit()
    _cache_bust(f"ancha:{serie}")
    return len(tuplas)


def leer_rem(tipo: str) -> list[dict]:
    """REM_IPC/REM_FX/REM_IPC_INTERANUAL -> misma forma que devolvía Sheets:
    lista de dicts con CLAVE, FECHA_PRONOSTICO, PERIODO, MEDIANA, PROMEDIO,
    DESVIO, MAXIMO, MINIMO, PERCENTIL_90."""
    key = f"rem:{tipo}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fecha_pronostico, periodo, mediana, promedio, desvio, "
                "maximo, minimo, percentil_90 FROM rem_forecast WHERE tipo = %s "
                "ORDER BY fecha_pronostico, periodo",
                (tipo,),
            )
            rows = cur.fetchall()
    out = []
    for r in rows:
        fp, pe = r["fecha_pronostico"].isoformat(), r["periodo"].isoformat()
        out.append({
            "CLAVE": f"{fp}|{pe}", "FECHA_PRONOSTICO": fp, "PERIODO": pe,
            "MEDIANA": r["mediana"], "PROMEDIO": r["promedio"], "DESVIO": r["desvio"],
            "MAXIMO": r["maximo"], "MINIMO": r["minimo"], "PERCENTIL_90": r["percentil_90"],
        })
    _cache_set(key, out)
    return out


def upsert_rem_bulk(tipo: str, registros: list[dict]) -> int:
    """registros = filas con FECHA_PRONOSTICO, PERIODO, MEDIANA, ... (mismo
    shape que arma bcra_rem.fetch_rem()). Bulk: una sola conexión para todo
    el lote, ver nota de upsert_valores_ancha_bulk."""
    tuplas = []
    for r in registros:
        fp, pe = r.get("FECHA_PRONOSTICO"), r.get("PERIODO")
        if not fp or not pe:
            continue
        tuplas.append((
            tipo, fp, pe, _num(r.get("MEDIANA")), _num(r.get("PROMEDIO")),
            _num(r.get("DESVIO")), _num(r.get("MAXIMO")), _num(r.get("MINIMO")),
            _num(r.get("PERCENTIL_90")),
        ))
    if not tuplas:
        return 0
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO rem_forecast
                   (tipo, fecha_pronostico, periodo, mediana, promedio, desvio, maximo, minimo, percentil_90)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tipo, fecha_pronostico, periodo) DO NOTHING""",
                tuplas,
            )
        conn.commit()
    _cache_bust(f"rem:{tipo}")
    return len(tuplas)


def leer_uocra_adicionales() -> list[dict]:
    key = "uocra_adicionales"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT clave, concepto_num, titulo, texto, acuerdo_ref, valor, unidad, desde, hasta "
                "FROM uocra_adicionales ORDER BY clave"
            )
            rows = cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "CLAVE": r["clave"], "CONCEPTO_NUM": r["concepto_num"], "TITULO": r["titulo"],
            "TEXTO": r["texto"], "ACUERDO_REF": r["acuerdo_ref"], "VALOR": r["valor"],
            "UNIDAD": r["unidad"],
            "DESDE": r["desde"].isoformat() if r["desde"] else None,
            "HASTA": r["hasta"].isoformat() if r["hasta"] else None,
        })
    _cache_set(key, out)
    return out


def upsert_uocra_adicionales_bulk(registros: list[dict]) -> int:
    tuplas = []
    for r in registros:
        clave = r.get("CLAVE")
        if not clave:
            continue
        tuplas.append((
            clave, r.get("CONCEPTO_NUM"), r.get("TITULO"), r.get("TEXTO"), r.get("ACUERDO_REF"),
            _num(r.get("VALOR")), r.get("UNIDAD"), r.get("DESDE") or None, r.get("HASTA") or None,
        ))
    if not tuplas:
        return 0
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO uocra_adicionales
                   (clave, concepto_num, titulo, texto, acuerdo_ref, valor, unidad, desde, hasta)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (clave) DO NOTHING""",
                tuplas,
            )
        conn.commit()
    _cache_bust("uocra_adicionales")
    return len(tuplas)


def leer_materiales_historico(id_proveedor: str) -> list[dict]:
    key = f"materiales:{id_proveedor}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id_proveedor, descripcion, fecha, precio FROM materiales_cotizaciones "
                "WHERE id_proveedor = %s ORDER BY fecha",
                (id_proveedor,),
            )
            rows = cur.fetchall()
    resultado = [{"ID_PROVEEDOR": r["id_proveedor"], "DESCRIPCION": r["descripcion"],
                   "FECHA": r["fecha"].isoformat(), "PRECIO": r["precio"]} for r in rows]
    _cache_set(key, resultado)
    return resultado


def upsert_materiales_historico_bulk(registros: list[dict]) -> int:
    tuplas = []
    for r in registros:
        id_prov, desc, fecha = r.get("ID_PROVEEDOR"), r.get("DESCRIPCION"), r.get("FECHA")
        if not (id_prov and desc and fecha):
            continue
        tuplas.append((id_prov, desc, fecha, _num(r.get("PRECIO"))))
    if not tuplas:
        return 0
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO materiales_cotizaciones (id_proveedor, descripcion, fecha, precio)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (id_proveedor, descripcion, fecha) DO NOTHING""",
                tuplas,
            )
        conn.commit()
    _cache_bust("materiales:")
    return len(tuplas)


def upsert_valores_ancha_bulk(serie: str, registros: list[dict], headers: list[str], fecha_col: str = "FECHA") -> int:
    """Como upsert_valores_ancha pero para TODAS las filas de una pestaña de
    una sola vez: una única conexión + un único executemany, en vez de
    reconectar por cada fecha (eso es lo que hacía que la migración de DOLAR
    tardara una eternidad y se cortara a mitad de camino - miles de conexiones
    en vez de una)."""
    tuplas = []
    for r in registros:
        fecha = r.get(fecha_col)
        if not fecha:
            continue
        for col in headers:
            val = r.get(col)
            if val in (None, ""):
                continue
            tuplas.append((serie, col, fecha, _num(val)))
    if not tuplas:
        return 0
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO series_valores (serie, columna, fecha, valor)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (serie, columna, fecha) DO NOTHING""",
                tuplas,
            )
        conn.commit()
    _cache_bust(f"ancha:{serie}")
    return len(tuplas)


def guardar_curva_cauciones(curva: list[dict]) -> int:
    """Snapshot de la curva completa de cauciones — SE PISA entera en cada
    refresh (no es histórico, es la foto de ahora; el histórico de 4 plazos
    de referencia va aparte, a series_valores/CAUCION). Si `curva` viene
    vacía (BYMA no respondió), NO se toca la tabla — mejor dato viejo que
    tabla vacía."""
    if not curva:
        return 0
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("truncate table mercado_curva_cauciones")
            cur.executemany(
                """INSERT INTO mercado_curva_cauciones
                   (plazo_dias, vencimiento, tasa, tasa_cierre_anterior, bid, offer, volumen, actualizado_en)
                   VALUES (%s,%s,%s,%s,%s,%s,%s, now())""",
                [(c["plazo_dias"], c.get("vencimiento"), c.get("tasa"), c.get("tasa_cierre_anterior"),
                  c.get("bid"), c.get("offer"), c.get("volumen")) for c in curva],
            )
        conn.commit()
    return len(curva)


def guardar_tasas_mav(filas: list[dict]) -> int:
    """Snapshot de tasas MAV (cheques/pagarés) — mismo criterio: se pisa
    entera, no-op si viene vacía."""
    if not filas:
        return 0
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("truncate table mercado_tasas_mav")
            cur.executemany(
                """INSERT INTO mercado_tasas_mav
                   (instrumento, moneda, segmento, rango, tna, tea, tem, monto, actualizado_en)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())""",
                [(f["instrumento"], f["moneda"], f["segmento"], f["rango"],
                  f.get("tna"), f.get("tea"), f.get("tem"), f.get("monto")) for f in filas],
            )
        conn.commit()
    return len(filas)


# ── KPI de uso de Supabase (plan free = 500 MB) ──────────────────────────────
LIMITE_MB = 500  # plan free de Supabase

def uso_supabase() -> dict:
    """Tamaño de la base + top tablas, para anticipar el límite del plan free.
    Cacheado 1h (no cambia rápido)."""
    key = "uso_supabase"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database()) AS b")
            total_b = cur.fetchone()["b"]
            cur.execute(
                """SELECT c.relname AS tabla,
                          pg_total_relation_size(c.oid) AS b
                     FROM pg_class c
                     JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                    ORDER BY pg_total_relation_size(c.oid) DESC
                    LIMIT 8"""
            )
            top = [{"tabla": r["tabla"], "mb": round(r["b"] / 1048576, 2)} for r in cur.fetchall()]
    usado_mb = round(total_b / 1048576, 2)
    out = {
        "usado_mb": usado_mb,
        "limite_mb": LIMITE_MB,
        "pct": round(usado_mb / LIMITE_MB * 100, 1),
        "top_tablas": top,
    }
    _cache_set(key, out)
    return out
