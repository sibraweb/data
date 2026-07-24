"""
Curva mensual de inflación combinada, armada en orden de prioridad:

  1) Dato REAL de INDEC (INFLACION_INDEC) — lo que ya se publicó.
  2) Curva mensual EXPLÍCITA del último REM ("var. % mensual", ~6-7 meses
     hacia adelante desde la fecha de la encuesta) — para los meses que el
     dato real todavía no cubre.
  3) Anclas INTERANUALES del REM ("var. % i.a.; dic-26/27/28", "jun-27",
     "jun-28"...) — cada una fija el nivel de precios de UN mes objetivo
     exacto respecto al mismo mes 12 meses antes. Como esas anclas quedan
     espaciadas ~6 meses entre sí (dic-26, jun-27, dic-27, jun-28, dic-28),
     se procesan en orden cronológico: la ventana de 12 meses de cada ancla
     casi siempre tiene la mitad ya resuelta (real, curva REM, o una ancla
     anterior) — el resto se reparte parejo (raíz N-ésima) para esa mitad
     puntual, en vez de asumir una tasa plana para el año entero.

Ej.: si dic-26 ya queda 100% cubierto por real+curva REM (nada que estimar),
"jun-27" (12 meses adelante) tiene la mitad de su ventana (jul-dic 2026) ya
resuelta por la curva REM — el residuo se reparte solo entre ene-jun 2027.
Después "dic-27" resuelve jul-dic 2027 con el mismo criterio, y así.
"""

from __future__ import annotations


def _factor_compuesto(pcts: list[float]) -> float:
    factor = 1.0
    for p in pcts:
        factor *= (1 + p / 100)
    return factor


def _restar_meses(anio: int, mes: int, n: int) -> tuple[int, int]:
    total = anio * 12 + (mes - 1) - n
    return total // 12, total % 12 + 1


def _ventana_12_meses(periodo_fin: str) -> list[str]:
    """Las 12 claves 'YYYY-MM' que terminan en `periodo_fin` (inclusive) — la
    ventana de 12 meses que define un interanual (ej. "jun-27" -> jul-26..jun-27)."""
    anio, mes = int(periodo_fin[:4]), int(periodo_fin[5:7])
    claves = []
    for i in range(11, -1, -1):
        a, m = _restar_meses(anio, mes, i)
        claves.append(f"{a:04d}-{m:02d}")
    return claves


def construir_curva_mensual(
    mensuales_reales: list[dict],
    curva_rem_mensual: list[dict],
    curva_rem_interanual: list[dict],
) -> list[dict]:
    """
    mensuales_reales: [{"PERIODO": "YYYY-MM-DD", "VALOR": pct}, ...] (INDEC real)
    curva_rem_mensual: [{"PERIODO": "YYYY-MM-DD", "MEDIANA": pct}, ...] (REM, último relevamiento)
    curva_rem_interanual: [{"PERIODO": "YYYY-MM-DD", "MEDIANA": pct}, ...] (REM, i.a. a cualquier mes objetivo)

    Devuelve una curva mensual continua y ordenada:
    [{"periodo": "YYYY-MM-01", "valor_pct": .., "fuente": "real"|"rem_mensual"|"rem_interanual_repartido"}, ...]
    """
    mapa: dict[str, dict] = {}
    for r in mensuales_reales:
        mapa[r["PERIODO"][:7]] = {"valor_pct": round(float(r["VALOR"]), 2), "fuente": "real"}
    for r in curva_rem_mensual:
        clave = r["PERIODO"][:7]
        if clave not in mapa:
            mapa[clave] = {"valor_pct": round(float(r["MEDIANA"]), 2), "fuente": "rem_mensual"}

    anclas = sorted(curva_rem_interanual, key=lambda r: r["PERIODO"])
    for ancla in anclas:
        ventana = _ventana_12_meses(ancla["PERIODO"][:7])
        faltantes = [c for c in ventana if c not in mapa]
        if not faltantes:
            continue

        cubiertos = [mapa[c]["valor_pct"] for c in ventana if c in mapa]
        factor_cubierto = _factor_compuesto(cubiertos)
        if factor_cubierto <= 0:
            continue

        factor_objetivo = 1 + float(ancla["MEDIANA"]) / 100
        n = len(faltantes)
        tasa = ((factor_objetivo / factor_cubierto) ** (1 / n) - 1) * 100
        for c in faltantes:
            # `ancla` = contra qué proyección interanual se repartió este mes.
            # Permite pintar cada tramo de un color distinto en el gráfico
            # (hasta dic-26, dic-26→jul-27, jul-27→dic-27, …).
            mapa[c] = {"valor_pct": round(tasa, 2),
                       "fuente": "rem_interanual_repartido",
                       "ancla": ancla["PERIODO"][:7]}

    return [{"periodo": f"{clave}-01", **datos} for clave, datos in sorted(mapa.items())]


def resumen_por_anio(curva_combinada: list[dict], curva_rem_interanual: list[dict]) -> dict[str, dict]:
    """Cuántos meses de cada fuente tiene cada año tocado por proyección
    (se omiten los años 100% reales, ya cerrados), más el REM anual (dic/dic)
    de referencia cuando existe para ese año."""
    anual_dic = {
        r["PERIODO"][:4]: float(r["MEDIANA"])
        for r in curva_rem_interanual if r["PERIODO"][5:7] == "12"
    }
    conteo: dict[str, dict] = {}
    for c in curva_combinada:
        anio = c["periodo"][:4]
        conteo.setdefault(anio, {"real": 0, "rem_mensual": 0, "rem_interanual_repartido": 0})
        conteo[anio][c["fuente"]] = conteo[anio].get(c["fuente"], 0) + 1

    resultado = {}
    for anio, datos in sorted(conteo.items()):
        if datos["rem_mensual"] == 0 and datos["rem_interanual_repartido"] == 0:
            continue
        resultado[anio] = {"rem_anual_pct": anual_dic.get(anio), **datos}
    return resultado
