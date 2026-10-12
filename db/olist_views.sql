-- ============================================================================
-- Vistas analíticas para apoyar el motor Text-to-SQL sobre el dataset Olist.
--
-- Escritas para SQLite (usa julianday() para diferencias de fechas en días).
-- Postgres: reemplazar julianday(a) - julianday(b) por
-- EXTRACT(EPOCH FROM (a::timestamp - b::timestamp)) / 86400.
-- ============================================================================

DROP VIEW IF EXISTS vw_ventas_pedido;
DROP VIEW IF EXISTS vw_clientes_recurrentes;
DROP VIEW IF EXISTS vw_entregas_retrasos;
DROP VIEW IF EXISTS vw_ingresos_por_categoria;
DROP VIEW IF EXISTS vw_ingresos_por_vendedor;
DROP VIEW IF EXISTS vw_retraso_por_rango;
DROP VIEW IF EXISTS vw_pedidos_entregados;
DROP VIEW IF EXISTS vw_totales_pedido;
DROP VIEW IF EXISTS vw_articulos_vendidos;
DROP VIEW IF EXISTS vw_pedidos_validos;

-- ----------------------------------------------------------------------------
-- vw_ventas_pedido
-- Grano: una fila por línea de pedido (order_items). Trae el cliente único
-- (customer_unique_id, NO customer_id) y su estado (customer_state), la
-- categoría del producto en inglés (LEFT JOIN a product_category_translation;
-- si no hay traducción, cae al nombre en portugués -- la tabla de traducción
-- no cubre todas las categorías), el vendedor (seller_id, seller_state; LEFT
-- JOIN por seguridad aunque la FK ya lo garantiza), precio y flete de esa
-- línea, estatus/fecha del pedido, y la calificación promedio del pedido
-- (subconsulta que colapsa a UNA fila por pedido, porque un pedido puede
-- tener más de una reseña en order_reviews).
-- ----------------------------------------------------------------------------
CREATE VIEW vw_ventas_pedido AS
WITH review_promedio AS (
    SELECT order_id, ROUND(AVG(review_score), 2) AS review_score_promedio
    FROM order_reviews
    GROUP BY order_id
)
SELECT
    oi.order_id,
    oi.order_item_id,
    c.customer_unique_id,
    c.customer_state,
    oi.seller_id,
    s.seller_state,
    COALESCE(t.product_category_name_english, p.product_category_name) AS categoria_ingles,
    oi.price,
    oi.freight_value,
    o.order_status,
    o.order_purchase_timestamp,
    rp.review_score_promedio
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
JOIN customers c ON c.customer_id = o.customer_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN sellers s ON s.seller_id = oi.seller_id
LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name
LEFT JOIN review_promedio rp ON rp.order_id = oi.order_id
ORDER BY oi.order_id, oi.order_item_id;

-- ----------------------------------------------------------------------------
-- vw_clientes_recurrentes
-- Por customer_unique_id (persona real, no customer_id): número de pedidos
-- distintos, primera/última compra y gasto total (suma de order_payments.
-- payment_value por pedido). Excluye pedidos en estatus 'canceled' o
-- 'unavailable' del conteo y del gasto -- un pedido cancelado/no disponible
-- no representa una compra real, e inflaría artificialmente la recurrencia.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_clientes_recurrentes AS
WITH pedidos_validos AS (
    SELECT o.order_id, c.customer_unique_id, o.order_purchase_timestamp
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
),
pagos_por_pedido AS (
    SELECT order_id, SUM(payment_value) AS total_pagado
    FROM order_payments
    GROUP BY order_id
)
SELECT
    pv.customer_unique_id,
    COUNT(DISTINCT pv.order_id) AS num_pedidos,
    MIN(pv.order_purchase_timestamp) AS primera_compra,
    MAX(pv.order_purchase_timestamp) AS ultima_compra,
    ROUND(SUM(COALESCE(pp.total_pagado, 0)), 2) AS gasto_total,
    CASE WHEN COUNT(DISTINCT pv.order_id) > 1 THEN 1 ELSE 0 END AS es_recurrente
FROM pedidos_validos pv
LEFT JOIN pagos_por_pedido pp ON pp.order_id = pv.order_id
GROUP BY pv.customer_unique_id
ORDER BY num_pedidos DESC, gasto_total DESC;

