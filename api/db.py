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

import datetime as _dt
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


def frescura() -> list[dict]:
    """Cada serie, cuantos valores tiene y hace cuantos dias que no crece.

    ⚠ POR QUE ESTO Y NO `chequear_fuentes.py`. Ese corre TODAS las fuentes
    —sale a internet— y tarda; sirve para diagnosticar. Esto lee la base y
    contesta en un segundo, que es lo que una vista necesita para abrirse.

    Juan, 2026-09-13: *«la vista general de indices deberia tener todos los
    indices relevados y decir desde hace cuanto no actualiza, asi vemos si hay
    algun problema»*. Y hace falta justamente porque ahora corren solas: «corre
    solo» sin nadie mirando es como estuvieron los schedulers en agosto,
    apagados, con todas las fuentes contestando bien y las series sin crecer.

    ⚠ LOS DIAS SE CUENTAN CONTRA HOY, NO CONTRA LA ULTIMA CORRIDA. Un job que
    corre todos los dias y trae siempre el mismo ultimo dato esta muerto y el
    historial no lo dice: dice «ok» todos los dias.

    `atraso_normal` es cada cuanto PUBLICA la fuente, no cada cuanto corremos:
    el ICC sale una vez por mes con un mes de rezago, asi que 44 dias es lo
    esperable y 197 no. Sin ese dato la vista mostraria en rojo la mitad de las
    series mensuales y se aprenderia a ignorarla.
    """
    # dias que es NORMAL que una serie este sin moverse, por como publica
    TOLERANCIA = {
        "diaria": 5,       # habiles + fin de semana largo
        "mensual": 50,     # sale con un mes de rezago
        "trimestral": 130,
    }
    CADENCIA = {
        # diarias: bancarias, dolar, indices de mercado
        "DOLAR": "diaria", "CER": "diaria", "UVA": "diaria", "UVI": "diaria",
        "ICL": "diaria", "BADLAR": "diaria", "BAIBAR": "diaria",
        "TM20": "diaria", "TAMAR": "diaria", "TIM": "diaria",
        "MERVAL": "diaria", "RIESGO_PAIS": "diaria", "CAUCION": "diaria",
        "CHEQUES": "diaria", "PAGARES": "diaria", "USO_JUSTICIA": "diaria",
        "DEPOSITOS_30D": "diaria", "ADELANTOS_CTA_CTE": "diaria",
        "ADELANTOS_GRANDES": "diaria", "PRESTAMOS_PERSONALES": "diaria",
        "CERT_BNA_TNA_GRANDES": "diaria", "CERT_BNA_TNA_MIPYME": "diaria",
        "CERT_BNA_IND_GRANDES": "diaria", "CERT_BNA_IND_MIPYME": "diaria",
    }
    cx = _conectar()
    try:
        with cx.cursor() as cur:
            cur.execute("""
                SELECT serie, COUNT(*) AS n,
                       MIN(fecha) AS desde, MAX(fecha) AS hasta,
                       (CURRENT_DATE - MAX(fecha)) AS dias
                  FROM public.series_valores
                 GROUP BY serie ORDER BY 5 DESC NULLS FIRST""")
            filas = cur.fetchall()
    finally:
        cx.close()

    out = []
    for f in filas:
        # ⚠ el cursor devuelve DICTS, no tuplas: `f[0]` daba KeyError. Se
        # accede por nombre, que ademas no se rompe si la consulta cambia de
        # orden manana.
        serie = f["serie"]
        dias = f["dias"]
        cad = CADENCIA.get(serie, "mensual")
        tope = TOLERANCIA[cad]
        # ⚠ un valor con fecha FUTURA no esta atrasado: el salario minimo se
        # publica por adelantado. `dias` negativo -> al dia.
        atrasada = dias is not None and dias > tope
        out.append({
            "serie": serie, "valores": f["n"],
            "desde": f["desde"].isoformat() if f["desde"] else None,
            "hasta": f["hasta"].isoformat() if f["hasta"] else None,
            "dias_sin_actualizar": dias,
            "cadencia": cad, "tolerancia_dias": tope,
            "atrasada": atrasada,
        })
    return out


