-- ============================================================================
-- Vistas analíticas para apoyar el motor Text-to-SQL.
--
-- Escritas para SQLite (usa funciones strftime()). El bloque de comentarios
-- sobre cada vista indica el equivalente en PostgreSQL para facilitar la
-- migración (basta con sustituir strftime(...) por to_char(...)/date_trunc(...)).
-- ============================================================================

DROP VIEW IF EXISTS vw_ingresos_netos_mensuales;
DROP VIEW IF EXISTS vw_retencion_churn_trimestral;
DROP VIEW IF EXISTS vw_ltv_cliente;

-- ----------------------------------------------------------------------------
-- vw_ingresos_netos_mensuales
-- Ingresos netos por mes = (pagos de cuotas + ventas de productos) - gastos operativos
-- Postgres: reemplazar strftime('%Y-%m', fecha) por to_char(fecha, 'YYYY-MM')
-- ----------------------------------------------------------------------------
CREATE VIEW vw_ingresos_netos_mensuales AS
WITH ingresos_pagos AS (
    SELECT strftime('%Y-%m', fecha_pago) AS mes, SUM(COALESCE(monto, 0)) AS total
    FROM pagos
    GROUP BY mes
),
ingresos_ventas AS (
    SELECT strftime('%Y-%m', fecha) AS mes, SUM(cantidad * precio_unitario) AS total
    FROM ventas
    GROUP BY mes
),
gastos AS (
    SELECT strftime('%Y-%m', fecha) AS mes, SUM(monto) AS total
    FROM gastos_operativos
    GROUP BY mes
),
meses AS (
    SELECT mes FROM ingresos_pagos
    UNION
    SELECT mes FROM ingresos_ventas
    UNION
    SELECT mes FROM gastos
)
SELECT
    m.mes,
    COALESCE(ip.total, 0) AS ingresos_cuotas,
    COALESCE(iv.total, 0) AS ingresos_productos,
    COALESCE(ip.total, 0) + COALESCE(iv.total, 0) AS ingresos_totales,
    COALESCE(g.total, 0) AS gastos_totales,
    (COALESCE(ip.total, 0) + COALESCE(iv.total, 0)) - COALESCE(g.total, 0) AS ingreso_neto
FROM meses m
LEFT JOIN ingresos_pagos ip ON ip.mes = m.mes
LEFT JOIN ingresos_ventas iv ON iv.mes = m.mes
LEFT JOIN gastos g ON g.mes = m.mes
ORDER BY m.mes;

-- ----------------------------------------------------------------------------
-- vw_retencion_churn_trimestral
-- Por trimestre: membresías activas al inicio, canceladas durante el trimestre,
-- y tasa de churn = canceladas / activas_al_inicio. Retención = 1 - churn.
-- Postgres: reemplazar strftime('%Y', fecha_inicio) por EXTRACT(YEAR FROM fecha_inicio)::text,
-- y ((CAST(strftime('%m',fecha_inicio) AS INT)-1)/3)+1 por EXTRACT(QUARTER FROM fecha_inicio).
-- ----------------------------------------------------------------------------
CREATE VIEW vw_retencion_churn_trimestral AS
WITH membresias_trimestre AS (
    SELECT
        id,
        cliente_id,
        estado,
        fecha_inicio,
        fecha_cancelacion,
        strftime('%Y', fecha_inicio) AS anio,
        ((CAST(strftime('%m', fecha_inicio) AS INTEGER) - 1) / 3) + 1 AS trimestre
    FROM membresias
),
activas_inicio AS (
    SELECT anio, trimestre, COUNT(*) AS total_activas
    FROM membresias_trimestre
    GROUP BY anio, trimestre
),
canceladas AS (
    SELECT
        strftime('%Y', fecha_cancelacion) AS anio,
        ((CAST(strftime('%m', fecha_cancelacion) AS INTEGER) - 1) / 3) + 1 AS trimestre,
        COUNT(*) AS total_canceladas
    FROM membresias
    WHERE estado = 'cancelada' AND fecha_cancelacion IS NOT NULL
    GROUP BY anio, trimestre
)
SELECT
    ai.anio,
    ai.trimestre,
    ai.total_activas,
    COALESCE(c.total_canceladas, 0) AS total_canceladas,
    ROUND(COALESCE(c.total_canceladas, 0) * 1.0 / NULLIF(ai.total_activas, 0), 4) AS tasa_churn,
    ROUND(1.0 - (COALESCE(c.total_canceladas, 0) * 1.0 / NULLIF(ai.total_activas, 0)), 4) AS tasa_retencion
FROM activas_inicio ai
LEFT JOIN canceladas c ON c.anio = ai.anio AND c.trimestre = ai.trimestre
ORDER BY ai.anio, ai.trimestre;

-- ----------------------------------------------------------------------------
-- vw_ltv_cliente
-- LTV aproximado por cliente = suma de pagos de cuotas + suma de ventas de productos
-- asociadas a ese cliente, a lo largo de toda su relación con el gimnasio.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_ltv_cliente AS
WITH pagos_cliente AS (
    SELECT cliente_id, SUM(COALESCE(monto, 0)) AS total_pagos
    FROM pagos
    GROUP BY cliente_id
),
ventas_cliente AS (
    SELECT cliente_id, SUM(cantidad * precio_unitario) AS total_ventas
    FROM ventas
    WHERE cliente_id IS NOT NULL
    GROUP BY cliente_id
)
SELECT
    c.id AS cliente_id,
    c.nombre,
    c.apellido,
    COALESCE(p.total_pagos, 0) AS total_pagos_cuotas,
    COALESCE(v.total_ventas, 0) AS total_ventas_productos,
    COALESCE(p.total_pagos, 0) + COALESCE(v.total_ventas, 0) AS ltv_aproximado
FROM clientes c
LEFT JOIN pagos_cliente p ON p.cliente_id = c.id
LEFT JOIN ventas_cliente v ON v.cliente_id = c.id
ORDER BY ltv_aproximado DESC;
