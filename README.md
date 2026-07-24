# Sibratech · Índices

Dashboard interno de índices económicos/de construcción (dólar, CER, UVA,
UOCRA, RIPTE, materiales), con ajuste/comparación entre series (ej. salario
UOCRA ÷ CER, cemento ÷ dólar). Mismo patrón que `sibra-obra-repo`: server
local (Flask + Google Sheets como DB) + frontend estático que le pega por LAN.

Ver `api/SETUP.md` para levantar el servidor por primera vez.

## Estado de las fuentes

| Serie | Fuente | Estado |
|---|---|---|
| CER, UVA | `api.bcra.gob.ar` | ✅ automático |
| Dólar (oficial/blue/MEP/CCL/mayorista) | `dolarapi.com` | ✅ automático (solo valor del día — la serie se arma día a día) |
| RIPTE | scrape mensual de argentina.gob.ar | ✅ automático |
| REM — previsiones IPC y tipo de cambio | Excel histórico de BCRA (`historico-relevamiento-expectativas-mercado.xlsx`), se pisa entero cada mes | ✅ automático — ventana "Proyecciones (REM)" muestra la curva del último relevamiento |
| UOCRA | histórico migrado, sin scraper | ⏳ pendiente relevar fuente de paritarias |
| Materiales (Cerámica Norte, Construcciones en Seco, SERINAR) | `COTIZACIONES` de `sibra-obra-repo` (pipeline de mail ya existente) | ✅ se lee en vivo, sin reingesta propia |
| Materiales (Che Camba, Electropunto) | — | ⏳ pendiente parser en Obra |

## Proyección (UOCRA, Construcción, RIPTE)

Cada una de estas 3 ventanas tiene un checkbox "Ver proyección": estima por
regresión (OLS simple, `api/proyeccion.py`) cuánto explica la variación %
mensual de esa serie la variación % mensual de CER y del dólar oficial
histórico, y extrapola esa relación hacia adelante usando la curva de
previsión del REM. Siempre muestra el **R²** del ajuste junto al gráfico —
es un ajuste histórico simple, no un modelo econométrico, así que hay que
mirar el R² antes de confiar en la extrapolación (si es bajo, esa serie no
se explica bien por CER/dólar solos).

## Calcular entre dos fechas — ajustar un monto

Debajo de cada gráfico está el bloque **"Calcular entre dos fechas"**, que corre
sobre la MISMA serie graficada (con el ajuste elegido) y devuelve la variación %
y la TIR anualizada entre las dos fechas.

Además del %, se puede **ajustar un importe**: se carga un valor en **"Monto a
ajustar"** y la tabla muestra el **coeficiente** y el **monto ajustado**:

```
coeficiente    = valor_hasta / valor_desde
monto ajustado = monto × coeficiente
```

Sirve para responder "si en tal fecha esto costaba $X, ¿a cuánto equivale hoy
según este índice?". El monto se recalcula **al vuelo** mientras se tipea, usando
el coeficiente del último cálculo — no vuelve a pegarle a la API. Si se cambian
las fechas o el ajuste hay que apretar **Calcular variación** de nuevo.

Ojo con el criterio de fechas: si la serie es mensual y la fecha pedida cae en
medio de un mes, se usa el último dato publicado en o antes de esa fecha (ej. IPC
del 3 de abril = el dato de fin de marzo).