# ── Redeterminacion por indice de contrato ──────────────────────────────────
#
# ⚠ ESTO NO ES LA POLINOMICA DE INDEC. Juan, 2026-09-13: *«cuando cerramos una
# orden de venta definimos el indice con el cliente, por ejemplo camarco; cuando
# determinamos una orden de trabajo con un proveedor definimos con el el indice,
# por ejemplo uocra»*. Es UN indice por contrato, pactado al firmar. La base de
# 436 insumos de INDEC (`indec_op_*`) es otra cosa: *«por ahora va a ser solo un
# control de gestion»*, para comparar contra proveedores y MercadoLibre.
#
# Por eso el calculo vive aca y no en Obra: Obra pide el salto y no tiene que
# saber la regla del mes anterior ni como se busca un mes en cada serie.

# Series que sirven como indice de contrato. No es un filtro de seguridad: es
# para que la pantalla ofrezca estas y no BADLAR o el riesgo pais, que estan en
# la misma tabla y no son indices de ajuste de obra.
SERIES_CONTRATO = {
    "CAC": "CAMARCO - costo de la construccion",
    "ICC_CABA": "ICC INDEC - CABA",
    "ICC_BUENOS_AIRES": "ICC INDEC - Buenos Aires",
    "ICC_CORDOBA": "ICC INDEC - Cordoba",
    "ICC_SANTA_FE": "ICC INDEC - Santa Fe",
    "APYMECO": "APYMECO - indice de la construccion (La Plata)",
    "UOCRA": "Jornales UOCRA por categoria",
    "SALARIOS": "Indice de salarios (INDEC)",
    "RIPTE": "RIPTE",
    "SMVM": "Salario minimo vital y movil",
    "INFLACION_INDEC": "IPC (INDEC)",
    "CER": "CER",
    "UVA": "UVA",
    "UVI": "UVI",
    "ICL": "ICL (alquileres)",
}


def guardar_provisorios(serie: str, filas: list[dict], foto: str | None = None) -> dict:
    """Registra que meses de `serie` estan provisorios, guardando SOLO los cambios.

    `filas`: [{"FECHA": "2026-07-31", "PROVISORIO": True}, ...]

    ⚠ SOLO LOS DELTAS. La primera corrida entra entera (linea de base); las
    siguientes escriben unicamente los meses cuyo flag cambio. Si no, serian
    187 filas por corrida para registrar los 2 o 3 que se movieron.

    ⚠ Y EL DELTA COMPARA EL FLAG, QUE ES LO UNICO QUE HAY. Parece obvio dicho
    asi, pero en `indec_op_revisiones` el delta comparaba solo el VALOR y por
    eso el mes que pasaba a definitivo sin cambiar de numero no dejaba fila: la
    ratificacion —el dato que dice que el provisorio servia— era invisible.
    Aca el flag ES el dato, asi que no hay forma de repetir ese error, pero
    queda escrito para que nadie "optimice" comparando el valor.

    Devuelve {"nuevos": n, "cambios": n, "sin_cambio": n}.
    """
    if not filas:
        return {"nuevos": 0, "cambios": 0, "sin_cambio": 0}
    foto = foto or _dt.date.today().isoformat()
    ahora = {f["FECHA"]: bool(f["PROVISORIO"]) for f in filas if f.get("FECHA")}

    with _conectar() as cx, cx.cursor() as cur:
        # ⚠ si ya hay una foto POSTERIOR cargada, el delta se calcularia al
        # revés y mentiria en las dos filas. Se avisa y no se escribe.
        cur.execute("SELECT COUNT(*) AS n FROM series_provisorios "
                    "WHERE serie = %s AND foto > %s", (serie, foto))
        if cur.fetchone()["n"]:
            return {"nuevos": 0, "cambios": 0, "sin_cambio": 0,
                    "error": f"ya hay fotos posteriores a {foto} para {serie}"}
        cur.execute("""
            SELECT DISTINCT ON (fecha) fecha, provisorio
              FROM series_provisorios
             WHERE serie = %s AND foto <= %s
             ORDER BY fecha, foto DESC""", (serie, foto))
        previo = {r["fecha"].isoformat(): r["provisorio"] for r in cur.fetchall()}

        nuevas, cambios, iguales = [], 0, 0
        for fecha, prov in sorted(ahora.items()):
            if fecha in previo:
                if previo[fecha] == prov:
                    iguales += 1
                    continue
                cambios += 1
            nuevas.append((serie, fecha, foto, prov))
        if nuevas:
            cur.executemany(
                "INSERT INTO series_provisorios (serie, fecha, foto, provisorio) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", nuevas)
            cx.commit()
    _cache_bust("provisorio")
    return {"nuevos": len(nuevas) - cambios, "cambios": cambios,
            "sin_cambio": iguales}