-- ----------------------------------------------------------------------------
-- vw_entregas_retrasos
-- Por pedido ENTREGADO (order_delivered_customer_date IS NOT NULL): días de
-- retraso (positivo = llegó después de lo estimado, negativo/cero = a tiempo
-- o antes) y la calificación promedio del pedido (misma subconsulta que en
-- vw_ventas_pedido, para no duplicar filas por pedidos con varias reseñas).
-- ----------------------------------------------------------------------------
CREATE VIEW vw_entregas_retrasos AS
WITH review_promedio AS (
    SELECT order_id, ROUND(AVG(review_score), 2) AS review_score_promedio
    FROM order_reviews
    GROUP BY order_id
)
SELECT
    o.order_id,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_estimated_delivery_date,
    o.order_delivered_customer_date,
    ROUND(julianday(o.order_delivered_customer_date) - julianday(o.order_estimated_delivery_date), 1) AS dias_retraso,
    CASE WHEN julianday(o.order_delivered_customer_date) > julianday(o.order_estimated_delivery_date) THEN 1 ELSE 0 END AS entrega_con_retraso,
    rp.review_score_promedio
FROM orders o
LEFT JOIN review_promedio rp ON rp.order_id = o.order_id
WHERE o.order_delivered_customer_date IS NOT NULL;

-- ----------------------------------------------------------------------------
-- vw_ingresos_por_categoria
-- Agregado por categoría (en inglés; COALESCE a 'sin_categoria' cuando el
-- producto no tiene product_category_name). Excluye pedidos 'canceled'/
-- 'unavailable' -- un pedido cancelado no es ingreso real. ratio_flete_ingresos
-- se calcula SUM(freight)/SUM(price) (agregado), NUNCA como promedio de la
-- razón de cada línea (eso pondera mal las líneas baratas).
-- ----------------------------------------------------------------------------
CREATE VIEW vw_ingresos_por_categoria AS
SELECT
    COALESCE(categoria_ingles, 'sin_categoria') AS categoria_ingles,
    COUNT(DISTINCT order_id) AS pedidos,
    ROUND(SUM(price), 2) AS ingresos,
    ROUND(SUM(freight_value), 2) AS flete_total,
    ROUND(SUM(freight_value) * 1.0 / NULLIF(SUM(price), 0), 4) AS ratio_flete_ingresos
FROM vw_ventas_pedido
WHERE order_status NOT IN ('canceled', 'unavailable')
GROUP BY COALESCE(categoria_ingles, 'sin_categoria')
ORDER BY ingresos DESC;

-- ----------------------------------------------------------------------------
-- vw_ingresos_por_vendedor
-- Mismo patrón que vw_ingresos_por_categoria, agrupado por vendedor. Incluye
-- seller_state para preguntas geográficas ("estado" = seller_state, ver notas
-- del esquema).
-- ----------------------------------------------------------------------------
CREATE VIEW vw_ingresos_por_vendedor AS
SELECT
    seller_id,
    seller_state,
    COUNT(DISTINCT order_id) AS pedidos,
    ROUND(SUM(price), 2) AS ingresos,
    ROUND(SUM(freight_value), 2) AS flete_total,
    ROUND(SUM(freight_value) * 1.0 / NULLIF(SUM(price), 0), 4) AS ratio_flete_ingresos
FROM vw_ventas_pedido
WHERE order_status NOT IN ('canceled', 'unavailable')
GROUP BY seller_id, seller_state
ORDER BY ingresos DESC;

-- ----------------------------------------------------------------------------
-- vw_retraso_por_rango
-- Sobre vw_entregas_retrasos (ya son solo pedidos entregados), excluyendo
-- también 'canceled'/'unavailable' por seguridad. Rangos en CASCADA sin
-- huecos sobre dias_retraso: a_tiempo (<=0), 1-3, 4-7, 8-14, 15+ (resto).
-- `orden` (1-5) permite ORDER BY sin repetir el CASE. pct_1_2_estrellas se
-- calcula sobre los pedidos CON reseña (COUNT(review_score_promedio) como
-- denominador), no sobre el total de pedidos del rango.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_retraso_por_rango AS
SELECT
    CASE
        WHEN dias_retraso <= 0 THEN 'a_tiempo'
        WHEN dias_retraso <= 3 THEN '1-3'
        WHEN dias_retraso <= 7 THEN '4-7'
        WHEN dias_retraso <= 14 THEN '8-14'
        ELSE '15+'
    END AS rango_retraso,
    CASE
        WHEN dias_retraso <= 0 THEN 1
        WHEN dias_retraso <= 3 THEN 2
        WHEN dias_retraso <= 7 THEN 3
        WHEN dias_retraso <= 14 THEN 4
        ELSE 5
    END AS orden,
    COUNT(*) AS pedidos,
    ROUND(AVG(review_score_promedio), 2) AS calificacion_promedio,
    ROUND(100.0 * SUM(CASE WHEN review_score_promedio <= 2 THEN 1 ELSE 0 END) / NULLIF(COUNT(review_score_promedio), 0), 2) AS pct_1_2_estrellas
