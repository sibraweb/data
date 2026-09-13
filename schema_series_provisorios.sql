-- Que valores de una serie estan marcados PROVISORIOS por la fuente, y desde
-- cuando. Va aparte de `series_valores` a proposito: esa tabla la escriben 36
-- scrapers por tres funciones genericas (`upsert_valores_simple`,
-- `upsert_valores_ancha`, `upsert_valores_ancha_bulk`) y agregarle una columna
-- por fila obligaba a tocar el camino de escritura de todas las fuentes para
-- un dato que hoy solo publican dos.
--
-- ⚠ POR QUE HACE FALTA. Juan liquida certificados con el indice del contrato
-- (CAMARCO con el cliente, UOCRA con el proveedor). Si CAMARCO revisa un mes,
-- la proxima bajada lo pisa y el numero con el que se liquido desaparece sin
-- dejar rastro. Medido en INDEC, donde esta tabla ya existe desde antes
-- (`indec_op_revisiones`): de 5.290 series-mes cerradas, 97,4% se ratificaron
-- sin cambio, pero el 2,6% que se movio llego a +5,20%.
--
-- ⚠ NO HAY COLUMNA `columna`. En el CAC el asterisco esta en la fila del
-- PERIODO, no en cada una de las tres series (costo/materiales/mano de obra):
-- es el mes el que es provisorio, no un renglon. Si aparece una fuente que
-- marque por renglon, se agrega entonces y no antes.
--
-- ⚠ AUSENCIA DE FILA = NO SABEMOS, no "definitivo". La mayoria de las 36
-- series no publican la distincion. Un consumidor que lea esta tabla tiene que
-- tratar el NULL como tercer estado (la regla del manual: un control que no
-- sabe tiene que decir que no sabe).
CREATE TABLE IF NOT EXISTS series_provisorios (
    serie      TEXT NOT NULL,
    fecha      DATE NOT NULL,   -- el periodo del indice, como en series_valores
    foto       DATE NOT NULL,   -- cuando lo leimos
    provisorio BOOLEAN NOT NULL,
    PRIMARY KEY (serie, fecha, foto)
);

CREATE INDEX IF NOT EXISTS idx_series_provisorios_serie
    ON series_provisorios (serie, fecha, foto);