def estado_provisorio(serie: str, fecha: str) -> bool | None:
    """Si ese periodo esta provisorio HOY. None = la fuente no lo dice.

    ⚠ None NO ES "definitivo". De las 36 series, hoy solo el CAC publica la
    distincion; para el resto no se sabe y hay que decirlo asi.
    """
    with _conectar() as cx, cx.cursor() as cur:
        cur.execute("""
            SELECT provisorio FROM series_provisorios
             WHERE serie = %s AND fecha = %s
             ORDER BY foto DESC LIMIT 1""", (serie, fecha))
        r = cur.fetchone()
    return None if r is None else bool(r["provisorio"])


def historia_provisorio(serie: str) -> list[dict]:
    """Cada periodo que salio provisorio y cuando lo vimos cerrar.

    Es el equivalente de `revisiones_indec.py` para las series de contrato: con
    esto se puede contestar "el numero con el que liquide ese certificado sigue
    siendo el mismo" sin ir a buscar una planilla vieja.
    """
    with _conectar() as cx, cx.cursor() as cur:
        cur.execute("""
            SELECT fecha,
                   MIN(foto) FILTER (WHERE provisorio)     AS prov_desde,
                   MIN(foto) FILTER (WHERE NOT provisorio) AS def_desde
              FROM series_provisorios
             WHERE serie = %s
             GROUP BY fecha ORDER BY fecha""", (serie,))
        filas = cur.fetchall()
    out = []
    for f in filas:
        pd_, dd = f["prov_desde"], f["def_desde"]
        out.append({
            "fecha": f["fecha"].isoformat(),
            "provisorio_desde": pd_.isoformat() if pd_ else None,
            "definitivo_desde": dd.isoformat() if dd else None,
            # ⚠ techo, no plazo: solo sabemos que cerro entre dos bajadas
            "dias_hasta_verlo_cerrado": (dd - pd_).days if (pd_ and dd) else None,
            "sigue_provisorio": bool(pd_ and not dd),
        })
    return out


def redet_series() -> list[dict]:
    """Los indices que se pueden pactar en un contrato, con sus columnas.

    Devuelve tambien hasta que mes llega cada uno: un contrato con un indice que
    dejo de publicarse no se puede redeterminar, y eso hay que verlo ANTES de
    firmar, no cuando hay que emitir el certificado.
    """
    with _conectar() as cx, cx.cursor() as cur:
        cur.execute("""
            SELECT serie, columna, COUNT(*) AS n, MAX(fecha) AS hasta
              FROM series_valores
             WHERE serie = ANY(%s)
             GROUP BY serie, columna
             ORDER BY serie, columna""", (list(SERIES_CONTRATO),))
        filas = cur.fetchall()
    out: dict[str, dict] = {}
    for f in filas:
        d = out.setdefault(f["serie"], {
            "serie": f["serie"], "nombre": SERIES_CONTRATO[f["serie"]],
            "columnas": [], "hasta": None,
        })
        d["columnas"].append({
            "columna": f["columna"], "valores": f["n"],
            "hasta": f["hasta"].isoformat() if f["hasta"] else None,
        })
        h = f["hasta"].isoformat() if f["hasta"] else None
        if h and (d["hasta"] is None or h > d["hasta"]):
            d["hasta"] = h
    return [out[k] for k in sorted(out)]


