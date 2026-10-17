"""
Construye eval/casos_juez.json: los 6 casos del juez iterativo (Fase 1 de la tarea
"juez con retroalimentación iterativa").

- 5 necesidades de la entrega (2, 4, 5, 6 y 8) y 1 caso de control.
- `sql_referencia` sale de la función qNN() correspondiente de dashboard/queries.py
  (mismos CTE, filtros y redondeos). Lo que en qNN() se decide en pandas (el "quiebre"
  de q02, el filtro de q04 y la clasificación de q08) se reescribe aquí en SQL.
- Verificación (solo lectura): cada referencia se EJECUTA contra db/olist.db y sus
  cifras clave se comparan con lo que devuelve la qNN() del dashboard. Además, ningún
  `patrones_error` puede activarse sobre el propio SQL de referencia.

Uso:
    python -m eval.construir_casos_juez            # verifica y escribe eval/casos_juez.json
    python -m eval.construir_casos_juez --solo-verificar
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from db.olist_database import get_readonly_connection

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "eval" / "casos_juez.json"

V = "o.order_status NOT IN ('canceled', 'unavailable')"
VALIDOS_TXT = "pedidos válidos (sin contar cancelados ni no disponibles)"

VENTAS_VALIDAS = f"""ventas_validas AS (
    SELECT oi.order_id, oi.price, oi.freight_value,
           COALESCE(t.product_category_name_english, 'sin_categoria') AS categoria
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN products p ON p.product_id = oi.product_id
    LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name
    WHERE {V}
)"""

REVIEW_PEDIDO = """review_pedido AS (
    SELECT order_id, AVG(review_score) AS review_score_promedio
    FROM order_reviews
    GROUP BY order_id
)"""

# Patrones reutilizables (regex sobre el SQL candidato, sin distinguir mayúsculas).
P_DIVISION_ENTERA = {
    "regex": r"\A(?![\s\S]*(100\.0|1\.0\s*\*|\*\s*1\.0|AS\s+REAL|AS\s+FLOAT|AVG\s*\())",
    "diagnostico": "El porcentaje se calcula sin forzar decimales: en SQLite entero/entero trunca (usa 100.0 * a / b).",
}
# Vistas de db/olist_views.sql que YA excluyen canceled/unavailable (ronda 2, lección 7, D-37): usarlas
# no es "olvidar el filtro". vw_ventas_pedido y vw_entregas_retrasos traen todos los estatus.
VISTAS_YA_VALIDAS = (r"vw_pedidos_validos|vw_clientes_recurrentes|vw_ingresos_por_categoria|vw_ingresos_por_vendedor"
                     r"|vw_retraso_por_rango|vw_pedidos_entregados|vw_totales_pedido|vw_articulos_vendidos")
P_SIN_VALIDOS = {
    "regex": rf"\A(?![\s\S]*(order_status|{VISTAS_YA_VALIDAS}))",
    "diagnostico": "No filtra pedidos válidos: hay que excluir los estatus 'canceled' y 'unavailable'.",
}
P_FECHA_TRANSPORTISTA = {
    "regex": r"order_delivered_carrier_date",
    "diagnostico": "Usa la fecha de entrega al transportista; la entrega al cliente es order_delivered_customer_date.",
}
P_PAYMENT_VALUE_COMO_INGRESO = {
    "regex": r"payment_value",
    "diagnostico": "Los ingresos/precio se miden con order_items.price, no con payment_value (que incluye flete y cuotas).",
}
P_NOMBRE_PORTUGUES = {
    "regex": r"\A(?![\s\S]*(product_category_name_english|categoria_ingles|categoria_en))",
    "diagnostico": "No usa el nombre de categoría en inglés (product_category_translation.product_category_name_english).",
}

CASOS = [
    {
        "id": "c01_total_pedidos",
        "necesidad": "Control (caso sencillo)",
        "origen": "métrica 'Pedidos' de la cabecera del dashboard (pages/1_Dashboard.py)",
        "pregunta": "¿Cuántos pedidos hay en total en la base, contando todos los estatus (incluidos los cancelados y los no disponibles)?",
        "sql_referencia": "SELECT COUNT(*) AS pedidos FROM orders",
        "respuesta_nl_referencia": "Hay 99,441 pedidos en total, de cualquier estatus.",
        "cifras_clave_nl": [{"tipo": "conteo", "valor": 99441}],
        "criterio_aceptacion": {
            "descripcion": "La primera fila contiene el total exacto de pedidos.",
            "comprobaciones": [
                {"comparador": "valor_con_tolerancia", "tipo": "conteo", "valor": 99441, "donde": "primera_fila"},
            ],
        },
        "dificultades": [
            "La pregunta pide TODOS los estatus: filtrar pedidos válidos da 98,207 (incorrecto aquí).",
            "Contar filas de order_items u order_payments en lugar de orders cuenta artículos o pagos, no pedidos.",
        ],
        "patrones_error": [
            {"regex": rf"order_status|{VISTAS_YA_VALIDAS}", "diagnostico": "La pregunta pide todos los estatus; no hay que filtrar por order_status ni usar vistas que excluyen cancelados."},
            {"regex": r"\bFROM\s+(order_items|order_payments|order_reviews)\b", "diagnostico": "Cuenta filas de una tabla de detalle (artículos, pagos o reseñas), no pedidos."},
        ],
        "verificacion_dashboard": None,
    },
    {
        "id": "n02_quiebre_retraso_calificacion",
        "necesidad": "2 · Retraso vs reseñas",
        "origen": "dashboard/queries.py:q02",
        "pregunta": (
            f"Toma los {VALIDOS_TXT} que ya fueron entregados al cliente y tienen al menos una reseña. "
            "La calificación de cada pedido es el promedio de sus reseñas, y su retraso son los días (con decimales) "
            "entre la fecha estimada de entrega y la fecha real de entrega al cliente (real menos estimada). "
            "Agrupa los pedidos en rangos de retraso: a tiempo (0 o menos), más de 0 y hasta 3 días, más de 3 y hasta 7, "
            "más de 7 y hasta 14, y más de 14. Decimos que la calificación cae notablemente en el primer rango, en orden "
            "creciente de retraso, cuyo porcentaje de pedidos con calificación de 2 o menos es al menos el doble que el de "
            "los pedidos a tiempo. ¿Cuál es ese rango, cuántos pedidos tiene, qué porcentaje de ellos tiene calificación "
            "de 2 o menos y cuál es ese porcentaje en los pedidos a tiempo?"
        ),
        "sql_referencia": f"""WITH entregas AS (
    SELECT o.order_id,
           julianday(o.order_delivered_customer_date) - julianday(o.order_estimated_delivery_date) AS dias_retraso
    FROM orders o
    WHERE o.order_delivered_customer_date IS NOT NULL
      AND {V}
),
{REVIEW_PEDIDO},
rangos AS (
    SELECT
        CASE WHEN e.dias_retraso <= 0 THEN 'a_tiempo'
             WHEN e.dias_retraso <= 3 THEN '1-3'
             WHEN e.dias_retraso <= 7 THEN '4-7'
             WHEN e.dias_retraso <= 14 THEN '8-14'
             ELSE '15+' END AS rango_retraso,
        CASE WHEN e.dias_retraso <= 0 THEN 1
             WHEN e.dias_retraso <= 3 THEN 2
             WHEN e.dias_retraso <= 7 THEN 3
             WHEN e.dias_retraso <= 14 THEN 4
             ELSE 5 END AS orden,
        rp.review_score_promedio
    FROM entregas e
    JOIN review_pedido rp ON rp.order_id = e.order_id
),
tabla AS (
    SELECT rango_retraso, orden, COUNT(*) AS pedidos,
           ROUND(100.0 * SUM(CASE WHEN review_score_promedio <= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_1_2_estrellas
    FROM rangos
    GROUP BY rango_retraso, orden
)
SELECT t.rango_retraso, t.pedidos, t.pct_1_2_estrellas, b.pct_1_2_estrellas AS pct_a_tiempo
FROM tabla t
CROSS JOIN (SELECT pct_1_2_estrellas FROM tabla WHERE orden = 1) b
WHERE t.orden > 1 AND t.pct_1_2_estrellas >= 2 * b.pct_1_2_estrellas
ORDER BY t.orden
LIMIT 1""",
        "respuesta_nl_referencia": (
            "La calificación cae notablemente desde el primer rango con retraso (más de 0 y hasta 3 días): de sus 2,636 "
            "pedidos, el 19.08 % tiene calificación de 2 o menos, frente al 9.19 % de los pedidos entregados a tiempo "
            "(más del doble)."
        ),
        "cifras_clave_nl": [
            {"tipo": "conteo", "valor": 2636},
            {"tipo": "porcentaje", "valor": 19.08},
            {"tipo": "porcentaje", "valor": 9.19},
        ],
        "criterio_aceptacion": {
            "descripcion": (
                "Alguna fila (de a lo sumo 2) contiene los pedidos y el % de calificaciones bajas del rango de quiebre; "
                "el % de los pedidos a tiempo aparece en alguna celda. No se compara la etiqueta del rango."
            ),
            "comprobaciones": [
                {"comparador": "fila_contiene", "fila": "cualquiera", "max_filas": 2,
                 "valores": [{"tipo": "conteo", "valor": 2636}, {"tipo": "porcentaje", "valor": 19.08}]},
                {"comparador": "valor_con_tolerancia", "tipo": "porcentaje", "valor": 9.19, "donde": "cualquier_celda"},
            ],
        },
        "dificultades": [
            "Reseñas duplicadas: un pedido puede tener varias reseñas; la calificación del pedido es su PROMEDIO (con reseñas crudas da 2,651 pedidos y 19.12 %).",
            "Días con decimales: truncar a días enteros (date(), CAST) mueve pedidos entre rangos (da 1,852 pedidos y 32.18 %).",
            "El rango 'más de 0 y hasta 3' incluye retrasos de fracciones de día (0 < retraso <= 3); 'a tiempo' es <= 0.",
            "Fecha correcta: order_delivered_customer_date (no la del transportista) y fechas NULL fuera (no entregados).",
            "Calificación baja es <= 2 (1 o 2 estrellas), no < 2.",
            "El criterio compara porcentajes entre rangos (>= 2x el de 'a tiempo'), no calificaciones promedio.",
            "Porcentaje: 100.0 * a / b para evitar división entera.",
        ],
        "patrones_error": [
            {"regex": r"CAST\s*\(\s*\(?\s*julianday|\bdate\s*\(\s*(\w+\.)?order_(delivered_customer|estimated_delivery)_date",
             "diagnostico": "Trunca el retraso a días enteros; debe ser la diferencia con decimales (julianday real − julianday estimada)."},
            {"regex": r"\A(?![\s\S]*GROUP\s+BY\s+(\w+\.)?order_id)",
             "diagnostico": "No agrupa las reseñas por pedido: un pedido puede tener varias reseñas y su calificación es el promedio."},
            {"regex": r"review_score\w*\s*<\s*2\b(?!\.)",
             "diagnostico": "'< 2' deja fuera las calificaciones de 2; la condición es <= 2."},
            {"regex": r"order_purchase_timestamp",
             "diagnostico": "El retraso se mide contra la fecha ESTIMADA de entrega, no contra la fecha de compra."},
            P_FECHA_TRANSPORTISTA,
            P_DIVISION_ENTERA,
        ],
        "verificacion_dashboard": "q02",
    },
    {
        "id": "n04_vendedores_a_revisar",
        "necesidad": "4 · Vendedores problemáticos",
        "origen": "dashboard/queries.py:q04 (parámetros por defecto: 30 pedidos, 3.5, 15 %, 25 %)",
        "pregunta": (
            "Considera los vendedores con al menos 30 pedidos (pedidos distintos con algún artículo suyo, de cualquier estatus). "
            f"Para cada uno calcula: sus ingresos (suma de price de sus artículos en {VALIDOS_TXT}); su calificación "
            "(promedio, entre sus pedidos válidos con reseña, de la calificación de cada pedido, que es el promedio de las "
            "reseñas de ese pedido); y su % de entregas tardías (porcentaje de sus pedidos válidos entregados al cliente en "
            "los que la entrega real fue posterior a la estimada). ¿Cuántos de esos vendedores están en el 25 % con más "
            "ingresos y además tienen una calificación menor a 3.5 o más del 15 % de entregas tardías, y cuánto suman los "
            "ingresos de esos vendedores?"
        ),
        "sql_referencia": f"""WITH {REVIEW_PEDIDO},
pedidos_vendedor AS (
    SELECT DISTINCT oi.seller_id, o.order_id, o.order_status
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
),
resumen_pedidos AS (
    SELECT seller_id, COUNT(DISTINCT order_id) AS pedidos_totales
    FROM pedidos_vendedor
    GROUP BY seller_id
    HAVING COUNT(DISTINCT order_id) >= 30
),
ingresos_vendedor AS (
    SELECT oi.seller_id, SUM(oi.price) AS ingresos
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE {V}
    GROUP BY oi.seller_id
),
entregas_vendedor_raw AS (
    SELECT DISTINCT oi.seller_id, o.order_id,
           CASE WHEN julianday(o.order_delivered_customer_date) > julianday(o.order_estimated_delivery_date)
                THEN 1 ELSE 0 END AS entrega_tardia
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE o.order_delivered_customer_date IS NOT NULL
      AND {V}
),
entregas_vendedor AS (
    SELECT seller_id, ROUND(100.0 * SUM(entrega_tardia) / COUNT(*), 2) AS pct_entregas_tardias
    FROM entregas_vendedor_raw
    GROUP BY seller_id
),
calificacion_vendedor_raw AS (
    SELECT DISTINCT oi.seller_id, o.order_id, rp.review_score_promedio
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN review_pedido rp ON rp.order_id = o.order_id
    WHERE {V}
),
calificacion_vendedor AS (
    SELECT seller_id, ROUND(AVG(review_score_promedio), 2) AS calificacion_promedio
    FROM calificacion_vendedor_raw
    GROUP BY seller_id
),
vendedores AS (
    SELECT rp.seller_id,
           ROUND(COALESCE(iv.ingresos, 0), 2) AS ingresos,
           cv.calificacion_promedio,
           ev.pct_entregas_tardias,
           PERCENT_RANK() OVER (ORDER BY COALESCE(iv.ingresos, 0) DESC) AS percentil_ingresos_desc
    FROM resumen_pedidos rp
    LEFT JOIN ingresos_vendedor iv ON iv.seller_id = rp.seller_id
    LEFT JOIN entregas_vendedor ev ON ev.seller_id = rp.seller_id
    LEFT JOIN calificacion_vendedor cv ON cv.seller_id = rp.seller_id
)
SELECT COUNT(*) AS vendedores_a_revisar, ROUND(SUM(ingresos), 2) AS ingresos_combinados
FROM vendedores
WHERE percentil_ingresos_desc <= 0.25
  AND (calificacion_promedio < 3.5 OR pct_entregas_tardias > 15)""",
        "respuesta_nl_referencia": (
            "13 vendedores (de 634 con al menos 30 pedidos) están en el 25 % superior de ingresos y tienen calificación "
            "menor a 3.5 o más del 15 % de entregas tardías; en conjunto suman R$ 574,541.26 de ingresos."
        ),
        "cifras_clave_nl": [
            {"tipo": "conteo", "valor": 13},
            {"tipo": "dinero", "valor": 574541.26},
        ],
        "criterio_aceptacion": {
            "descripcion": "La primera fila contiene el número de vendedores y la suma de sus ingresos.",
            "comprobaciones": [
                {"comparador": "fila_contiene", "fila": "primera", "max_filas": None,
                 "valores": [{"tipo": "conteo", "valor": 13}, {"tipo": "dinero", "valor": 574541.26}]},
            ],
        },
        "dificultades": [
            "Reseñas duplicadas: la calificación del pedido es el promedio de sus reseñas; con reseñas crudas salen 14 vendedores y R$ 597,265.18.",
            "Abanico de JOIN: unir order_items con reseñas o pagos en el mismo nivel que SUM(price) multiplica los ingresos.",
            "COUNT vs COUNT DISTINCT: un pedido con varios artículos del mismo vendedor cuenta una sola vez.",
            "Universos distintos: el mínimo de 30 pedidos cuenta todos los estatus; ingresos, calificación y % tardías solo pedidos válidos.",
            "% tardías: denominador = pedidos válidos ENTREGADOS (fecha de entrega al cliente no NULL).",
            "La condición es calificación baja O muchas tardías (OR, no AND), y solo dentro del 25 % superior de ingresos.",
            "El 25 % superior es por percentil sobre los vendedores elegibles (PERCENT_RANK o CUME_DIST dan lo mismo aquí), no LIMIT 25.",
            "Agregar primero por vendedor y filtrar después (WHERE/HAVING sobre agregados en el nivel correcto).",
        ],
        "patrones_error": [
            {"regex": r"\bLIMIT\s+25\b", "diagnostico": "'El 25 % con más ingresos' es un percentil de los vendedores elegibles, no los 25 primeros."},
            {"regex": r"calif\w*\s*<\s*3\.5\s+AND\b", "diagnostico": "La condición es calificación < 3.5 O % tardías > 15 (OR), no AND."},
            {"regex": r"\bAVG\s*\(\s*(\w+\.)?price\b", "diagnostico": "Los ingresos son la SUMA de price, no su promedio."},
            {"regex": r"\A(?![\s\S]*GROUP\s+BY\s+(\w+\.)?order_id)",
             "diagnostico": "No agrupa las reseñas por pedido: la calificación de cada pedido es el promedio de sus reseñas."},
            {"regex": r"JOIN\s+order_(reviews|payments)\b[\s\S]*SUM\s*\(\s*(\w+\.)?price",
             "diagnostico": "Posible abanico: un JOIN con reseñas o pagos antes de SUM(price) duplica artículos y multiplica los ingresos."},
            P_PAYMENT_VALUE_COMO_INGRESO,
            P_FECHA_TRANSPORTISTA,
            P_SIN_VALIDOS,
        ],
        "verificacion_dashboard": "q04",
    },
    {
        "id": "n05_categorias_peso_flete",
        "necesidad": "5 · Flete",
        "origen": "dashboard/queries.py:q05 (tabla de categorías, min_ingresos_categoria = 5000)",
        "pregunta": (
            "Entre las categorías de producto (nombre en inglés; los productos sin categoría cuentan como 'sin_categoria') "
            f"con ingresos de al menos R$ 5,000 (suma de price en {VALIDOS_TXT}), ¿cuáles son las 3 en las que el flete pesa "
            "más sobre el precio, medido como flete total entre precio total de la categoría (en porcentaje), y cuál es ese "
            "porcentaje en cada una? Ordénalas de mayor a menor."
        ),
        "sql_referencia": f"""WITH {VENTAS_VALIDAS}
SELECT categoria,
       ROUND(SUM(price), 2) AS ingresos,
       ROUND(SUM(freight_value), 2) AS flete_total,
       ROUND(100.0 * SUM(freight_value) / NULLIF(SUM(price), 0), 2) AS pct_flete_sobre_precio
FROM ventas_validas
GROUP BY categoria
HAVING SUM(price) >= 5000
ORDER BY pct_flete_sobre_precio DESC
LIMIT 3""",
        "respuesta_nl_referencia": (
            "Las 3 categorías donde más pesa el flete son christmas_supplies (36.66 %), signaling_and_security (30.26 %) "
            "y food_drink (29.69 %)."
        ),
        "cifras_clave_nl": [
            {"tipo": "porcentaje", "valor": 36.66},
            {"tipo": "porcentaje", "valor": 30.26},
            {"tipo": "porcentaje", "valor": 29.69},
        ],
        "criterio_aceptacion": {
            "descripcion": "Las 3 primeras filas son esas categorías en ese orden, cada una con su porcentaje.",
            "comprobaciones": [
                {"comparador": "top_k_igual", "k": 3, "tipo": "texto", "orden_importa": True,
                 "valores": ["christmas_supplies", "signaling_and_security", "food_drink"]},
                {"comparador": "fila_contiene", "fila": "primera", "max_filas": None,
                 "valores": [{"tipo": "texto", "valor": "christmas_supplies"}, {"tipo": "porcentaje", "valor": 36.66}]},
                {"comparador": "fila_contiene", "fila": "cualquiera", "max_filas": None,
                 "valores": [{"tipo": "texto", "valor": "signaling_and_security"}, {"tipo": "porcentaje", "valor": 30.26}]},
                {"comparador": "fila_contiene", "fila": "cualquiera", "max_filas": None,
                 "valores": [{"tipo": "texto", "valor": "food_drink"}, {"tipo": "porcentaje", "valor": 29.69}]},
            ],
        },
        "dificultades": [
            "SUM/SUM, no AVG de razones: el promedio fila a fila de flete/precio cambia el ranking (electronics 68.55 % pasaría al primer lugar).",
            "El umbral de R$ 5,000 es sobre los ingresos de la CATEGORÍA (HAVING SUM(price) >= 5000), no sobre cada artículo; sin él ganan categorías minúsculas (home_comfort_2).",
            "Solo pedidos válidos: con todos los estatus christmas_supplies da 36.69 % (fuera de tolerancia).",
            "Nombre en inglés vía product_category_translation (LEFT JOIN); sin categoría = 'sin_categoria'.",
            "Precio = order_items.price; payment_value no es el precio del producto.",
            "Abanico: unir con pagos o reseñas duplica artículos y altera las sumas.",
            "Porcentaje: 100.0 * a / b.",
        ],
        "patrones_error": [
            {"regex": r"\bAVG\s*\([^)]*freight_value\s*/", "diagnostico": "Promedio de razones fila a fila: el peso del flete de la categoría es SUM(flete) / SUM(precio)."},
            {"regex": r"\A(?![\s\S]*\b5000\b)", "diagnostico": "Falta el umbral de ingresos de la categoría (al menos R$ 5,000)."},
            {"regex": r"WHERE[^;]*?\bprice\s*>=?\s*5000\b", "diagnostico": "El umbral de R$ 5,000 se aplica a la suma de ingresos de la categoría (HAVING), no al precio de cada artículo."},
            {"regex": r"JOIN\s+order_(reviews|payments)\b", "diagnostico": "Unir con reseñas o pagos duplica artículos y altera las sumas de precio y flete."},
            P_PAYMENT_VALUE_COMO_INGRESO,
            P_NOMBRE_PORTUGUES,
            P_SIN_VALIDOS,
        ],
        "verificacion_dashboard": "q05",
    },
    {
        "id": "n06_categoria_mas_a_plazos",
        "necesidad": "6 · Pagos",
        "origen": "dashboard/queries.py:q06 (tabla de categorías a plazos, min_pedidos_categoria = 100)",
        "pregunta": (
            f"Considera los {VALIDOS_TXT} y sus pagos, sin contar los pagos cuyo método es 'not_defined'. El número de "
            "cuotas de un pedido es el mayor número de cuotas entre sus pagos, y un pedido se pagó a plazos si ese número es "
            "mayor que 1. Para cada categoría de producto (nombre en inglés; sin categoría = 'sin_categoria') cuenta los "
            "pedidos distintos que tienen al menos un artículo de esa categoría (un pedido con varias categorías cuenta en "
            "cada una). Entre las categorías con al menos 100 de esos pedidos, ¿cuál tiene el mayor porcentaje de pedidos "
            "pagados a plazos y cuál es ese porcentaje?"
        ),
        "sql_referencia": f"""WITH {VENTAS_VALIDAS},
pedido_pagos AS (
    SELECT op.order_id, MAX(op.payment_installments) AS max_cuotas
    FROM order_payments op
    JOIN orders o ON o.order_id = op.order_id
    WHERE op.payment_type != 'not_defined'
      AND {V}
    GROUP BY op.order_id
),
categoria_pedido AS (
    SELECT DISTINCT categoria, order_id FROM ventas_validas
)
SELECT cp.categoria,
       COUNT(*) AS pedidos,
       ROUND(100.0 * SUM(CASE WHEN pp.max_cuotas > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_mas_de_1_cuota
FROM categoria_pedido cp
JOIN pedido_pagos pp ON pp.order_id = cp.order_id
GROUP BY cp.categoria
HAVING COUNT(*) >= 100
ORDER BY pct_mas_de_1_cuota DESC
LIMIT 1""",
        "respuesta_nl_referencia": "La categoría que más se paga a plazos es computers: el 79.01 % de sus 181 pedidos se pagó en más de una cuota.",
        "cifras_clave_nl": [
            {"tipo": "porcentaje", "valor": 79.01},
        ],
        "criterio_aceptacion": {
            "descripcion": "La primera fila contiene la categoría y su porcentaje de pedidos a plazos.",
            "comprobaciones": [
                {"comparador": "fila_contiene", "fila": "primera", "max_filas": None,
                 "valores": [{"tipo": "texto", "valor": "computers"}, {"tipo": "porcentaje", "valor": 79.01}]},
            ],
        },
        "dificultades": [
            "Granularidad: se cuentan PEDIDOS distintos por categoría, no artículos (por artículo: 203 y 78.82 %).",
            "Varios pagos por pedido: las cuotas del pedido son el MÁXIMO entre sus pagos; tomar cada fila de pago o el mínimo cambia el % (con MIN: 75.69 %).",
            "Abanico order_items × order_payments: unirlos sin agregar antes duplica filas.",
            "'A plazos' es más de 1 cuota (> 1); hay pagos con 0 cuotas que no son a plazos.",
            "Todos los métodos de pago cuentan (no solo tarjeta), excepto 'not_defined'.",
            "Umbral de 100 pedidos por categoría (HAVING), no por artículo.",
            "Porcentaje: 100.0 * a / b.",
        ],
        "patrones_error": [
            {"regex": r"payment_installments\s*>=\s*1\b|payment_installments\s*>\s*0\b",
             "diagnostico": "Pagado a plazos es más de 1 cuota (> 1); >= 1 incluye los pagos de contado."},
            {"regex": r"payment_type\s*=\s*'credit_card'", "diagnostico": "La pregunta incluye todos los métodos de pago (menos 'not_defined'), no solo tarjeta de crédito."},
            {"regex": r"\A(?![\s\S]*\bDISTINCT\b)", "diagnostico": "No usa DISTINCT: probablemente cuenta artículos (o filas de pago) en lugar de pedidos distintos."},
            {"regex": r"\A(?![\s\S]*\bMAX\s*\(\s*(\w+\.)?payment_installments)",
             "diagnostico": "Las cuotas del pedido son el máximo entre sus pagos; hay que agregar order_payments por pedido."},
            {"regex": r"\A(?![\s\S]*(>=|>)\s*100\b(?!\.))", "diagnostico": "Falta el mínimo de 100 pedidos por categoría."},
            P_NOMBRE_PORTUGUES,
            P_SIN_VALIDOS,
            P_DIVISION_ENTERA,
        ],
        "verificacion_dashboard": "q06",
    },
    {
        "id": "n08_categorias_problema_producto",
        "necesidad": "8 · Insatisfacción",
        "origen": "dashboard/queries.py:q08 (min_resenas = 100; clasificación 'problema_de_producto')",
        "pregunta": (
            f"Usa solo {VALIDOS_TXT}. Las reseñas de una categoría de producto (nombre en inglés; sin categoría = "
            "'sin_categoria') son las reseñas de los pedidos que tienen algún artículo de esa categoría (cada reseña cuenta "
            "una vez por categoría, aunque el pedido tenga varios artículos de ella). Considera solo categorías con al menos "
            "100 reseñas. Una categoría tiene mala calificación si el promedio de sus reseñas es menor que el promedio de "
            "todas las reseñas de pedidos válidos. Su % de entregas tardías es el porcentaje de sus pedidos entregados al "
            "cliente en los que la entrega real fue posterior a la estimada, y el % global se calcula igual sobre todos los "
            "pedidos válidos entregados. ¿Qué categorías tienen mala calificación y, a la vez, un % de entregas tardías menor "
            "que el global (es decir, la insatisfacción no se explica por retrasos)?"
        ),
        "sql_referencia": f"""WITH {VENTAS_VALIDAS},
categoria_pedido AS (
    SELECT DISTINCT categoria, order_id FROM ventas_validas
),
resumen_categoria AS (
    SELECT cp.categoria, COUNT(*) AS num_resenas, ROUND(AVG(r.review_score), 2) AS calificacion_promedio
    FROM categoria_pedido cp
    JOIN order_reviews r ON r.order_id = cp.order_id
    GROUP BY cp.categoria
    HAVING COUNT(*) >= 100
),
tardios_categoria AS (
    SELECT cp.categoria,
           ROUND(100.0 * SUM(CASE WHEN julianday(o.order_delivered_customer_date) > julianday(o.order_estimated_delivery_date)
                                  THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_tardios
    FROM categoria_pedido cp
    JOIN orders o ON o.order_id = cp.order_id
    WHERE o.order_delivered_customer_date IS NOT NULL
    GROUP BY cp.categoria
),
global AS (
    SELECT
        (SELECT ROUND(AVG(r.review_score), 4) FROM order_reviews r
            JOIN orders o ON o.order_id = r.order_id
            WHERE {V}) AS calificacion_global,
        (SELECT ROUND(100.0 * SUM(CASE WHEN julianday(o.order_delivered_customer_date) > julianday(o.order_estimated_delivery_date)
                                       THEN 1 ELSE 0 END) / COUNT(*), 4)
            FROM orders o
            WHERE o.order_delivered_customer_date IS NOT NULL AND {V}) AS pct_tardios_global
)
SELECT rc.categoria
FROM resumen_categoria rc
JOIN tardios_categoria tc ON tc.categoria = rc.categoria
CROSS JOIN global g
WHERE rc.calificacion_promedio < g.calificacion_global
  AND tc.pct_tardios < g.pct_tardios_global
ORDER BY rc.categoria""",
        "respuesta_nl_referencia": None,  # se completa con el resultado ejecutado (lista de categorías)
        "cifras_clave_nl": [{"tipo": "conteo", "valor": 11}],
        "criterio_aceptacion": {
            "descripcion": "El conjunto de categorías devuelto es exactamente el esperado (sin importar el orden).",
            "comprobaciones": [
                {"comparador": "conjunto_igual", "tipo": "texto", "valores": None},  # se completa con el resultado
            ],
        },
        "dificultades": [
            "Promedio global de TODAS las reseñas de pedidos válidos, no el promedio de los promedios por categoría.",
            "Aquí la calificación usa las reseñas crudas (cada reseña cuenta), a diferencia de las necesidades 2 y 4.",
            "Un pedido con varios artículos de la misma categoría aporta sus reseñas una sola vez a esa categoría (DISTINCT categoría-pedido antes de unir reseñas).",
            "% tardías solo sobre pedidos ENTREGADOS al cliente (fecha no NULL), por categoría y global.",
            "'Mala calificación' es relativa al promedio global, no a un número fijo como 3 o 4.",
            "Umbral de 100 reseñas por categoría con HAVING (sobre el agregado, no en WHERE).",
            "Dos agregados distintos (reseñas y entregas) por categoría: calcularlos en subconsultas separadas para no cruzar filas.",
        ],
        "patrones_error": [
            {"regex": r"\A(?![\s\S]*order_delivered_customer_date\s+IS\s+NOT\s+NULL)",
             "diagnostico": "El % de entregas tardías debe calcularse solo sobre pedidos entregados (fecha de entrega al cliente no NULL)."},
            {"regex": r"\A(?![\s\S]*(>=|>)\s*100\b(?!\.))", "diagnostico": "Falta el mínimo de 100 reseñas por categoría."},
            {"regex": r"(calif\w*|review_score\w*|avg\w*)\s*<\s*[1-5](\.\d+)?\b",
             "diagnostico": "'Mala calificación' se compara con el promedio global de reseñas, no con un número fijo."},
            {"regex": r"\bAVG\s*\(\s*(\w+\.)?(calificacion\w*|avg\w*|promedio\w*)\s*\)",
             "diagnostico": "Posible promedio de promedios: el promedio global es sobre todas las reseñas, no sobre los promedios de cada categoría."},
            P_FECHA_TRANSPORTISTA,
            P_NOMBRE_PORTUGUES,
            P_SIN_VALIDOS,
        ],
        "verificacion_dashboard": "q08",
    },
]


def _ejecutar(conn, sql):
    cur = conn.execute(sql)
    return [d[0] for d in cur.description], [list(f) for f in cur.fetchall()]


def _cifras_dashboard(nombre: str) -> dict:
    """Cifras clave de la qNN() del dashboard, para contrastar con la referencia."""
    from dashboard import queries as Q

    r = getattr(Q, nombre)()
    if nombre == "q02":
        t = r["tablas"]["retraso_vs_calificacion"]
        base = float(t.loc[t["rango_retraso"] == "a_tiempo", "pct_1_2_estrellas"].iloc[0])
        q = t[(t["rango_retraso"] != "a_tiempo") & (t["pct_1_2_estrellas"] >= 2 * base)].iloc[0]
        return {"filas": [[q["rango_retraso"], int(q["pedidos"]), float(q["pct_1_2_estrellas"]), base]]}
    if nombre == "q04":
        rv = r["tablas"]["vendedores_a_revisar"]
        return {"filas": [[len(rv), round(float(rv["ingresos"].sum()), 2)]]}
    if nombre == "q05":
        t = r["tablas"]["top_10_categorias_flete"].head(3)
        return {"filas": t.values.tolist()}
    if nombre == "q06":
        t = r["tablas"]["categorias_mas_pagadas_a_plazos"].head(1)
        return {"filas": t.values.tolist()}
    if nombre == "q08":
        t = r["tablas"]["insatisfaccion_por_categoria"]
        return {"filas": [[c] for c in sorted(t.loc[t["clasificacion"] == "problema_de_producto", "categoria"])]}
    raise ValueError(nombre)


def construir(escribir: bool) -> int:
    conn = get_readonly_connection()
    fallos = 0
    salida = []
    try:
        for caso in CASOS:
            caso = json.loads(json.dumps(caso))  # copia profunda
            cols, filas = _ejecutar(conn, caso["sql_referencia"])
            print(f"== {caso['id']}: {len(filas)} fila(s) {cols}")
            for f in filas[:12]:
                print("   ", f)

            # Patrones: deben compilar y no activarse sobre la propia referencia.
            for p in caso["patrones_error"]:
                if re.search(p["regex"], caso["sql_referencia"], re.IGNORECASE):
                    print(f"   [FALLO] el patrón se activa sobre la referencia: {p['regex']}")
                    fallos += 1

            if caso["id"] == "n08_categorias_problema_producto":
                nombres = [f[0] for f in filas]
                caso["criterio_aceptacion"]["comprobaciones"][0]["valores"] = nombres
                caso["respuesta_nl_referencia"] = (
                    f"{len(nombres)} categorías tienen mala calificación sin que la explique el retraso "
                    f"(insatisfacción por producto): " + ", ".join(nombres) + "."
                )
                caso["cifras_clave_nl"] = [{"tipo": "conteo", "valor": len(nombres)}]

            if caso["verificacion_dashboard"]:
                dash = _cifras_dashboard(caso["verificacion_dashboard"])["filas"]
                if caso["id"] == "n05_categorias_peso_flete":
                    comparable = [[f[0], f[3]] for f in filas], [[f[0], f[3]] for f in dash]
                else:
                    comparable = filas, dash
                ok = comparable[0] == comparable[1]
                print(f"   dashboard {caso['verificacion_dashboard']}(): {dash} -> {'OK' if ok else 'FALLO'}")
                fallos += 0 if ok else 1

            caso["resultado_referencia"] = {"columnas": cols, "filas": filas}
            salida.append(caso)
    finally:
        conn.close()

    print(f"\nFallos de verificación: {fallos}")
    if escribir and not fallos:
        doc = {
            "version": 1,
            "descripcion": (
                "Casos del juez iterativo: necesidades 2, 4, 5, 6 y 8 de la entrega + 1 control. "
                "sql_referencia, resultado_referencia, respuesta_nl_referencia y cifras_clave_nl NUNCA "
                "entran al prompt del modelo candidato."
            ),
            "generado_con": "python -m eval.construir_casos_juez",
            "casos": salida,
        }
        SALIDA.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Escrito {SALIDA.relative_to(RAIZ)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-verificar", action="store_true")
    a = ap.parse_args()
    raise SystemExit(construir(escribir=not a.solo_verificar))
