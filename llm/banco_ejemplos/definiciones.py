"""
Necesidades NEGATIVAS (D-41): preguntas parecidas a las necesidades reales 2, 4, 5, 6 y 8 del
dashboard, pero distintas (otra métrica, otra dimensión, otro periodo, otro filtro u otra
agregación). Las escribió el modelo grande; `llm/banco_ejemplos/construir.py` EJECUTA cada SQL
contra db/olist.db (solo lectura), valida el resultado y genera `respuesta_nl` desde las filas.

`respuesta` es una plantilla: se rellena con las filas reales (`f` = lista de filas) mediante
`str.format`, así que ninguna cifra se escribe a mano.
"""
from __future__ import annotations

# Calificación de un pedido = promedio de sus reseñas (un pedido puede tener varias).
CALIF = "(SELECT order_id, AVG(review_score) AS calif FROM order_reviews GROUP BY order_id)"
TARDE = "julianday(v.order_delivered_customer_date) > julianday(v.order_estimated_delivery_date)"

NECESIDADES = [
    # ------------------------------------------------------------------ familia 2: retraso vs reseñas
    {
        "id": "neg_f2_01_pct_5_estrellas_tarde_vs_tiempo",
        "familia": "2 · Retraso vs reseñas",
        "pregunta": "De los pedidos válidos entregados con reseña, ¿qué porcentaje tiene calificación de 5 estrellas entre los que llegaron tarde y entre los que llegaron a tiempo?",
        "variantes": ["¿Cuántos pedidos (en %) reciben 5 estrellas cuando llegan tarde frente a cuando llegan a tiempo?"],
        "en_que_se_diferencia": "Mide la proporción de calificaciones perfectas (= 5), no la calificación promedio ni las bajas.",
        "sql": f"""SELECT
  ROUND(100.0 * SUM(CASE WHEN {TARDE} AND r.calif = 5 THEN 1 ELSE 0 END) / SUM(CASE WHEN {TARDE} THEN 1 ELSE 0 END), 2) AS pct_5_tarde,
  ROUND(100.0 * SUM(CASE WHEN NOT ({TARDE}) AND r.calif = 5 THEN 1 ELSE 0 END) / SUM(CASE WHEN NOT ({TARDE}) THEN 1 ELSE 0 END), 2) AS pct_5_a_tiempo
FROM vw_pedidos_validos v
JOIN {CALIF} r ON r.order_id = v.order_id
WHERE v.order_delivered_customer_date IS NOT NULL""",
        "respuesta": "Entre los pedidos que llegaron tarde, el {f[0][0]:.2f} % tiene 5 estrellas; entre los que llegaron a tiempo, el {f[0][1]:.2f} %.",
        "trampas": ["La calificación del pedido es el promedio de sus reseñas (agrupar order_reviews por order_id).",
                    "El denominador de cada porcentaje es su propio grupo (tarde o a tiempo), no el total.",
                    "Excluir pedidos sin fecha de entrega (NULL)."],
    },
    {
        "id": "neg_f2_02_estados_peor_calif_retraso_10",
        "familia": "2 · Retraso vs reseñas",
        "pregunta": "¿Qué 3 estados de clientes ponen las peores notas a los pedidos que llegan más de 10 días después de lo prometido? (solo estados con 50 o más pedidos válidos así)",
        "variantes": ["¿Qué 3 estados califican peor los pedidos que llegan más de 10 días tarde?"],
        "en_que_se_diferencia": "Cambia la dimensión (estado del cliente) y filtra solo retrasos de más de 10 días.",
        "sql": f"""SELECT v.customer_state, COUNT(*) AS pedidos, ROUND(AVG(r.calif), 2) AS calificacion
FROM vw_pedidos_validos v
JOIN {CALIF} r ON r.order_id = v.order_id
WHERE v.order_delivered_customer_date IS NOT NULL
  AND julianday(v.order_delivered_customer_date) - julianday(v.order_estimated_delivery_date) > 10
GROUP BY v.customer_state
HAVING COUNT(*) >= 50
ORDER BY calificacion ASC
LIMIT 3""",
        "respuesta": "Los estados con peor calificación en pedidos con más de 10 días de retraso son {f[0][0]} ({f[0][2]:.2f}), {f[1][0]} ({f[1][2]:.2f}) y {f[2][0]} ({f[2][2]:.2f}).",
        "trampas": ["El umbral de 50 pedidos va en HAVING, después de agrupar.",
                    "Retraso en días con decimales: julianday(real) - julianday(estimada)."],
    },
    {
        "id": "neg_f2_03_dias_retraso_por_calificacion",
        "familia": "2 · Retraso vs reseñas",
        "pregunta": "En los pedidos válidos entregados con reseña, ¿cuántos días de diferencia promedio entre la entrega real y la estimada tienen los pedidos calificados con 1 estrella y los calificados con 5?",
        "variantes": ["¿Los pedidos de 1 estrella llegan más tarde respecto a lo prometido que los de 5 estrellas? Dame el promedio de días de cada grupo."],
        "en_que_se_diferencia": "Invierte la dirección: agrupa por calificación y mide los días de retraso promedio.",
        "sql": f"""SELECT CAST(r.calif AS INTEGER) AS estrellas,
       COUNT(*) AS pedidos,
       ROUND(AVG(julianday(v.order_delivered_customer_date) - julianday(v.order_estimated_delivery_date)), 2) AS dias_vs_estimada
FROM vw_pedidos_validos v
JOIN {CALIF} r ON r.order_id = v.order_id
WHERE v.order_delivered_customer_date IS NOT NULL AND r.calif IN (1, 5)
GROUP BY r.calif
ORDER BY estrellas""",
        "respuesta": "Los pedidos de {f[0][0]} estrella llegan en promedio {f[0][2]:.2f} días respecto de la fecha estimada y los de {f[1][0]} estrellas, {f[1][2]:.2f} días (negativo = antes de lo estimado).",
        "trampas": ["Un valor negativo significa que llegó ANTES de lo estimado.",
                    "Solo pedidos cuyo promedio de reseñas es exactamente 1 o 5."],
    },
    {
        "id": "neg_f2_04_calif_retraso_por_anio",
        "familia": "2 · Retraso vs reseñas",
        "pregunta": "Para los años de compra 2017 y 2018, ¿cuál fue la calificación promedio de los pedidos válidos que se entregaron después de la fecha estimada?",
        "variantes": ["¿Mejoró de 2017 a 2018 la calificación de los pedidos que llegaron tarde?"],
        "en_que_se_diferencia": "Agrega por periodo (año de compra) y solo mira pedidos con retraso.",
        "sql": f"""SELECT strftime('%Y', v.order_purchase_timestamp) AS anio, COUNT(*) AS pedidos, ROUND(AVG(r.calif), 2) AS calificacion
FROM vw_pedidos_validos v
JOIN {CALIF} r ON r.order_id = v.order_id
WHERE v.order_delivered_customer_date IS NOT NULL AND {TARDE}
  AND strftime('%Y', v.order_purchase_timestamp) IN ('2017', '2018')
GROUP BY anio
ORDER BY anio""",
        "respuesta": "Los pedidos con retraso se calificaron en promedio con {f[0][2]:.2f} en {f[0][0]} ({f[0][1]:,} pedidos) y con {f[1][2]:.2f} en {f[1][0]} ({f[1][1]:,} pedidos).",
        "trampas": ["El año sale de order_purchase_timestamp con strftime('%Y', ...).",
                    "La comparación de fechas es con julianday, no como texto."],
    },
    {
        "id": "neg_f2_05_semanas_de_retraso",
        "familia": "2 · Retraso vs reseñas",
        "pregunta": "Solo para los pedidos válidos que llegaron tarde, agrupándolos por semanas de retraso (hasta 7 días, de 8 a 14, de 15 a 21 y más de 21), ¿cuántos pedidos hay y cuál es la calificación promedio en cada grupo?",
        "variantes": ["¿Cómo cae la calificación semana a semana de retraso?"],
        "en_que_se_diferencia": "Usa otros rangos (semanas) y excluye los pedidos a tiempo.",
        "sql": f"""WITH d AS (
  SELECT r.calif, julianday(v.order_delivered_customer_date) - julianday(v.order_estimated_delivery_date) AS dias
  FROM vw_pedidos_validos v JOIN {CALIF} r ON r.order_id = v.order_id
  WHERE v.order_delivered_customer_date IS NOT NULL AND {TARDE}
)
SELECT CASE WHEN dias <= 7 THEN '1) hasta 7' WHEN dias <= 14 THEN '2) 8-14' WHEN dias <= 21 THEN '3) 15-21' ELSE '4) mas de 21' END AS semanas,
       COUNT(*) AS pedidos, ROUND(AVG(calif), 2) AS calificacion
FROM d GROUP BY semanas ORDER BY semanas""",
        "respuesta": "Con hasta 7 días de retraso la calificación promedio es {f[0][2]:.2f} ({f[0][1]:,} pedidos); de 8 a 14, {f[1][2]:.2f}; de 15 a 21, {f[2][2]:.2f}; y con más de 21 días, {f[3][2]:.2f} ({f[3][1]:,} pedidos).",
        "trampas": ["Los rangos deben ser excluyentes y en cascada (CASE en orden).",
                    "Etiquetas con prefijo numérico para que ORDER BY respete el orden."],
    },
    {
        "id": "neg_f2_06_comentario_tarde_vs_tiempo",
        "familia": "2 · Retraso vs reseñas",
        "pregunta": "¿Qué porcentaje de los pedidos válidos entregados que llegaron tarde tiene al menos una reseña con comentario escrito, y qué porcentaje entre los que llegaron a tiempo?",
        "variantes": ["¿Los clientes escriben más comentarios cuando el pedido llega tarde?"],
        "en_que_se_diferencia": "La métrica es la presencia de comentario (review_comment_message no nulo), no la calificación.",
        "sql": f"""WITH p AS (
  SELECT v.order_id, CASE WHEN {TARDE} THEN 1 ELSE 0 END AS tarde,
         MAX(CASE WHEN rv.review_comment_message IS NOT NULL THEN 1 ELSE 0 END) AS con_comentario
  FROM vw_pedidos_validos v JOIN order_reviews rv ON rv.order_id = v.order_id
  WHERE v.order_delivered_customer_date IS NOT NULL
  GROUP BY v.order_id
)
SELECT ROUND(100.0 * SUM(CASE WHEN tarde = 1 THEN con_comentario ELSE 0 END) / SUM(tarde), 2) AS pct_comentario_tarde,
       ROUND(100.0 * SUM(CASE WHEN tarde = 0 THEN con_comentario ELSE 0 END) / SUM(1 - tarde), 2) AS pct_comentario_a_tiempo
FROM p""",
        "respuesta": "El {f[0][0]:.2f} % de los pedidos que llegaron tarde tiene un comentario escrito, frente al {f[0][1]:.2f} % de los que llegaron a tiempo.",
        "trampas": ["Agregar primero por pedido (MAX) para no contar dos veces pedidos con varias reseñas.",
                    "Comentario = review_comment_message IS NOT NULL."],
    },
    {
        "id": "neg_f2_07_mes_2018_mas_tardios",
        "familia": "2 · Retraso vs reseñas",
        "pregunta": "En 2018, ¿en qué mes de compra (AAAA-MM) fue mayor el porcentaje de pedidos válidos entregados después de la fecha estimada, y cuál fue la calificación promedio de los pedidos de ese mes?",
        "variantes": ["¿Cuál fue el peor mes de 2018 en puntualidad y cómo lo calificaron?"],
        "en_que_se_diferencia": "Agrega por mes y combina porcentaje de retraso con calificación del mes.",
        "sql": f"""SELECT strftime('%Y-%m', v.order_purchase_timestamp) AS mes,
       ROUND(100.0 * SUM(CASE WHEN {TARDE} THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_tarde,
       ROUND(AVG(r.calif), 2) AS calificacion
FROM vw_pedidos_validos v
LEFT JOIN {CALIF} r ON r.order_id = v.order_id
WHERE v.order_delivered_customer_date IS NOT NULL AND strftime('%Y', v.order_purchase_timestamp) = '2018'
GROUP BY mes
ORDER BY pct_tarde DESC
LIMIT 1""",
        "respuesta": "El mes de 2018 con más retrasos fue {f[0][0]}: el {f[0][1]:.2f} % de sus pedidos llegó tarde y su calificación promedio fue {f[0][2]:.2f}.",
        "trampas": ["LEFT JOIN a las reseñas para no perder pedidos sin reseña en el denominador del porcentaje.",
                    "Solo pedidos entregados (fecha no NULL)."],
    },
    # ------------------------------------------------------------------ familia 4: vendedores problemáticos
    {
        "id": "neg_f4_01_top5_vendedores_pct_tarde",
        "familia": "4 · Vendedores problemáticos",
        "pregunta": "Entre los vendedores con 50 o más pedidos válidos ya recibidos por el cliente, ¿qué 5 vendedores incumplen más seguido el plazo prometido y en qué proporción?",
        "variantes": ["¿Qué 5 vendedores entregan tarde más seguido (con al menos 50 pedidos entregados)?"],
        "en_que_se_diferencia": "Ordena vendedores solo por porcentaje de entregas tardías; no usa ingresos ni calificación.",
        "sql": f"""WITH pv AS (
  SELECT DISTINCT oi.seller_id, v.order_id, CASE WHEN {TARDE} THEN 1 ELSE 0 END AS tarde
  FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
  WHERE v.order_delivered_customer_date IS NOT NULL
)
SELECT seller_id, COUNT(*) AS pedidos, ROUND(100.0 * SUM(tarde) / COUNT(*), 2) AS pct_tarde
FROM pv GROUP BY seller_id HAVING COUNT(*) >= 50
ORDER BY pct_tarde DESC LIMIT 5""",
        "respuesta": "El vendedor con más entregas tardías es {f[0][0]} ({f[0][2]:.2f} % de {f[0][1]:,} pedidos); le siguen {f[1][0]} ({f[1][2]:.2f} %) y {f[2][0]} ({f[2][2]:.2f} %).",
        "trampas": ["DISTINCT vendedor-pedido: un pedido con varios artículos del mismo vendedor cuenta una vez.",
                    "Denominador: pedidos entregados del vendedor."],
    },
    {
        "id": "neg_f4_02_vendedor_peor_calificado_100",
        "familia": "4 · Vendedores problemáticos",
        "pregunta": "De los vendedores que tienen 100 o más pedidos válidos, ¿quién recibe las peores notas de sus clientes (nota media por pedido) y cuánto ha facturado?",
        "variantes": ["¿Cuál es el vendedor grande peor calificado y cuánto vende?"],
        "en_que_se_diferencia": "Busca un solo vendedor (el peor calificado) y reporta sus ingresos; umbral de 100 pedidos.",
        "sql": f"""WITH pv AS (
  SELECT DISTINCT oi.seller_id, v.order_id FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
),
cal AS (
  SELECT pv.seller_id, COUNT(*) AS pedidos, AVG(r.calif) AS calif
  FROM pv LEFT JOIN {CALIF} r ON r.order_id = pv.order_id GROUP BY pv.seller_id HAVING COUNT(*) >= 100
),
ing AS (
  SELECT oi.seller_id, SUM(oi.price) AS ingresos FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id GROUP BY oi.seller_id
)
SELECT cal.seller_id, cal.pedidos, ROUND(cal.calif, 2) AS calificacion, ROUND(ing.ingresos, 2) AS ingresos
FROM cal JOIN ing ON ing.seller_id = cal.seller_id
ORDER BY cal.calif ASC LIMIT 1""",
        "respuesta": "El vendedor peor calificado con al menos 100 pedidos es {f[0][0]}: calificación {f[0][2]:.2f} en {f[0][1]:,} pedidos y R$ {f[0][3]:,.2f} de ingresos.",
        "trampas": ["Calcular ingresos en una subconsulta aparte: unirlos con reseñas multiplica filas.",
                    "La calificación del vendedor promedia la de cada pedido, no las reseñas crudas."],
    },
    {
        "id": "neg_f4_03_vendedores_sp_calif_menor_4",
        "familia": "4 · Vendedores problemáticos",
        "pregunta": "¿Cuántos vendedores con sede en SP y 30 o más pedidos válidos tienen una nota media por pedido inferior a 4?",
        "variantes": ["¿Cuántos vendedores paulistas medianos o grandes están por debajo de 4 estrellas?"],
        "en_que_se_diferencia": "Filtra por estado del vendedor y usa otro umbral de calificación; no mira ingresos ni retrasos.",
        "sql": f"""WITH pv AS (
  SELECT DISTINCT oi.seller_id, v.order_id
  FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
  JOIN sellers s ON s.seller_id = oi.seller_id WHERE s.seller_state = 'SP'
),
cal AS (
  SELECT pv.seller_id, COUNT(*) AS pedidos, AVG(r.calif) AS calif
  FROM pv LEFT JOIN {CALIF} r ON r.order_id = pv.order_id GROUP BY pv.seller_id HAVING COUNT(*) >= 30
)
SELECT COUNT(*) AS vendedores, (SELECT COUNT(*) FROM cal) AS vendedores_con_30_pedidos FROM cal WHERE calif < 4""",
        "respuesta": "{f[0][0]:,} de los {f[0][1]:,} vendedores de SP con al menos 30 pedidos tienen calificación promedio menor a 4.",
        "trampas": ["El estado del vendedor está en sellers.seller_state (no en el cliente).",
                    "COUNT sobre vendedores ya agregados, no sobre pedidos."],
    },
    {
        "id": "neg_f4_04_top3_vendedores_cancelados",
        "familia": "4 · Vendedores problemáticos",
        "pregunta": "Entre los vendedores con al menos 20 pedidos (de cualquier estatus), ¿cuáles son los 3 con mayor porcentaje de pedidos cancelados y cuál es ese porcentaje?",
        "variantes": ["¿Qué vendedores cancelan más pedidos en proporción?"],
        "en_que_se_diferencia": "La métrica es la tasa de cancelación, que exige contar TODOS los estatus.",
        "sql": """WITH pv AS (
  SELECT DISTINCT oi.seller_id, o.order_id, o.order_status FROM order_items oi JOIN orders o ON o.order_id = oi.order_id
)
SELECT seller_id, COUNT(*) AS pedidos, ROUND(100.0 * SUM(CASE WHEN order_status = 'canceled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_cancelados
FROM pv GROUP BY seller_id HAVING COUNT(*) >= 20
ORDER BY pct_cancelados DESC, pedidos DESC LIMIT 3""",
        "respuesta": "El vendedor con mayor tasa de cancelación es {f[0][0]} ({f[0][2]:.2f} % de {f[0][1]:,} pedidos), seguido de {f[1][0]} ({f[1][2]:.2f} %) y {f[2][0]} ({f[2][2]:.2f} %).",
        "trampas": ["Aquí NO se filtran pedidos válidos: los cancelados son justamente lo que se mide.",
                    "Pedidos distintos por vendedor (DISTINCT)."],
    },
    {
        "id": "neg_f4_05_calif_top10pct_vs_resto",
        "familia": "4 · Vendedores problemáticos",
        "pregunta": "¿Cuál es la calificación promedio de los pedidos válidos de los vendedores que están en el 10 % con más ingresos, comparada con la del resto de vendedores?",
        "variantes": ["¿Los vendedores que más facturan tienen clientes más satisfechos que el resto?"],
        "en_que_se_diferencia": "Compara dos grupos de vendedores (top 10 % por ingresos frente al resto) en lugar de contar problemáticos.",
        "sql": f"""WITH ing AS (
  SELECT oi.seller_id, SUM(oi.price) AS ingresos FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id GROUP BY oi.seller_id
),
grupo AS (
  SELECT seller_id, CASE WHEN PERCENT_RANK() OVER (ORDER BY ingresos DESC) <= 0.10 THEN 'top_10' ELSE 'resto' END AS grupo FROM ing
),
pv AS (
  SELECT DISTINCT oi.seller_id, v.order_id FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
)
SELECT g.grupo, COUNT(*) AS pedidos_vendedor, ROUND(AVG(r.calif), 2) AS calificacion
FROM pv JOIN grupo g ON g.seller_id = pv.seller_id JOIN {CALIF} r ON r.order_id = pv.order_id
GROUP BY g.grupo ORDER BY g.grupo DESC""",
        "respuesta": "Los pedidos de los vendedores del 10 % con más ingresos tienen calificación promedio {f[0][2]:.2f}; los del resto, {f[1][2]:.2f}.",
        "trampas": ["El percentil se calcula sobre los ingresos ya agregados por vendedor (ventana sobre la CTE).",
                    "Pedidos distintos por vendedor antes de unir con reseñas."],
    },
    {
        "id": "neg_f4_06_estado_vendedor_mas_tardias",
        "familia": "4 · Vendedores problemáticos",
        "pregunta": "Agrupando por el estado donde está el vendedor (solo estados con 20 o más vendedores que hayan vendido), ¿cuál incumple más el plazo de entrega prometido, en porcentaje?",
        "variantes": ["¿Desde qué estado se despacha con peor puntualidad?"],
        "en_que_se_diferencia": "Agrega por estado del vendedor (no por vendedor) y filtra estados por cantidad de vendedores.",
        "sql": f"""WITH pv AS (
  SELECT DISTINCT s.seller_state, oi.seller_id, v.order_id, CASE WHEN {TARDE} THEN 1 ELSE 0 END AS tarde
  FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id JOIN sellers s ON s.seller_id = oi.seller_id
  WHERE v.order_delivered_customer_date IS NOT NULL
)
SELECT seller_state, COUNT(DISTINCT seller_id) AS vendedores, ROUND(100.0 * SUM(tarde) / COUNT(*), 2) AS pct_tarde
FROM pv GROUP BY seller_state HAVING COUNT(DISTINCT seller_id) >= 20
ORDER BY pct_tarde DESC LIMIT 1""",
        "respuesta": "El estado de vendedor con más entregas tardías es {f[0][0]}: {f[0][2]:.2f} % de entregas tarde, con {f[0][1]:,} vendedores.",
        "trampas": ["El umbral es de vendedores distintos (COUNT DISTINCT seller_id) en HAVING.",
                    "Cada par vendedor-pedido cuenta una vez."],
    },
    {
        "id": "neg_f4_07_pct_ingresos_vendedores_calif_baja",
        "familia": "4 · Vendedores problemáticos",
        "pregunta": "¿Qué porcentaje de los ingresos de pedidos válidos generan los vendedores con al menos 10 pedidos y calificación promedio menor a 3?",
        "variantes": ["¿Cuánto del negocio (en % de ingresos) depende de vendedores mal calificados?"],
        "en_que_se_diferencia": "Mide la participación en ingresos de un grupo de vendedores, no cuántos son.",
        "sql": f"""WITH pv AS (
  SELECT DISTINCT oi.seller_id, v.order_id FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
),
cal AS (
  SELECT pv.seller_id FROM pv LEFT JOIN {CALIF} r ON r.order_id = pv.order_id
  GROUP BY pv.seller_id HAVING COUNT(*) >= 10 AND AVG(r.calif) < 3
),
ing AS (
  SELECT oi.seller_id, SUM(oi.price) AS ingresos FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id GROUP BY oi.seller_id
)
SELECT ROUND(100.0 * SUM(CASE WHEN seller_id IN (SELECT seller_id FROM cal) THEN ingresos ELSE 0 END) / SUM(ingresos), 2) AS pct_ingresos,
       (SELECT COUNT(*) FROM cal) AS vendedores
FROM ing""",
        "respuesta": "Los {f[0][1]:,} vendedores con calificación menor a 3 (y al menos 10 pedidos) generan el {f[0][0]:.2f} % de los ingresos.",
        "trampas": ["Ingresos = SUM(price) de pedidos válidos, calculados aparte de las reseñas.",
                    "El denominador son los ingresos de todos los vendedores."],
    },
    # ------------------------------------------------------------------ familia 5: flete
    {
        "id": "neg_f5_01_estado_vendedor_peso_flete",
        "familia": "5 · Flete",
        "pregunta": "¿En qué 3 estados del VENDEDOR pesa más el flete sobre el precio (flete total entre precio total, en pedidos válidos), considerando estados con al menos 1,000 artículos vendidos?",
        "variantes": ["¿Desde qué estados sale más caro el envío en proporción al precio?"],
        "en_que_se_diferencia": "La dimensión es el estado del vendedor (origen del envío), no el del cliente ni la categoría.",
        "sql": """SELECT s.seller_state, COUNT(*) AS articulos, ROUND(100.0 * SUM(oi.freight_value) / SUM(oi.price), 2) AS pct_flete
FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id JOIN sellers s ON s.seller_id = oi.seller_id
GROUP BY s.seller_state HAVING COUNT(*) >= 1000
ORDER BY pct_flete DESC LIMIT 3""",
        "respuesta": "Los estados de vendedor donde más pesa el flete son {f[0][0]} ({f[0][2]:.2f} %), {f[1][0]} ({f[1][2]:.2f} %) y {f[2][0]} ({f[2][2]:.2f} %).",
        "trampas": ["SUM(flete) / SUM(precio), no el promedio de la razón por artículo.",
                    "El estado del vendedor está en sellers, unido por order_items.seller_id."],
    },
    {
        "id": "neg_f5_02_categorias_flete_mas_liviano",
        "familia": "5 · Flete",
        "pregunta": "¿En qué 3 categorías (nombre en inglés) el envío resulta más barato comparado con lo que cuestan los productos? Solo categorías que facturaron R$ 10,000 o más en pedidos válidos.",
        "variantes": ["¿En qué categorías el envío es más barato en proporción al precio?"],
        "en_que_se_diferencia": "Busca el mínimo (no el máximo) y usa otro umbral de ingresos.",
        "sql": """SELECT COALESCE(t.product_category_name_english, 'sin_categoria') AS categoria,
       ROUND(SUM(oi.price), 2) AS ingresos, ROUND(100.0 * SUM(oi.freight_value) / SUM(oi.price), 2) AS pct_flete
FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name
GROUP BY categoria HAVING SUM(oi.price) >= 10000
ORDER BY pct_flete ASC LIMIT 3""",
        "respuesta": "Las categorías donde menos pesa el flete son {f[0][0]} ({f[0][2]:.2f} %), {f[1][0]} ({f[1][2]:.2f} %) y {f[2][0]} ({f[2][2]:.2f} %).",
        "trampas": ["LEFT JOIN a la traducción; sin categoría = 'sin_categoria'.",
                    "Umbral de ingresos en HAVING sobre SUM(price)."],
    },
    {
        "id": "neg_f5_03_peso_flete_por_anio",
        "familia": "5 · Flete",
        "pregunta": "¿Cómo cambió el peso del flete sobre el precio (flete total entre precio total) de los pedidos válidos entre 2017 y 2018, según el año de compra?",
        "variantes": ["¿El flete pesó más o menos en 2018 que en 2017?"],
        "en_que_se_diferencia": "Agrega por periodo (año de compra) en lugar de por estado o categoría.",
        "sql": """SELECT strftime('%Y', v.order_purchase_timestamp) AS anio, ROUND(100.0 * SUM(oi.freight_value) / SUM(oi.price), 2) AS pct_flete
FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
WHERE strftime('%Y', v.order_purchase_timestamp) IN ('2017', '2018')
GROUP BY anio ORDER BY anio""",
        "respuesta": "El flete representó el {f[0][1]:.2f} % del precio en {f[0][0]} y el {f[1][1]:.2f} % en {f[1][0]}.",
        "trampas": ["Razón de sumas por año, no promedio de razones."],
    },
    {
        "id": "neg_f5_04_flete_mismo_estado_vs_otro",
        "familia": "5 · Flete",
        "pregunta": "¿Sale proporcionalmente más caro el envío cuando el vendedor despacha a otro estado que cuando vende dentro de su propio estado? Compara flete total entre precio total en ambos casos (pedidos válidos).",
        "variantes": ["¿Cuánto encarece el envío vender a otro estado?"],
        "en_que_se_diferencia": "Filtra por la relación entre el estado del vendedor y el del cliente.",
        "sql": """SELECT CASE WHEN s.seller_state = v.customer_state THEN 'mismo_estado' ELSE 'otro_estado' END AS tipo,
       COUNT(*) AS articulos, ROUND(100.0 * SUM(oi.freight_value) / SUM(oi.price), 2) AS pct_flete
FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id JOIN sellers s ON s.seller_id = oi.seller_id
GROUP BY tipo ORDER BY tipo""",
        "respuesta": "Cuando vendedor y cliente están en el mismo estado, el flete pesa el {f[0][2]:.2f} % del precio; en estados distintos, el {f[1][2]:.2f} %.",
        "trampas": ["El estado del cliente viene de vw_pedidos_validos.customer_state y el del vendedor de sellers."],
    },
    {
        "id": "neg_f5_05_flete_por_pedido_top3_estados",
        "familia": "5 · Flete",
        "pregunta": "Para los 3 estados con más pedidos válidos, ¿cuánto se paga de envío por pedido en promedio, sumando el flete de todos los artículos de cada pedido?",
        "variantes": ["¿Cuánto paga de envío, en promedio por pedido, un cliente de los estados más grandes?"],
        "en_que_se_diferencia": "El promedio es por pedido (agregando primero los artículos), no por artículo ni como proporción.",
        "sql": """WITH fp AS (
  SELECT v.order_id, v.customer_state, SUM(oi.freight_value) AS flete
  FROM vw_pedidos_validos v JOIN order_items oi ON oi.order_id = v.order_id GROUP BY v.order_id, v.customer_state
),
top AS (SELECT customer_state FROM vw_pedidos_validos GROUP BY customer_state ORDER BY COUNT(*) DESC LIMIT 3)
SELECT customer_state, COUNT(*) AS pedidos, ROUND(AVG(flete), 2) AS flete_promedio_pedido
FROM fp WHERE customer_state IN (SELECT customer_state FROM top)
GROUP BY customer_state ORDER BY pedidos DESC""",
        "respuesta": "El flete promedio por pedido es R$ {f[0][2]:.2f} en {f[0][0]}, R$ {f[1][2]:.2f} en {f[1][0]} y R$ {f[2][2]:.2f} en {f[2][0]}.",
        "trampas": ["Sumar el flete por pedido ANTES de promediar.",
                    "Elegir los 3 estados por número de pedidos en una subconsulta aparte."],
    },
    {
        "id": "neg_f5_06_furniture_decor_estado_flete",
        "familia": "5 · Flete",
        "pregunta": "Dentro de furniture_decor, ¿a qué estado (de quien compra) le cuesta más el envío en proporción al valor de los artículos, entre estados con 100 o más artículos vendidos en pedidos válidos?",
        "variantes": ["¿Dónde sale más caro, en proporción, enviar artículos de decoración?"],
        "en_que_se_diferencia": "Fija una categoría y busca el estado del cliente.",
        "sql": """SELECT v.customer_state, COUNT(*) AS articulos, ROUND(100.0 * SUM(oi.freight_value) / SUM(oi.price), 2) AS pct_flete
FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
JOIN products p ON p.product_id = oi.product_id
JOIN product_category_translation t ON t.product_category_name = p.product_category_name
WHERE t.product_category_name_english = 'furniture_decor'
GROUP BY v.customer_state HAVING COUNT(*) >= 100
ORDER BY pct_flete DESC LIMIT 1""",
        "respuesta": "En furniture_decor, el flete pesa más en {f[0][0]}: {f[0][2]:.2f} % del precio ({f[0][1]:,} artículos).",
        "trampas": ["La categoría en inglés está en product_category_translation; se llega por products."],
    },
    {
        "id": "neg_f5_07_flete_un_articulo_vs_varios",
        "familia": "5 · Flete",
        "pregunta": "¿Cuánto pesa el flete sobre el precio en los pedidos válidos de un solo artículo, y cuánto en los pedidos de varios artículos?",
        "variantes": ["¿Comprar varios artículos juntos abarata el envío en proporción?"],
        "en_que_se_diferencia": "Agrupa por tamaño del pedido, lo que exige contar artículos por pedido primero.",
        "sql": """WITH tp AS (
  SELECT oi.order_id, COUNT(*) AS articulos, SUM(oi.price) AS precio, SUM(oi.freight_value) AS flete
  FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id GROUP BY oi.order_id
)
SELECT CASE WHEN articulos = 1 THEN 'un_articulo' ELSE 'varios_articulos' END AS tipo,
       COUNT(*) AS pedidos, ROUND(100.0 * SUM(flete) / SUM(precio), 2) AS pct_flete
FROM tp GROUP BY tipo ORDER BY tipo""",
        "respuesta": "En pedidos de un solo artículo el flete pesa el {f[0][2]:.2f} % del precio; en pedidos de varios artículos, el {f[1][2]:.2f} %.",
        "trampas": ["Agregar por pedido antes de clasificar por número de artículos."],
    },
    # ------------------------------------------------------------------ familia 6: pagos
    {
        "id": "neg_f6_01_pct_credito_mas_10_cuotas",
        "familia": "6 · Pagos",
        "pregunta": "De los pedidos válidos pagados con tarjeta de crédito, ¿qué porcentaje usó más de 10 cuotas en ese pago?",
        "variantes": ["¿Qué tan común es financiar en más de 10 cuotas con tarjeta?"],
        "en_que_se_diferencia": "Fija un método de pago y otro umbral de cuotas; no agrupa por categoría.",
        "sql": """WITH pc AS (
  SELECT op.order_id, MAX(op.payment_installments) AS cuotas
  FROM order_payments op JOIN vw_pedidos_validos v ON v.order_id = op.order_id
  WHERE op.payment_type = 'credit_card' GROUP BY op.order_id
)
SELECT ROUND(100.0 * SUM(CASE WHEN cuotas > 10 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_mas_10_cuotas, COUNT(*) AS pedidos
FROM pc""",
        "respuesta": "El {f[0][0]:.2f} % de los {f[0][1]:,} pedidos pagados con tarjeta de crédito usó más de 10 cuotas.",
        "trampas": ["Agregar por pedido (MAX de cuotas) para no contar dos veces pedidos con varios pagos con tarjeta."],
    },
    {
        "id": "neg_f6_02_cuotas_promedio_credito_estado",
        "familia": "6 · Pagos",
        "pregunta": "Entre los estados del cliente con al menos 1,000 pagos con tarjeta de crédito en pedidos válidos, ¿cuáles son los 3 con más cuotas promedio por pago?",
        "variantes": ["¿En qué estados se financian más las compras con tarjeta?"],
        "en_que_se_diferencia": "Promedio de cuotas por pago, agrupado por estado del cliente.",
        "sql": """SELECT v.customer_state, COUNT(*) AS pagos, ROUND(AVG(op.payment_installments), 2) AS cuotas_promedio
FROM order_payments op JOIN vw_pedidos_validos v ON v.order_id = op.order_id
WHERE op.payment_type = 'credit_card'
GROUP BY v.customer_state HAVING COUNT(*) >= 1000
ORDER BY cuotas_promedio DESC LIMIT 3""",
        "respuesta": "Los estados con más cuotas promedio por pago con tarjeta son {f[0][0]} ({f[0][2]:.2f}), {f[1][0]} ({f[1][2]:.2f}) y {f[2][0]} ({f[2][2]:.2f}).",
        "trampas": ["Aquí la unidad es el pago (fila de order_payments), no el pedido."],
    },
    {
        "id": "neg_f6_03_metodo_mayor_valor_2018",
        "familia": "6 · Pagos",
        "pregunta": "Entre los pedidos válidos comprados en 2018, ¿qué método de pago deja el mayor valor pagado promedio por pedido (sumando lo pagado con ese método en cada pedido)?",
        "variantes": ["En 2018, ¿con qué método se pagan los pedidos más caros?"],
        "en_que_se_diferencia": "Restringe a un año y compara el valor promedio por método, no la cantidad de pedidos.",
        "sql": """WITH pm AS (
  SELECT op.order_id, op.payment_type, SUM(op.payment_value) AS valor
  FROM order_payments op JOIN vw_pedidos_validos v ON v.order_id = op.order_id
  WHERE strftime('%Y', v.order_purchase_timestamp) = '2018' AND op.payment_type != 'not_defined'
  GROUP BY op.order_id, op.payment_type
)
SELECT payment_type, COUNT(*) AS pedidos, ROUND(AVG(valor), 2) AS valor_promedio
FROM pm GROUP BY payment_type ORDER BY valor_promedio DESC LIMIT 1""",
        "respuesta": "En 2018, el método con mayor valor promedio por pedido fue {f[0][0]}: R$ {f[0][2]:,.2f} en promedio ({f[0][1]:,} pedidos).",
        "trampas": ["Sumar los pagos del mismo método dentro de cada pedido antes de promediar."],
    },
    {
        "id": "neg_f6_04_estado_mas_a_plazos",
        "familia": "6 · Pagos",
        "pregunta": "Entre los estados del cliente con al menos 1,000 pedidos válidos, ¿en cuál es mayor el porcentaje de pedidos pagados en más de una cuota (tomando el mayor número de cuotas de cada pedido)?",
        "variantes": ["¿Dónde se compra más a plazos?"],
        "en_que_se_diferencia": "La dimensión es el estado del cliente, no la categoría de producto.",
        "sql": """WITH pp AS (
  SELECT v.order_id, v.customer_state, MAX(op.payment_installments) AS cuotas
  FROM vw_pedidos_validos v JOIN order_payments op ON op.order_id = v.order_id
  WHERE op.payment_type != 'not_defined' GROUP BY v.order_id, v.customer_state
)
SELECT customer_state, COUNT(*) AS pedidos, ROUND(100.0 * SUM(CASE WHEN cuotas > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_a_plazos
FROM pp GROUP BY customer_state HAVING COUNT(*) >= 1000
ORDER BY pct_a_plazos DESC LIMIT 1""",
        "respuesta": "El estado donde más se paga a plazos es {f[0][0]}: el {f[0][2]:.2f} % de sus {f[0][1]:,} pedidos usó más de una cuota.",
        "trampas": ["Cuotas del pedido = MAX entre sus pagos; 'a plazos' es > 1.",
                    "Agregar los pagos por pedido antes de contar."],
    },
    {
        "id": "neg_f6_05_pedidos_voucher_combinado",
        "familia": "6 · Pagos",
        "pregunta": "¿Cuántos pedidos válidos se pagaron con voucher combinado con al menos otro método de pago distinto, y cuántos solo con voucher?",
        "variantes": ["¿Los vouchers se usan solos o junto con otro medio de pago?"],
        "en_que_se_diferencia": "Cuenta combinaciones de métodos por pedido.",
        "sql": """WITH mp AS (
  SELECT op.order_id, COUNT(DISTINCT op.payment_type) AS metodos, MAX(CASE WHEN op.payment_type = 'voucher' THEN 1 ELSE 0 END) AS usa_voucher
  FROM order_payments op JOIN vw_pedidos_validos v ON v.order_id = op.order_id GROUP BY op.order_id
)
SELECT SUM(CASE WHEN usa_voucher = 1 AND metodos > 1 THEN 1 ELSE 0 END) AS voucher_combinado,
       SUM(CASE WHEN usa_voucher = 1 AND metodos = 1 THEN 1 ELSE 0 END) AS solo_voucher
FROM mp""",
        "respuesta": "{f[0][0]:,} pedidos combinaron voucher con otro método y {f[0][1]:,} se pagaron solo con voucher.",
        "trampas": ["COUNT(DISTINCT payment_type) por pedido: un pedido puede tener varios pagos del mismo método."],
    },
    {
        "id": "neg_f6_06_mes_2017_boleto_valor",
        "familia": "6 · Pagos",
        "pregunta": "En 2017, ¿en qué mes de compra (AAAA-MM) fue más alto el valor promedio de los pagos con boleto en pedidos válidos?",
        "variantes": ["¿Qué mes de 2017 tuvo los boletos más caros en promedio?"],
        "en_que_se_diferencia": "Fija un método y un año, y agrega por mes.",
        "sql": """SELECT strftime('%Y-%m', v.order_purchase_timestamp) AS mes, COUNT(*) AS pagos, ROUND(AVG(op.payment_value), 2) AS valor_promedio
FROM order_payments op JOIN vw_pedidos_validos v ON v.order_id = op.order_id
WHERE op.payment_type = 'boleto' AND strftime('%Y', v.order_purchase_timestamp) = '2017'
GROUP BY mes ORDER BY valor_promedio DESC LIMIT 1""",
        "respuesta": "El mes de 2017 con boletos más altos en promedio fue {f[0][0]}: R$ {f[0][2]:,.2f} por pago ({f[0][1]:,} pagos).",
        "trampas": ["El mes es el de compra (order_purchase_timestamp), con strftime('%Y-%m', ...)."],
    },
    {
        "id": "neg_f6_07_calif_por_rango_cuotas",
        "familia": "6 · Pagos",
        "pregunta": "Agrupando los pedidos válidos por el mayor número de cuotas de sus pagos (1, de 2 a 5, de 6 a 10 y más de 10), ¿cuál es la calificación promedio de cada grupo?",
        "variantes": ["¿Los clientes que financian en muchas cuotas califican distinto?"],
        "en_que_se_diferencia": "Cruza pagos con reseñas por rango de cuotas, lo que exige agregar ambas tablas por pedido.",
        "sql": f"""WITH pp AS (
  SELECT op.order_id, MAX(op.payment_installments) AS cuotas
  FROM order_payments op JOIN vw_pedidos_validos v ON v.order_id = op.order_id GROUP BY op.order_id
)
SELECT CASE WHEN pp.cuotas <= 1 THEN '1) 1' WHEN pp.cuotas <= 5 THEN '2) 2-5' WHEN pp.cuotas <= 10 THEN '3) 6-10' ELSE '4) mas de 10' END AS rango_cuotas,
       COUNT(*) AS pedidos, ROUND(AVG(r.calif), 2) AS calificacion
FROM pp JOIN {CALIF} r ON r.order_id = pp.order_id
GROUP BY rango_cuotas ORDER BY rango_cuotas""",
        "respuesta": "La calificación promedio es {f[0][2]:.2f} con 1 cuota, {f[1][2]:.2f} con 2 a 5, {f[2][2]:.2f} con 6 a 10 y {f[3][2]:.2f} con más de 10 cuotas.",
        "trampas": ["Agregar pagos y reseñas por pedido ANTES de unirlos (si no, el JOIN multiplica filas).",
                    "Pagos con 0 cuotas caen en el grupo de 1."],
    },
    # ------------------------------------------------------------------ familia 8: insatisfacción
    {
        # Primera versión (por categoría, 1-2 estrellas, >= 300 reseñas) rechazada: SQL 0.718 >= 0.70 frente a n08 (D-41).
        "id": "neg_f8_01_top3_vendedores_resenas_malas",
        "familia": "8 · Insatisfacción",
        "pregunta": "¿Qué 3 vendedores con 200 o más reseñas en pedidos válidos acumulan la mayor proporción de reseñas malas (1 o 2 estrellas)?",
        "variantes": ["¿Qué vendedores grandes concentran más notas bajas?"],
        "en_que_se_diferencia": "La insatisfacción se mide por vendedor y cuenta 1 y 2 estrellas.",
        "sql": """WITH sp AS (
  SELECT DISTINCT oi.seller_id, oi.order_id FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
)
SELECT sp.seller_id, COUNT(*) AS resenas, ROUND(100.0 * SUM(CASE WHEN rv.review_score <= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_malas
FROM sp JOIN order_reviews rv ON rv.order_id = sp.order_id
GROUP BY sp.seller_id HAVING COUNT(*) >= 200
ORDER BY pct_malas DESC LIMIT 3""",
        "respuesta": "Los vendedores con más reseñas de 1 o 2 estrellas son {f[0][0]} ({f[0][2]:.2f} % de {f[0][1]:,} reseñas), {f[1][0]} ({f[1][2]:.2f} %) y {f[2][0]} ({f[2][2]:.2f} %).",
        "trampas": ["DISTINCT vendedor-pedido antes de unir reseñas, para que un pedido con varios artículos no repita sus reseñas.",
                    "1 o 2 estrellas = review_score <= 2."],
    },
    {
        "id": "neg_f8_02_estado_mas_1_estrella",
        "familia": "8 · Insatisfacción",
        "pregunta": "Entre los estados de los compradores con 500 o más reseñas de pedidos válidos, ¿dónde es más frecuente la nota mínima (1 estrella), en porcentaje?",
        "variantes": ["¿En qué estado están los clientes más insatisfechos?"],
        "en_que_se_diferencia": "La dimensión es el estado del cliente, no la categoría.",
        "sql": """SELECT v.customer_state, COUNT(*) AS resenas, ROUND(100.0 * SUM(CASE WHEN rv.review_score = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_1_estrella
FROM order_reviews rv JOIN vw_pedidos_validos v ON v.order_id = rv.order_id
GROUP BY v.customer_state HAVING COUNT(*) >= 500
ORDER BY pct_1_estrella DESC LIMIT 1""",
        "respuesta": "El estado con mayor proporción de reseñas de 1 estrella es {f[0][0]}: {f[0][2]:.2f} % de sus {f[0][1]:,} reseñas.",
        "trampas": ["La unidad es la reseña; no hace falta pasar por order_items (evita duplicar)."],
    },
    {
        "id": "neg_f8_03_top3_categorias_mejor_calificadas",
        "familia": "8 · Insatisfacción",
        "pregunta": "¿Qué 3 categorías (100 o más reseñas de pedidos válidos) tienen a los clientes más contentos según la nota media de las reseñas?",
        "variantes": ["¿Cuáles son las categorías que más gustan a los clientes?"],
        "en_que_se_diferencia": "Busca lo opuesto (mejor calificadas) y usa el promedio de estrellas.",
        "sql": """WITH cp AS (
  SELECT DISTINCT COALESCE(t.product_category_name_english, 'sin_categoria') AS categoria, oi.order_id
  FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
  JOIN products p ON p.product_id = oi.product_id
  LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name
)
SELECT cp.categoria, COUNT(*) AS resenas, ROUND(AVG(rv.review_score), 2) AS calificacion
FROM cp JOIN order_reviews rv ON rv.order_id = cp.order_id
GROUP BY cp.categoria HAVING COUNT(*) >= 100
ORDER BY calificacion DESC LIMIT 3""",
        "respuesta": "Las categorías mejor calificadas son {f[0][0]} ({f[0][2]:.2f}), {f[1][0]} ({f[1][2]:.2f}) y {f[2][0]} ({f[2][2]:.2f}).",
        "trampas": ["DISTINCT categoría-pedido antes de unir reseñas.",
                    "Umbral de reseñas en HAVING."],
    },
    {
        "id": "neg_f8_04_estados_vendedor_problema_producto",
        "familia": "8 · Insatisfacción",
        "pregunta": "Entre los estados de vendedor con al menos 300 reseñas de pedidos válidos, ¿cuáles tienen calificación promedio menor que la global y, a la vez, un porcentaje de entregas tardías menor que el global?",
        "variantes": ["¿Desde qué estados se vende con mala calificación aunque se entregue a tiempo?"],
        "en_que_se_diferencia": "Hace la clasificación 'producto vs logística' por estado del vendedor, no por categoría.",
        "sql": f"""WITH sp AS (
  SELECT DISTINCT s.seller_state, v.order_id, CASE WHEN {TARDE} THEN 1 ELSE 0 END AS tarde,
         v.order_delivered_customer_date AS entregado
  FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id JOIN sellers s ON s.seller_id = oi.seller_id
),
res AS (
  SELECT sp.seller_state, COUNT(*) AS resenas, AVG(rv.review_score) AS calif
  FROM sp JOIN order_reviews rv ON rv.order_id = sp.order_id GROUP BY sp.seller_state HAVING COUNT(*) >= 300
),
tar AS (
  SELECT seller_state, 100.0 * SUM(tarde) / COUNT(*) AS pct_tarde FROM sp WHERE entregado IS NOT NULL GROUP BY seller_state
),
g AS (
  SELECT (SELECT AVG(rv.review_score) FROM order_reviews rv JOIN vw_pedidos_validos v ON v.order_id = rv.order_id) AS calif_global,
         (SELECT 100.0 * SUM(CASE WHEN {TARDE} THEN 1 ELSE 0 END) / COUNT(*) FROM vw_pedidos_validos v WHERE v.order_delivered_customer_date IS NOT NULL) AS tarde_global
)
SELECT res.seller_state, res.resenas, ROUND(res.calif, 2) AS calificacion, ROUND(tar.pct_tarde, 2) AS pct_tarde
FROM res JOIN tar ON tar.seller_state = res.seller_state CROSS JOIN g
WHERE res.calif < g.calif_global AND tar.pct_tarde < g.tarde_global
ORDER BY res.calif""",
        "respuesta": "Hay {n} estado(s) de vendedor con calificación bajo la global pese a entregar a tiempo más que el promedio; el primero es {f[0][0]} (calificación {f[0][2]:.2f}, {f[0][3]:.2f} % tardías).",
        "trampas": ["Promedios globales sobre todas las reseñas y todos los pedidos entregados válidos, no promedio de promedios.",
                    "% tardías solo sobre pedidos entregados."],
    },
    {
        "id": "neg_f8_05_pct_1_estrella_con_comentario",
        "familia": "8 · Insatisfacción",
        "pregunta": "De las reseñas de 1 estrella de pedidos válidos, ¿qué porcentaje incluye un comentario escrito?",
        "variantes": ["¿Los clientes muy insatisfechos suelen explicar por qué?"],
        "en_que_se_diferencia": "Mide comentarios dentro de las reseñas de 1 estrella.",
        "sql": """SELECT ROUND(100.0 * SUM(CASE WHEN rv.review_comment_message IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_con_comentario,
       COUNT(*) AS resenas_1_estrella
FROM order_reviews rv JOIN vw_pedidos_validos v ON v.order_id = rv.order_id
WHERE rv.review_score = 1""",
        "respuesta": "El {f[0][0]:.2f} % de las {f[0][1]:,} reseñas de 1 estrella incluye un comentario escrito.",
        "trampas": ["El universo (1 estrella) va en el WHERE; la condición (comentario) en el CASE."],
    },
    {
        "id": "neg_f8_06_mes_2017_mas_1_estrella",
        "familia": "8 · Insatisfacción",
        "pregunta": "En 2017, ¿en qué mes de compra (AAAA-MM) fue mayor el porcentaje de reseñas de 1 estrella en pedidos válidos?",
        "variantes": ["¿Cuál fue el mes de 2017 con clientes más insatisfechos?"],
        "en_que_se_diferencia": "Agrega por periodo (mes de compra).",
        "sql": """SELECT strftime('%Y-%m', v.order_purchase_timestamp) AS mes, COUNT(*) AS resenas,
       ROUND(100.0 * SUM(CASE WHEN rv.review_score = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_1_estrella
FROM order_reviews rv JOIN vw_pedidos_validos v ON v.order_id = rv.order_id
WHERE strftime('%Y', v.order_purchase_timestamp) = '2017'
GROUP BY mes ORDER BY pct_1_estrella DESC LIMIT 1""",
        # Función, no plantilla: el chequeo de "texto confiable" lee "2017-11" como 2017 y -11 (D-41).
        "respuesta": lambda f, n: (f"El mes de 2017 con más reseñas de 1 estrella fue el mes {int(f[0][0][5:7])}: "
                                   f"{f[0][2]:.2f} % de sus {f[0][1]:,} reseñas."),
        "trampas": ["El mes sale de la fecha de compra del pedido, no de la fecha de la reseña."],
    },
    {
        "id": "neg_f8_07_bed_bath_1_estrella_tarde_vs_tiempo",
        "familia": "8 · Insatisfacción",
        "pregunta": "En la categoría bed_bath_table, ¿qué porcentaje de las reseñas de pedidos válidos entregados es de 1 estrella cuando el pedido llegó tarde, y cuál cuando llegó a tiempo?",
        "variantes": ["En cama, mesa y baño, ¿cuánto empeoran las reseñas si el pedido llega tarde?"],
        "en_que_se_diferencia": "Fija una categoría y separa por puntualidad.",
        "sql": f"""WITH cp AS (
  SELECT DISTINCT v.order_id, CASE WHEN {TARDE} THEN 1 ELSE 0 END AS tarde
  FROM order_items oi JOIN vw_pedidos_validos v ON v.order_id = oi.order_id
  JOIN products p ON p.product_id = oi.product_id
  JOIN product_category_translation t ON t.product_category_name = p.product_category_name
  WHERE t.product_category_name_english = 'bed_bath_table' AND v.order_delivered_customer_date IS NOT NULL
)
SELECT ROUND(100.0 * SUM(CASE WHEN cp.tarde = 1 AND rv.review_score = 1 THEN 1 ELSE 0 END) / SUM(cp.tarde), 2) AS pct_1_tarde,
       ROUND(100.0 * SUM(CASE WHEN cp.tarde = 0 AND rv.review_score = 1 THEN 1 ELSE 0 END) / SUM(1 - cp.tarde), 2) AS pct_1_a_tiempo
FROM cp JOIN order_reviews rv ON rv.order_id = cp.order_id""",
        "respuesta": "En bed_bath_table, el {f[0][0]:.2f} % de las reseñas es de 1 estrella cuando el pedido llegó tarde, frente al {f[0][1]:.2f} % cuando llegó a tiempo.",
        "trampas": ["DISTINCT pedido antes de unir reseñas.",
                    "Cada porcentaje con el denominador de su propio grupo."],
    },
]