def redet_valor_mes(serie: str, columna: str, periodo: str) -> dict | None:
    """El valor de un indice en un MES. `periodo` es "YYYY-MM".

    ⚠ NO SE BUSCA POR FECHA EXACTA. Cada serie fecha el mes a su manera: CAC e
    ICC guardan fin de mes (2026-07-31), UOCRA guarda el primero (2026-08-01).
    Pedir una fecha puntual devolvia None para la mitad de las series sin decir
    por que. Se busca dentro del mes calendario.

    ⚠ Y SI LA SERIE ES DIARIA (CER, UVA, ICL) SE TOMA EL ULTIMO DIA DEL MES, y
    la respuesta lo dice en `dias_en_el_mes`. Es una convencion elegida, no un
    dato del contrato: un contrato en CER suele fijar una fecha exacta. Si
    `dias_en_el_mes` viene > 1, quien consume tiene que decidir a conciencia.
    """
    with _conectar() as cx, cx.cursor() as cur:
        cur.execute("""
            SELECT fecha, valor, COUNT(*) OVER () AS dias
              FROM series_valores
             WHERE serie = %s AND columna = %s
               AND date_trunc('month', fecha) = date_trunc('month', %s::date)
               AND valor IS NOT NULL
             ORDER BY fecha DESC
             LIMIT 1""", (serie, columna, periodo + "-01"))
        r = cur.fetchone()
    if not r:
        return None
    return {
        "periodo": periodo,
        "fecha": r["fecha"].isoformat(),
        "indice": float(r["valor"]),
        "dias_en_el_mes": int(r["dias"]),
        # ⚠ TRES ESTADOS: True provisorio, False definitivo, None la fuente no
        # lo dice. Hoy solo el CAC publica la distincion; devolver False para
        # las otras 35 series seria afirmar algo que no sabemos.
        "provisorio": estado_provisorio(serie, r["fecha"].isoformat()),
    }


def _mes_anterior(periodo: str) -> str:
    """"2026-04" -> "2026-03". La norma de Juan, en las dos puntas."""
    a, m = (int(x) for x in periodo.split("-")[:2])
    return f"{a - 1}-12" if m == 1 else f"{a}-{m - 1:02d}"


