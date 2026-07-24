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

### Ajuste de monto en la pantalla Resumen

La pestaña **Resumen** también tiene **"Monto a ajustar"**. Después de apretar
**Calcular variación** (que llena la columna *Personalizado* con la variación de
cada índice entre las dos fechas), la columna **"Monto ajustado"** muestra el
importe llevado por **cada** índice:

```
coeficiente    = valor_hasta / valor_desde   (si no viniera, se deriva de la variación %)
monto ajustado = monto × coeficiente
```

Sirve para comparar de un vistazo cuánto da el mismo importe ajustado por CER, por
dólar, por IPC, etc. Se recalcula al vuelo mientras se tipea, sin volver a llamar
a la API.

## Proyección con el REM — la lógica (a generalizar)

El REM da **tres cosas**: los **meses puntuales** (jul, ago, sep…), la **proyección
a fin de año** (dic/dic) y la de los **próximos 12 meses**. La proyección se arma
como una **cadena de anclas**, y en cada tramo se reparte **geométricamente**
(nunca promediando — la inflación se compone):

```
objetivo del tramo   (1 + A)
acumulado ya conocido(1 + a)
falta                F = (1+A)/(1+a)
meses restantes      r
cada mes restante    F^(1/r) − 1        ← raíz r-ésima
```

Orden de prioridad por mes: **(1)** dato real de INDEC si ya se publicó → **(2)**
curva mensual del último REM → **(3)** repartido geométrico contra el ancla
interanual más cercana (dic/dic, o 12/24 meses hacia adelante). Ej.: se completa
hasta dic-26 con el ancla de fin de año, y de dic-26 a jul-27 se vuelve a repartir
geométricamente contra el ancla de los próximos 12 meses, descontando lo acumulado.

**Estado:** implementado **solo para inflación** (`rem_interanual_repartido`, ver
`api/proyeccion.py` y la tabla "REM anual" del front). **Pendiente:** generalizarlo
a los demás índices, reemplazando la regresión OLS actual (que depende del R² y es
más endeble).

**Decisión abierta — cuál es el ancla de cada índice:**
- **CER / UVA / UVI / ICL** → siguen el IPC ⇒ sirve el ancla de inflación del REM.
- **Dólar** → el REM tiene su propia proyección de dólar.
- **UOCRA / materiales / CAC** → ⚠ no hay ancla en el REM. Definir si se proyectan
  con inflación o con una expectativa propia.
