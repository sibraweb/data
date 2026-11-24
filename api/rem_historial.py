"""
Historial de las últimas publicaciones del REM, para comparar cómo se mueven
las expectativas de inflación de una encuesta a la siguiente.

Es ADITIVO: reutiliza construir_curva_mensual() de rem_estimaciones.py tal
cual está (la misma metodología de la curva combinada) y no cambia nada de
ella. Lo único propio de acá es QUÉ datos recibe cada publicación:

  - REM mensual y anclas interanuales: solo las filas de ESE relevamiento
    (FECHA_PRONOSTICO), no las del último.
  - IPC real de INDEC: solo lo que ya se conocía cuando se hizo la encuesta.
    El REM se releva los últimos días del mes S (FECHA_PRONOSTICO cae en S) y
    para entonces INDEC ya publicó el IPC de S-1 (sale a mediados de S), no el
    de S. Así que el corte es: periodo real < primer día del mes de la encuesta.

Con ese corte la curva de cada publicación sale igual aunque se arme semanas
después (no se cuela información posterior), y además se guarda congelada en
`rem_publicaciones` la primera vez que se ve (ver db.guardar_rem_publicacion).
"""

from __future__ import annotations

from rem_estimaciones import construir_curva_mensual

CANTIDAD = 5


def fechas_publicaciones(*grupos: list[dict], n: int = CANTIDAD) -> list[str]:
    """Las `n` FECHA_PRONOSTICO más recientes (de más nueva a más vieja) entre
    los grupos de filas del REM que se pasen."""
    fechas = {str(r["FECHA_PRONOSTICO"])[:10] for g in grupos for r in g if r.get("FECHA_PRONOSTICO")}
    return sorted(fechas, reverse=True)[:n]


def armar_publicacion(
    fecha_pronostico: str,
    rem_ipc: list[dict],
    rem_interanual: list[dict],
    inflacion_real: list[dict],
) -> dict:
    """rem_ipc / rem_interanual: filas de rem_forecast (todas las fechas, se
    filtra acá). inflacion_real: filas de INFLACION_INDEC ({FECHA, VALOR})."""
    fp = str(fecha_pronostico)[:10]
    corte = f"{fp[:7]}-01"

    mensual = [{"PERIODO": str(r["PERIODO"])[:10], "MEDIANA": float(r["MEDIANA"])}
               for r in rem_ipc
               if str(r["FECHA_PRONOSTICO"])[:10] == fp and r.get("MEDIANA") is not None]
    interanual = [{"PERIODO": str(r["PERIODO"])[:10], "MEDIANA": float(r["MEDIANA"])}
                  for r in rem_interanual
                  if str(r["FECHA_PRONOSTICO"])[:10] == fp and r.get("MEDIANA") is not None]
    reales = [{"PERIODO": str(r["FECHA"])[:10], "VALOR": float(r["VALOR"])}
              for r in inflacion_real
              if r.get("VALOR") not in (None, "") and str(r["FECHA"])[:10] < corte]

    curva = construir_curva_mensual(reales, mensual, interanual)
    return {
        "fecha_pronostico": fp,
        "datos": {"rem_ipc": mensual, "rem_ipc_interanual": interanual, "reales": reales},
        "curva": curva,
    }