FROM vw_entregas_retrasos
WHERE order_status NOT IN ('canceled', 'unavailable')
GROUP BY rango_retraso, orden
ORDER BY orden;

-- ----------------------------------------------------------------------------
-- vw_pedidos_validos (etapa 2, Paso 3, mejora b)
-- Una fila por pedido VÁLIDO (order_status NOT IN ('canceled','unavailable')),
-- con el cliente único y su estado: partir de aquí evita olvidar el filtro.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_pedidos_validos AS
SELECT
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_state,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status NOT IN ('canceled', 'unavailable');

-- ============================================================================
-- Etapa 3, E4: vistas de NEGOCIO genéricas (bloques reutilizables). Cada una es
-- un concepto de negocio, no la respuesta a una pregunta concreta. Todas parten
-- de vw_pedidos_validos (pedido válido = order_status NOT IN ('canceled','unavailable')).
-- Solo aparecen en el prompt con TEXT2SQL_VISTAS_NEGOCIO=1 (llm/schema_context.py).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- vw_pedidos_entregados -- concepto "pedido entregado"
-- Una fila por pedido VÁLIDO con fecha de entrega al cliente registrada.
-- dias_entrega = compra -> entrega; dias_retraso = entrega - fecha estimada
-- (positivo = llegó tarde); con_retraso = 1 si llegó después de la estimada.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_pedidos_entregados AS
SELECT
    v.order_id,
    v.customer_unique_id,
    v.customer_state,
    v.order_purchase_timestamp,
    v.order_delivered_customer_date,
    v.order_estimated_delivery_date,
    julianday(v.order_delivered_customer_date) - julianday(v.order_purchase_timestamp) AS dias_entrega,
    julianday(v.order_delivered_customer_date) - julianday(v.order_estimated_delivery_date) AS dias_retraso,
    CASE WHEN julianday(v.order_delivered_customer_date) > julianday(v.order_estimated_delivery_date)
         THEN 1 ELSE 0 END AS con_retraso
FROM vw_pedidos_validos v
WHERE v.order_delivered_customer_date IS NOT NULL;

-- ----------------------------------------------------------------------------
-- vw_totales_pedido -- concepto "pedido con sus totales"
-- Una fila por pedido VÁLIDO. Cada total se agrega por separado antes de unir,
-- así que no hay multiplicación de filas entre artículos, pagos y reseñas.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_totales_pedido AS
SELECT
    v.order_id,
    v.customer_unique_id,
    v.customer_state,
    v.order_purchase_timestamp,
    a.articulos,
    a.valor_productos,
    a.flete_total,
    p.total_pagado,
    r.calificacion
FROM vw_pedidos_validos v
LEFT JOIN (SELECT order_id, COUNT(*) AS articulos, SUM(price) AS valor_productos, SUM(freight_value) AS flete_total
           FROM order_items GROUP BY order_id) a ON a.order_id = v.order_id
LEFT JOIN (SELECT order_id, SUM(payment_value) AS total_pagado FROM order_payments GROUP BY order_id) p ON p.order_id = v.order_id
LEFT JOIN (SELECT order_id, AVG(review_score) AS calificacion FROM order_reviews GROUP BY order_id) r ON r.order_id = v.order_id;

-- ----------------------------------------------------------------------------
-- vw_articulos_vendidos -- concepto "artículo vendido"
-- Una fila por artículo (unidad) de un pedido VÁLIDO, con su categoría (inglés;
-- 'sin_categoria' si no tiene), su vendedor y su cliente ya unidos.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_articulos_vendidos AS
SELECT
    oi.order_id,
    oi.order_item_id,
    oi.product_id,
    COALESCE(t.product_category_name_english, 'sin_categoria') AS categoria,
    oi.seller_id,
    s.seller_city,
    s.seller_state,
    v.customer_unique_id,
    v.customer_state,
    v.order_purchase_timestamp,
    oi.price,
    oi.freight_value
FROM order_items oi
JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name
JOIN sellers s ON s.seller_id = oi.seller_id;