def redet_salto(serie: str, columna: str, base: str, redet: str,
                mes_anterior: bool = True) -> dict:
    """El factor de redeterminacion entre dos meses de contrato.

    ⚠ LA REGLA DEL MES ANTERIOR LA APLICA ESTA FUNCION, no quien la llama.
    Norma de Juan: la redeterminacion se hace SIEMPRE con el indice del mes
    anterior, en las dos puntas —abril->agosto busca marzo->julio— porque el
    indice del mes que arranca todavia no esta publicado cuando arranca. Que la
    aplique Obra, o la planilla, o la persona, es la forma de que un certificado
    salga con el mes corrido y nadie lo note.

    `mes_anterior=False` existe para el caso en que un contrato pacte otra cosa
    por escrito. No es el default y la respuesta deja dicho cual se uso.
    """
    m_base = _mes_anterior(base) if mes_anterior else base
    m_redet = _mes_anterior(redet) if mes_anterior else redet
    v_base = redet_valor_mes(serie, columna, m_base)
    v_redet = redet_valor_mes(serie, columna, m_redet)

    faltan = [m for m, v in ((m_base, v_base), (m_redet, v_redet)) if v is None]
    if faltan:
        return {"error": "sin indice publicado", "faltan": faltan,
                "serie": serie, "columna": columna}
    if not v_base["indice"]:
        return {"error": "el indice base es cero: no se puede dividir",
                "serie": serie, "columna": columna, "base": v_base}

    factor = v_redet["indice"] / v_base["indice"]
    return {
        "serie": serie, "columna": columna,
        "regla": ("indice del mes anterior en las dos puntas" if mes_anterior
                  else "indice del mes del contrato (regla del mes anterior DESACTIVADA)"),
        "mes_contrato_base": base, "mes_contrato_redet": redet,
        "base": v_base, "redet": v_redet,
        "factor": factor,
        "variacion": factor - 1,
        # ⚠ el aviso viaja con el numero: una serie diaria promediada a mes no
        # es lo mismo que un indice mensual y el que emite el certificado tiene
        # que verlo sin ir a buscarlo.
        "avisos": [a for a in (
            ("la serie es diaria: se tomo el ULTIMO dia de cada mes"
             if max(v_base["dias_en_el_mes"], v_redet["dias_en_el_mes"]) > 1 else None),
            # ⚠ ESTE ES EL AVISO QUE IMPORTA. Si una punta esta provisoria, el
            # factor puede moverse cuando la fuente la cierre. No bloquea: se
            # liquida con el provisorio a proposito (norma de Juan). Pero el
            # que emite el certificado tiene que saber que va a haber que
            # controlarlo despues, y por eso viaja con el numero.
            ("PUNTA BASE PROVISORIA (%s): el factor puede cambiar cuando la "
             "fuente la cierre" % v_base["periodo"]
             if v_base.get("provisorio") else None),
            ("PUNTA DE REDETERMINACION PROVISORIA (%s): el factor puede "
             "cambiar cuando la fuente la cierre" % v_redet["periodo"]
             if v_redet.get("provisorio") else None),
        ) if a],
        # para que el consumidor pueda decidir sin leer texto
        "alguna_punta_provisoria": bool(v_base.get("provisorio")
                                        or v_redet.get("provisorio")),
    }


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
                   -- ⚠ DO UPDATE Y NO DO NOTHING. La `clave` incluye el md5
                   -- del texto, asi que misma clave = mismo contenido y
                   -- reescribir es idempotente. Con DO NOTHING, tres filas
                   -- escritas por una version vieja quedaron sin titulo ni
                   -- texto (medido 13/09/2026: el aporte solidario y la
                   -- contribucion empresarial estaban en la base sin decir
                   -- QUE eran) y no habia corrida que las arregle.
                   -- ⚠ Y OJO CON EL SIGNO DE PORCENTAJE EN ESTE COMENTARIO:
                   -- psycopg lo lee como placeholder y contesta "incomplete
                   -- placeholder" sin nombrar el comentario. Si hace falta,
                   -- va doblado.
                   ON CONFLICT (clave) DO UPDATE SET
                       concepto_num = EXCLUDED.concepto_num,
                       titulo       = EXCLUDED.titulo,
                       texto        = EXCLUDED.texto,
                       acuerdo_ref  = EXCLUDED.acuerdo_ref,
                       valor        = EXCLUDED.valor,
                       unidad       = EXCLUDED.unidad,
                       desde        = EXCLUDED.desde,
                       hasta        = EXCLUDED.hasta""",
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


def leer_cotizaciones(id_proveedor: str) -> list[dict]:
    """UNA lista de precios por proveedor, de `cotizaciones` — la tabla del
    módulo de insumos de Obra, que desde 2026-09-06 tiene también el histórico
    viejo adentro (origen='HISTORICO', ver
    unificar_materiales_en_cotizaciones.py).

    Antes esto se ARMABA: la Sheet de Obra por un lado y nuestro histórico por
    el otro. Se rompió sin hacer ruido cuando Obra migró a Postgres y renumeró
    los proveedores. Una sola fuente no se puede desempalmar.

    Las columnas de `cotizaciones` son todas `text` (viene de una planilla), así
    que el precio se convierte acá y las filas sin número se descartan: un
    precio vacío no es un precio de cero."""
    key = f"cotizaciones:{id_proveedor}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT descripcion, fecha, precio FROM cotizaciones "
                "WHERE id_proveedor = %s AND fecha <> '' AND precio <> '' "
                "ORDER BY fecha",
                (id_proveedor,),
            )
            rows = cur.fetchall()
    resultado = []
    for r in rows:
        try:
            precio = float(str(r["precio"]).replace(",", "."))
        except (TypeError, ValueError):
            continue
        resultado.append({"ID_PROVEEDOR": id_proveedor, "DESCRIPCION": r["descripcion"],
                          "FECHA": str(r["fecha"])[:10], "PRECIO": precio})
    _cache_set(key, resultado)
    return resultado


def proveedores_con_cotizaciones() -> dict:
    """{id: nombre} de los que TIENEN precios cargados, salido de la tabla.

    Esta lista estaba escrita a mano y con los ids viejos (43, 12, 64, 229)
    mientras los datos usaban los de Obra (23, 206, 122, 312): la pantalla
    pedía proveedores que no existían y no devolvía un solo precio, sin avisar.
    Preguntándole a la base eso no puede volver a pasar, y un proveedor nuevo
    aparece solo."""
    key = "cotizaciones:proveedores"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    with _conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id_proveedor, max(proveedor) AS nombre, count(*) AS n "
                "FROM cotizaciones WHERE id_proveedor <> '' "
                "GROUP BY id_proveedor ORDER BY n DESC"
            )
            rows = cur.fetchall()
    resultado = {r["id_proveedor"]: (r["nombre"] or r["id_proveedor"]) for r in rows}
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
