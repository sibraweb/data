# Python vs JavaScript: la misma cuenta, dos veces

La página publicada (sibraweb.github.io/data/) es un estático: no hay dónde
correr `api/server.py`, así que la matemática de los índices está escrita dos
veces — en `api/*.py` y en `shared/sibra-indices-api.js`. **El Python manda.**
Si cambia una, hay que cambiar la otra y volver a correr esta comparación.

## Cómo se corre

1. Levantar el server local: `python api/server.py` (o el preset `indices`).
2. Abrir `http://localhost:8100/` — ahí conviven las dos implementaciones: la
   página habla con Flask, y `SbIndices` está cargado en la misma ventana.
3. En la consola del navegador, para cada caso: pedirle el resultado a Flask
   (`/api/...`), pasarle los MISMOS registros crudos a la función JS, y
   comparar punto por punto (fechas y valores).

La clave es que los dos lados coman exactamente los mismos registros: si se
comparan contra lecturas distintas, una diferencia no dice nada.

## Resultado — 2026-09-06

| Caso | Función | Resultado |
|---|---|---|
| UOCRA ÷ CER (merge asof + ratio) | `ajustar` | ✓ 73 puntos, dif. máx. 0 |
| CAMARCO materiales nominal | `ajustar` (modo nominal) | ✓ 187 puntos, dif. máx. 0 |
| Alquiler CABA ÷ dólar blue | `ajustar` | ✓ 74 puntos, dif. máx. 0 |
| IPC encadenado a nivel base 100 | `construirIndiceNivel` | ✓ 307 puntos, dif. máx. 0 |
| Variación CER 15-01-24 → 10-06-26 + TIR | `variacionDe` | ✓ los 7 campos iguales |
| Curva mensual combinada (real + REM + repartido) | `construirCurvaMensual` | ✓ 336 meses, fuentes y anclas alineadas |
| Resumen por año | `resumenPorAnio` | ✓ idéntico |
| Modelo OLS UOCRA / RIPTE / Construcción | `estimarModelo` | ✓ a, b_ipc, b_fx, r², n dentro de 1e-9 |
| Proyección de las tres | `proyectar` | ✓ 6 puntos cada una, dif. máx. 0 |

Las únicas "diferencias" que aparecen son el orden de las claves del JSON
(Flask las serializa alfabéticamente) — los valores son los mismos.

## Lo que encontró la comparación

**1. Empates en el merge asof.** Cuando la fecha de la serie base cae a la
misma distancia de dos puntos del índice (ej. alquiler de oct-2018: el blue
tiene dato el 28-oct y el 3-nov, 3 días para cada lado), pandas se queda con
el **anterior**. La primera versión del JS tomaba el posterior y daba 36 en vez
de 37. Eran 2 filas sobre 74 — el tipo de diferencia que no se ve mirando un
gráfico. Corregido en `asofNearest`.

**2. `/api/proyectar` tiraba 500, y no por el port.** Desde que el REM vive en
Postgres, `MEDIANA` llega como `decimal.Decimal` (la columna es `numeric`) y no
como el float que devolvía Sheets; `proyeccion.py:95` dividía Decimal por float
y explotaba con `TypeError`. La proyección no se veía en UOCRA, RIPTE ni
Construcción **tampoco en local**. Corregido con `float()` explícito al leer la
curva.

## Lo que esta comparación NO cubre

- El camino de lectura contra Supabase (`SibraSB.selectAll`, `leer`, `leerRem`,
  `financiamiento` y el router `get`). Necesita una sesión de usuario, así que
  se prueba entrando a la página publicada. Lo verificado del login es que el
  modal aparece, que la petición llega a Supabase Auth y que una credencial
  equivocada muestra "Invalid login credentials" sin dejar la pantalla colgada.
- La pestaña **Materiales**, que no funciona sin `api/server.py` por diseño:
  las cotizaciones vivas salen de la Sheet de Obra vía OAuth de Google.
