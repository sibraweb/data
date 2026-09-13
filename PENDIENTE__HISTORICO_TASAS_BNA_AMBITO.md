# PENDIENTE — histórico de tasas del BNA vía Ámbito

**Estado: relevado y probado a mano, NO implementado.** Juan, 11/09/2026:
*«anotá nomás todo cómo hacerlo, lo vemos después»*. Esto es la receta para
cuando se retome.

---

## Qué es, y por qué no se veía

Las páginas [tasas-activas-banco-nacion](https://www.ambito.com/contenidos/tasas-activas-banco-nacion.html)
y [tasas-pasivas-banco-nacion](https://www.ambito.com/contenidos/tasas-pasivas-banco-nacion.html)
de Ámbito **no traen los datos**: montan un `<iframe>` a una **planilla de
Google publicada**. Por eso bajarlas con `requests` devuelve una cáscara vacía,
y por eso tampoco se veían desde el navegador de la sesión (el iframe no
cargaba). Lo que hay que pedir es la planilla, no la página.

> Esto ya nos costó un rato: di por inaccesible una fuente que estaba abierta,
> igual que había pasado con el login de CAMARCO. **Cuando una página "no trae
> datos", mirar los iframes antes de darla por perdida.**

## La fuente

```
KEY  = 2PACX-1vQO9BxwDGXL5EIr0rAohUuAr10Fi3hiYPHQfTNCN17opmNz2IGHiSKEEPTFR-3FvYbPQKmEi1Dw6Hoh
LISTA  https://docs.google.com/spreadsheets/d/e/<KEY>/pubhtml
HOJA   https://docs.google.com/spreadsheets/d/e/<KEY>/pubhtml/sheet?headers=false&gid=<GID>
```

Se baja con un `GET` común, sin auth y sin navegador. Los `gid` salen de buscar
`gid=(\d+)` en el HTML de LISTA.

**Una hoja por año. 12 hojas relevadas al 11/09/2026:**

| gid | Año |
|---|---|
| 1598772329 | 2005 – 2007 |
| 1917690160 | 2009 |
| 1094637952 | 2010 |
| 1237222608 | 2011 |
| 1330178228 | 2013 |
| 1632211303 | 2014 (casi vacía: 4 filas) |
| 0 | **2018** |
| 1541919325 | 2021 |
| 1308278990 | 2022 |
| 1649749500 | 2023 |
| 2029045132 | 2025 |
| 1771614277 | 2026 |

⚠ **Faltan 2008, 2012, 2015, 2016, 2017, 2019, 2020 y 2024.** No es una serie
continua: es historia parcial. Hay que decir eso en cualquier pantalla que la
muestre, o alguien va a leer un hueco como un cero.

## Qué trae cada hoja

Columnas: **Fecha · Cartera General (TNA/TEA) · Adelanto Cta. Cte. con acuerdo ·
Descubiertos en Cta. Cte.** (con garantía hipotecaria, previamente solicitado,
no solicitado previamente TASA, no solicitado previamente CFT) — TNA y TEA cada
uno.

⚠ **La estructura CAMBIA entre años.** En 2018 la cartera general se abre en
**Diversas** y **Agropecuaria**; hoy es una sola. El parser tiene que leer los
encabezados de cada hoja, no asumir un orden fijo.

⚠ **Las fechas vienen AGRUPADAS POR RANGO** cuando la tasa no cambió:
`02/01 al 03/05/18`, `21 al 25/05/18`, `12 AL 15/06/2026`, `29/4/26 al 30/04/26`.
Hay que expandirlas a días. Ojo con las variantes: separador `al` o `AL`, año
de 2 o 4 dígitos, y a veces el año solo en la segunda fecha.

⚠ **Hay `s/d`** donde no hubo dato. No es cero: es que no se publicó.

⚠ **Hay comas donde debería haber puntos** (`26,02` en una fila de 2026,
`44,76` en una de 2026). Son typos de la planilla. Normalizar, y avisar si el
valor se aparta demasiado del día anterior.

## Verificación que ya pasó

El 11/09/2026 la hoja de 2026 da **cartera general TNA 26,48 / TEA 29,94**, y el
PDF del BNA que ya relevamos da exactamente lo mismo. O sea que es la misma
fuente, con historia.

## Lo que esto habilita

1. **Backfill de las activas** en vez de relevar solo hacia adelante. Hoy
   `scrapers/bna_tasas.py` saca la foto del día; esto le da pasado.
2. **El tramo TACG de los certificados.** La hoja de 2018 trae la cartera
   general diaria de todo el año — el insumo del tramo 01/01/2018 → 05/12/2018.
   *(Ese tramo YA quedó cubierto por la TNA relevada del archivo de CAMARCO; esto
   sería una segunda fuente independiente para contrastarlo.)*

## Criterio

Se releva, **no se publica** — mismo criterio que la base de CAMARCO
(Juan, 11/09/2026). Ver el candado sobre `RESUMEN_SERIES` en `api/server.py`.
