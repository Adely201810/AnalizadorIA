"""
Dashboard de verificación: 10 funciones (q01..q10), una por necesidad del
dueño, que consultan directamente las TABLAS BASE de db/olist.db (orders,
order_items, customers, sellers, products, order_payments, order_reviews,
product_category_translation) -- nunca las vistas vw_* del chatbot -- para
que este dashboard sea una comprobación independiente.

Convenciones (documentadas también en cada "notas"):
  - Cliente = customer_unique_id (una persona puede tener varios customer_id).
  - "Pedido válido" = order_status NOT IN ('canceled', 'unavailable'). Los
    ingresos/ventas siempre se calculan sobre pedidos válidos. Cuando una
    métrica necesita otros estatus (cancelaciones, por ejemplo) se indica
    explícitamente en la función y en sus notas.
  - Categoría = product_category_translation.product_category_name_english
    vía LEFT JOIN, con COALESCE(..., 'sin_categoria').
  - Diferencias de fechas: julianday(a) - julianday(b), en días.
  - Ratios de agregados (flete/ingresos, etc.) se calculan SUM/SUM, nunca
    como promedio de razones por fila.
  - Toda "respuesta_clave" se arma con f-strings sobre resultados ya
    calculados por SQL/pandas; no interviene ningún LLM.

Cada función devuelve un dict:
  {
    "pregunta": str,
    "respuesta_clave": str (en español, con cifras formateadas),
    "tablas": {nombre: pd.DataFrame, ...},
    "parametros": {nombre: valor, ...},
    "sql": str (todas las sentencias SQL ejecutadas, para auditar),
    "notas": str (definiciones y limitaciones),
  }
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from db.olist_database import get_readonly_connection

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _conn() -> sqlite3.Connection:
    return get_readonly_connection()


def _run(conn: sqlite3.Connection, sql: str, params: tuple | list | None = None) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params or [])


def _money(v) -> str:
    if v is None or pd.isna(v):
        return "R$ 0,00"
    return f"R$ {v:,.2f}"


def _pct(v) -> str:
    if v is None or pd.isna(v):
        return "0.0%"
    return f"{v:.1f}%"


# Fragmentos de SQL reutilizados (CTEs) --------------------------------------

PEDIDOS_CLIENTE_CTE = """
pedidos_cliente AS (
    SELECT o.order_id, c.customer_unique_id, c.customer_state, o.order_purchase_timestamp
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
)"""

PAGOS_PEDIDO_CTE = """
pagos_pedido AS (
    SELECT order_id, SUM(payment_value) AS total_pagado
    FROM order_payments
    GROUP BY order_id
)"""

REVIEW_PEDIDO_CTE = """
review_pedido AS (
    SELECT order_id, AVG(review_score) AS review_score_promedio
    FROM order_reviews
    GROUP BY order_id
)"""

VENTAS_VALIDAS_CTE = """
ventas_validas AS (
    SELECT
        oi.order_id,
        oi.price,
        oi.freight_value,
        oi.seller_id,
        se.seller_state,
        c.customer_unique_id,
        c.customer_state,
        o.order_purchase_timestamp,
        COALESCE(t.product_category_name_english, 'sin_categoria') AS categoria
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN customers c ON c.customer_id = o.customer_id
    JOIN products p ON p.product_id = oi.product_id
    LEFT JOIN sellers se ON se.seller_id = oi.seller_id
    LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
)"""

ENTREGAS_CTE = """
entregas AS (
    SELECT
        o.order_id,
        julianday(o.order_delivered_customer_date) - julianday(o.order_estimated_delivery_date) AS dias_retraso,
        CASE WHEN julianday(o.order_delivered_customer_date) > julianday(o.order_estimated_delivery_date)
             THEN 1 ELSE 0 END AS entrega_tardia
    FROM orders o
    WHERE o.order_delivered_customer_date IS NOT NULL
      AND o.order_status NOT IN ('canceled', 'unavailable')
)"""

RESUMEN_CLIENTE_CTE = """
clientes AS (
    SELECT customer_unique_id, COUNT(DISTINCT order_id) AS num_pedidos
    FROM pedidos_cliente
    GROUP BY customer_unique_id
),
gasto_cliente AS (
    SELECT pc.customer_unique_id, SUM(COALESCE(pp.total_pagado, 0)) AS gasto_total
    FROM pedidos_cliente pc
    LEFT JOIN pagos_pedido pp ON pp.order_id = pc.order_id
    GROUP BY pc.customer_unique_id
),
primer_pedido AS (
    SELECT customer_unique_id, order_id
    FROM (
        SELECT customer_unique_id, order_id,
               ROW_NUMBER() OVER (
                   PARTITION BY customer_unique_id
                   ORDER BY order_purchase_timestamp ASC, order_id ASC
               ) AS rn
        FROM pedidos_cliente
    )
    WHERE rn = 1
),
resumen_cliente AS (
    SELECT
        cl.customer_unique_id,
        cl.num_pedidos,
        CASE WHEN cl.num_pedidos > 1 THEN 1 ELSE 0 END AS es_recurrente,
        gc.gasto_total,
        rp.review_score_promedio AS calif_primer_pedido
    FROM clientes cl
    LEFT JOIN gasto_cliente gc ON gc.customer_unique_id = cl.customer_unique_id
    LEFT JOIN primer_pedido pped ON pped.customer_unique_id = cl.customer_unique_id
    LEFT JOIN review_pedido rp ON rp.order_id = pped.order_id
)"""

# El fragmento anterior referencia "review_pedido", que debe declararse antes
# en el WITH de cada consulta que use RESUMEN_CLIENTE_CTE (junto con
# pedidos_cliente y pagos_pedido).


# ---------------------------------------------------------------------------
# 1. Retención
# ---------------------------------------------------------------------------


def q01(min_clientes_categoria: int = 200) -> dict:
    pregunta = (
        "¿Qué porcentaje de clientes son recurrentes (más de 1 pedido válido), "
        "cómo se comparan contra los no recurrentes, qué compran y en qué "
        "categorías/estados hay mejor tasa de recompra?"
    )
    conn = _conn()
    try:
        sql_comparacion = f"""
        WITH {PEDIDOS_CLIENTE_CTE},
        {PAGOS_PEDIDO_CTE},
        {REVIEW_PEDIDO_CTE},
        {RESUMEN_CLIENTE_CTE}
        SELECT
            es_recurrente,
            COUNT(*) AS clientes,
            ROUND(AVG(gasto_total), 2) AS gasto_promedio,
            ROUND(AVG(calif_primer_pedido), 2) AS calificacion_primer_pedido_promedio
        FROM resumen_cliente
        GROUP BY es_recurrente
        """
        comparacion = _run(conn, sql_comparacion)

        sql_top_categorias = f"""
        WITH {PEDIDOS_CLIENTE_CTE},
        {PAGOS_PEDIDO_CTE},
        {REVIEW_PEDIDO_CTE},
        {RESUMEN_CLIENTE_CTE},
        {VENTAS_VALIDAS_CTE}
        SELECT
            v.categoria,
            COUNT(DISTINCT v.customer_unique_id) AS clientes_recurrentes,
            ROUND(SUM(v.price), 2) AS ingresos
        FROM ventas_validas v
        JOIN resumen_cliente rc ON rc.customer_unique_id = v.customer_unique_id
        WHERE rc.es_recurrente = 1
        GROUP BY v.categoria
        ORDER BY ingresos DESC
        LIMIT 10
        """
        top_categorias = _run(conn, sql_top_categorias)

        sql_top_estados = f"""
        WITH {PEDIDOS_CLIENTE_CTE},
        {PAGOS_PEDIDO_CTE},
        {REVIEW_PEDIDO_CTE},
        {RESUMEN_CLIENTE_CTE},
        {VENTAS_VALIDAS_CTE}
        SELECT
            v.customer_state,
            COUNT(DISTINCT v.customer_unique_id) AS clientes_recurrentes
        FROM ventas_validas v
        JOIN resumen_cliente rc ON rc.customer_unique_id = v.customer_unique_id
        WHERE rc.es_recurrente = 1
        GROUP BY v.customer_state
        ORDER BY clientes_recurrentes DESC
        LIMIT 10
        """
        top_estados = _run(conn, sql_top_estados)

        sql_recompra_categoria = f"""
        WITH {PEDIDOS_CLIENTE_CTE},
        {PAGOS_PEDIDO_CTE},
        {REVIEW_PEDIDO_CTE},
        {RESUMEN_CLIENTE_CTE},
        {VENTAS_VALIDAS_CTE},
        clientes_categoria AS (
            SELECT DISTINCT categoria, customer_unique_id
            FROM ventas_validas
        )
        SELECT
            cc.categoria,
            COUNT(*) AS clientes,
            SUM(rc.es_recurrente) AS clientes_recurrentes,
            ROUND(100.0 * SUM(rc.es_recurrente) / COUNT(*), 2) AS tasa_recompra_pct
        FROM clientes_categoria cc
        JOIN resumen_cliente rc ON rc.customer_unique_id = cc.customer_unique_id
        GROUP BY cc.categoria
        HAVING COUNT(*) >= ?
        ORDER BY tasa_recompra_pct DESC
        """
        recompra_categoria = _run(conn, sql_recompra_categoria, (min_clientes_categoria,))
    finally:
        conn.close()

    total_clientes = int(comparacion["clientes"].sum())
    fila_rec = comparacion[comparacion["es_recurrente"] == 1]
    fila_no_rec = comparacion[comparacion["es_recurrente"] == 0]
    clientes_rec = int(fila_rec["clientes"].iloc[0]) if not fila_rec.empty else 0
    pct_recurrentes = 100.0 * clientes_rec / total_clientes if total_clientes else 0.0
    gasto_rec = float(fila_rec["gasto_promedio"].iloc[0]) if not fila_rec.empty else 0.0
    gasto_no_rec = float(fila_no_rec["gasto_promedio"].iloc[0]) if not fila_no_rec.empty else 0.0

    respuesta_clave = (
        f"{pct_recurrentes:.1f}% de los clientes ({clientes_rec:,} de {total_clientes:,}) "
        f"son recurrentes. Su gasto total promedio es {_money(gasto_rec)} vs "
        f"{_money(gasto_no_rec)} de los no recurrentes "
        f"({(gasto_rec / gasto_no_rec - 1) * 100 if gasto_no_rec else 0:.1f}% más). "
        f"Categorías con mejor tasa de recompra (mín. {min_clientes_categoria} clientes): "
        + (
            ", ".join(
                f"{r.categoria} ({r.tasa_recompra_pct:.1f}%)"
                for r in recompra_categoria.head(3).itertuples()
            )
            if not recompra_categoria.empty
            else "sin categorías con suficiente volumen"
        )
        + "."
    )

    sql_total = "\n\n".join(
        [sql_comparacion, sql_top_categorias, sql_top_estados, sql_recompra_categoria]
    )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {
            "comparacion_recurrentes_vs_no": comparacion,
            "top_10_categorias_recurrentes": top_categorias,
            "top_10_estados_recurrentes": top_estados,
            "tasa_recompra_por_categoria": recompra_categoria,
        },
        "parametros": {"min_clientes_categoria": min_clientes_categoria},
        "sql": sql_total,
        "notas": (
            "Pedido válido = order_status NOT IN ('canceled','unavailable'). "
            "Cliente recurrente = customer_unique_id con más de 1 pedido válido "
            "(distinct order_id). Gasto total del cliente = suma de "
            "order_payments.payment_value de sus pedidos válidos (no order_items.price, "
            "para incluir flete y descuentos/vouchers tal como se cobraron). "
            "Calificación del primer pedido = promedio de order_reviews del pedido "
            "válido con la fecha de compra más antigua del cliente (desempate por "
            "order_id). 'Top categorías/estados de recurrentes' cuenta clientes "
            "distintos que compraron ahí (un cliente puede aparecer en varias "
            "categorías/estados). Tasa de recompra por categoría = % de los clientes "
            "que alguna vez compraron en esa categoría que son recurrentes en TODO su "
            "historial (no solo dentro de la categoría); se filtra con HAVING "
            "clientes >= min_clientes_categoria para evitar categorías con pocos datos."
        ),
    }


# ---------------------------------------------------------------------------
# 2. Retraso vs reseñas
# ---------------------------------------------------------------------------


def q02() -> dict:
    pregunta = (
        "¿A partir de cuántos días de retraso en la entrega cae notablemente la "
        "calificación de los pedidos?"
    )
    conn = _conn()
    try:
        sql = f"""
        WITH {ENTREGAS_CTE},
        {REVIEW_PEDIDO_CTE},
        entregas_con_resena AS (
            SELECT e.order_id, e.dias_retraso, e.entrega_tardia, rp.review_score_promedio
            FROM entregas e
            JOIN review_pedido rp ON rp.order_id = e.order_id
        ),
        rangos AS (
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
                review_score_promedio
            FROM entregas_con_resena
        )
        SELECT
            rango_retraso,
            orden,
            COUNT(*) AS pedidos,
            ROUND(AVG(review_score_promedio), 2) AS calificacion_promedio,
            ROUND(100.0 * SUM(CASE WHEN review_score_promedio <= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_1_2_estrellas
        FROM rangos
        GROUP BY rango_retraso, orden
        ORDER BY orden
        """
        tabla = _run(conn, sql)
    finally:
        conn.close()

    tabla = tabla.sort_values("orden").reset_index(drop=True)
    base = tabla.loc[tabla["rango_retraso"] == "a_tiempo", "pct_1_2_estrellas"]
    pct_base = float(base.iloc[0]) if not base.empty else 0.0

    quiebre = None
    for _, row in tabla.iterrows():
        if row["rango_retraso"] == "a_tiempo":
            continue
        if pct_base > 0 and row["pct_1_2_estrellas"] >= 2 * pct_base:
            quiebre = row
            break

    if quiebre is not None:
        respuesta_clave = (
            f"A partir del rango de retraso '{quiebre['rango_retraso']}' días el % de "
            f"reseñas de 1-2 estrellas ({quiebre['pct_1_2_estrellas']:.1f}%) es al menos "
            f"el doble que en las entregas a tiempo ({pct_base:.1f}%). Calificación "
            f"promedio en ese rango: {quiebre['calificacion_promedio']:.2f}/5 vs "
            f"{tabla.loc[tabla['rango_retraso'] == 'a_tiempo', 'calificacion_promedio'].iloc[0]:.2f}/5 a tiempo."
        )
    else:
        respuesta_clave = (
            "En ningún rango de retraso el % de reseñas de 1-2 estrellas llegó a "
            f"duplicar el de las entregas a tiempo ({pct_base:.1f}%)."
        )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {"retraso_vs_calificacion": tabla},
        "parametros": {},
        "sql": sql,
        "notas": (
            "Solo pedidos ENTREGADOS (order_delivered_customer_date IS NOT NULL) que "
            "tienen al menos una reseña en order_reviews, y que no están "
            "'canceled'/'unavailable' (por seguridad; en la práctica un pedido con "
            "fecha de entrega real casi nunca tiene esos estatus). "
            "dias_retraso = julianday(entrega_real) - julianday(entrega_estimada); "
            "<=0 es 'a_tiempo' (llegó en fecha o antes). Rangos en cascada sin huecos: "
            "a_tiempo, 1-3, 4-7, 8-14, 15+. Criterio de 'quiebre' (definido para esta "
            "respuesta_clave, no es un estándar de la industria): el primer rango, en "
            "orden creciente de retraso, cuyo % de reseñas de 1-2 estrellas es >= 2x "
            "el de 'a_tiempo'."
        ),
    }


# ---------------------------------------------------------------------------
# 3. Concentración
# ---------------------------------------------------------------------------


def q03(top_n_categorias: int = 5, top_m_vendedores: int = 10) -> dict:
    pregunta = (
        "¿Qué tan concentrados están los ingresos en pocas categorías y pocos "
        "vendedores?"
    )
    conn = _conn()
    try:
        sql_categorias = f"""
        WITH {VENTAS_VALIDAS_CTE},
        por_categoria AS (
            SELECT categoria, ROUND(SUM(price), 2) AS ingresos
            FROM ventas_validas
            GROUP BY categoria
        )
        SELECT
            categoria,
            ingresos,
            ROUND(100.0 * ingresos / SUM(ingresos) OVER (), 2) AS pct_ingresos,
            ROUND(100.0 * SUM(ingresos) OVER (ORDER BY ingresos DESC
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                  / SUM(ingresos) OVER (), 2) AS pct_acumulado,
            ROW_NUMBER() OVER (ORDER BY ingresos DESC) AS rango
        FROM por_categoria
        ORDER BY ingresos DESC
        """
        categorias = _run(conn, sql_categorias)

        sql_vendedores = f"""
        WITH {VENTAS_VALIDAS_CTE},
        por_vendedor AS (
            SELECT seller_id, seller_state, ROUND(SUM(price), 2) AS ingresos
            FROM ventas_validas
            GROUP BY seller_id, seller_state
        )
        SELECT
            seller_id,
            seller_state,
            ingresos,
            ROUND(100.0 * ingresos / SUM(ingresos) OVER (), 2) AS pct_ingresos,
            ROUND(100.0 * SUM(ingresos) OVER (ORDER BY ingresos DESC
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                  / SUM(ingresos) OVER (), 2) AS pct_acumulado,
            ROW_NUMBER() OVER (ORDER BY ingresos DESC) AS rango
        FROM por_vendedor
        ORDER BY ingresos DESC
        """
        vendedores = _run(conn, sql_vendedores)
    finally:
        conn.close()

    pct_top_categorias = float(
        categorias.loc[categorias["rango"] == top_n_categorias, "pct_acumulado"].iloc[0]
    ) if (categorias["rango"] == top_n_categorias).any() else float(categorias["pct_acumulado"].iloc[-1])

    pct_top_vendedores = float(
        vendedores.loc[vendedores["rango"] == top_m_vendedores, "pct_acumulado"].iloc[0]
    ) if (vendedores["rango"] == top_m_vendedores).any() else float(vendedores["pct_acumulado"].iloc[-1])

    respuesta_clave = (
        f"Las top {top_n_categorias} categorías concentran el {pct_top_categorias:.1f}% "
        f"de los ingresos (de {len(categorias)} categorías en total). Los top "
        f"{top_m_vendedores} vendedores concentran el {pct_top_vendedores:.1f}% de los "
        f"ingresos (de {len(vendedores)} vendedores en total)."
    )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {
            "pareto_categorias": categorias,
            "pareto_vendedores": vendedores,
        },
        "parametros": {"top_n_categorias": top_n_categorias, "top_m_vendedores": top_m_vendedores},
        "sql": "\n\n".join([sql_categorias, sql_vendedores]),
        "notas": (
            "Ingresos = SUM(order_items.price) de pedidos válidos (excluye flete). "
            "pct_acumulado es la curva de Pareto: % de ingresos acumulado ordenando "
            "de mayor a menor ingreso, fila por fila. rango = posición en ese orden "
            "(1 = mayor ingreso)."
        ),
    }


# ---------------------------------------------------------------------------
# 4. Vendedores problemáticos
# ---------------------------------------------------------------------------


def q04(
    min_pedidos: int = 30,
    umbral_calificacion: float = 3.5,
    umbral_pct_tardias: float = 15.0,
    percentil_ingresos_top: float = 0.25,
) -> dict:
    pregunta = (
        "¿Qué vendedores generan mucho ingreso pero tienen mala calificación o "
        "muchas entregas tardías (candidatos a revisión)?"
    )
    conn = _conn()
    try:
        sql = f"""
        WITH {REVIEW_PEDIDO_CTE},
        pedidos_vendedor AS (
            -- TODOS los estatus: se necesita para poder calcular % de cancelados.
            SELECT DISTINCT oi.seller_id, o.order_id, o.order_status
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
        ),
        resumen_pedidos AS (
            SELECT
                seller_id,
                COUNT(DISTINCT order_id) AS pedidos_totales,
                ROUND(100.0 * SUM(CASE WHEN order_status = 'canceled' THEN 1 ELSE 0 END)
                      / COUNT(DISTINCT order_id), 2) AS pct_cancelados
            FROM pedidos_vendedor
            GROUP BY seller_id
            HAVING COUNT(DISTINCT order_id) >= ?
        ),
        ingresos_vendedor AS (
            SELECT oi.seller_id, SUM(oi.price) AS ingresos
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            WHERE o.order_status NOT IN ('canceled', 'unavailable')
            GROUP BY oi.seller_id
        ),
        entregas_vendedor_raw AS (
            SELECT DISTINCT oi.seller_id, o.order_id,
                   CASE WHEN julianday(o.order_delivered_customer_date) > julianday(o.order_estimated_delivery_date)
                        THEN 1 ELSE 0 END AS entrega_tardia
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            WHERE o.order_delivered_customer_date IS NOT NULL
              AND o.order_status NOT IN ('canceled', 'unavailable')
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
            WHERE o.order_status NOT IN ('canceled', 'unavailable')
        ),
        calificacion_vendedor AS (
            SELECT seller_id, ROUND(AVG(review_score_promedio), 2) AS calificacion_promedio
            FROM calificacion_vendedor_raw
            GROUP BY seller_id
        )
        SELECT
            rp.seller_id AS seller_id,
            rp.pedidos_totales,
            ROUND(COALESCE(iv.ingresos, 0), 2) AS ingresos,
            cv.calificacion_promedio,
            ev.pct_entregas_tardias,
            rp.pct_cancelados,
            PERCENT_RANK() OVER (ORDER BY COALESCE(iv.ingresos, 0) DESC) AS percentil_ingresos_desc
        FROM resumen_pedidos rp
        LEFT JOIN ingresos_vendedor iv ON iv.seller_id = rp.seller_id
        LEFT JOIN entregas_vendedor ev ON ev.seller_id = rp.seller_id
        LEFT JOIN calificacion_vendedor cv ON cv.seller_id = rp.seller_id
        ORDER BY ingresos DESC
        """
        tabla = _run(conn, sql, (min_pedidos,))
    finally:
        conn.close()

    tabla["top_25pct_ingresos"] = tabla["percentil_ingresos_desc"] <= percentil_ingresos_top
    tabla["vendedor_a_revisar"] = tabla["top_25pct_ingresos"] & (
        (tabla["calificacion_promedio"] < umbral_calificacion)
        | (tabla["pct_entregas_tardias"] > umbral_pct_tardias)
    )

    revisar = tabla[tabla["vendedor_a_revisar"]].sort_values("ingresos", ascending=False)
    n_revisar = len(revisar)
    ingresos_revisar = float(revisar["ingresos"].sum())

    respuesta_clave = (
        f"{n_revisar} vendedores (de {len(tabla)} con >= {min_pedidos} pedidos) están "
        f"en el {percentil_ingresos_top * 100:.0f}% superior de ingresos y tienen "
        f"calificación < {umbral_calificacion} o % de entregas tardías > "
        f"{umbral_pct_tardias:.0f}%. Ingresos combinados en riesgo: "
        f"{_money(ingresos_revisar)}."
    )
    if n_revisar:
        top3 = revisar.head(3)
        respuesta_clave += " Top 3 a revisar: " + ", ".join(
            f"{r.seller_id[:8]}… ({_money(r.ingresos)}, calif. {r.calificacion_promedio:.2f}, "
            f"{r.pct_entregas_tardias:.1f}% tardías)"
            for r in top3.itertuples()
        )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {"vendedores": tabla, "vendedores_a_revisar": revisar},
        "parametros": {
            "min_pedidos": min_pedidos,
            "umbral_calificacion": umbral_calificacion,
            "umbral_pct_tardias": umbral_pct_tardias,
            "percentil_ingresos_top": percentil_ingresos_top,
        },
        "sql": sql,
        "notas": (
            "pedidos_totales cuenta TODOS los estatus (necesario para % de cancelados); "
            "ingresos, calificación y % de entregas tardías se calculan solo sobre "
            "pedidos válidos (NOT IN canceled/unavailable). 'Pedido del vendedor' = "
            "pedido que tiene al menos un item vendido por ese seller_id; un mismo "
            "pedido puede contarse para varios vendedores si tuvo items de varios. "
            "top_25pct_ingresos se aproxima con PERCENT_RANK() sobre ingresos "
            "descendente <= percentil_ingresos_top (0 = el de mayor ingreso). "
            "vendedor_a_revisar = está en ese percentil superior Y (calificación < "
            "umbral_calificacion O % tardías > umbral_pct_tardias)."
        ),
    }


# ---------------------------------------------------------------------------
# 5. Flete
# ---------------------------------------------------------------------------


def q05(min_ingresos_categoria: float = 5000.0) -> dict:
    pregunta = "¿En qué estados y categorías el flete pesa más sobre el precio pagado?"
    conn = _conn()
    try:
        sql_estados = f"""
        WITH {VENTAS_VALIDAS_CTE}
        SELECT
            customer_state,
            ROUND(SUM(price), 2) AS ingresos,
            ROUND(SUM(freight_value), 2) AS flete_total,
            ROUND(100.0 * SUM(freight_value) / NULLIF(SUM(price), 0), 2) AS pct_flete_sobre_precio
        FROM ventas_validas
        GROUP BY customer_state
        ORDER BY pct_flete_sobre_precio DESC
        """
        estados = _run(conn, sql_estados)

        sql_categorias = f"""
        WITH {VENTAS_VALIDAS_CTE}
        SELECT
            categoria,
            ROUND(SUM(price), 2) AS ingresos,
            ROUND(SUM(freight_value), 2) AS flete_total,
            ROUND(100.0 * SUM(freight_value) / NULLIF(SUM(price), 0), 2) AS pct_flete_sobre_precio
        FROM ventas_validas
        GROUP BY categoria
        HAVING SUM(price) >= ?
        ORDER BY pct_flete_sobre_precio DESC
        LIMIT 10
        """
        categorias = _run(conn, sql_categorias, (min_ingresos_categoria,))
    finally:
        conn.close()

    peor_estado = estados.iloc[0] if not estados.empty else None
    peor_categoria = categorias.iloc[0] if not categorias.empty else None

    respuesta_clave = ""
    if peor_estado is not None:
        respuesta_clave += (
            f"El estado con mayor peso de flete sobre precio es {peor_estado['customer_state']} "
            f"({peor_estado['pct_flete_sobre_precio']:.1f}%). "
        )
    if peor_categoria is not None:
        respuesta_clave += (
            f"La categoría más afectada (con ingresos >= {_money(min_ingresos_categoria)}) es "
            f"{peor_categoria['categoria']} ({peor_categoria['pct_flete_sobre_precio']:.1f}%)."
        )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {
            "flete_por_estado": estados,
            "top_10_categorias_flete": categorias,
        },
        "parametros": {"min_ingresos_categoria": min_ingresos_categoria},
        "sql": "\n\n".join([sql_estados, sql_categorias]),
        "notas": (
            "pct_flete_sobre_precio = SUM(freight_value)/SUM(price)*100 por grupo "
            "(NUNCA el promedio de la razón fila por fila, que sobre-pondera items "
            "baratos). Estado = customer_state (estado del cliente que recibe el "
            "envío, no del vendedor). Categorías filtradas con HAVING ingresos >= "
            "min_ingresos_categoria para evitar categorías minúsculas con ratios "
            "extremos poco representativos."
        ),
    }


# ---------------------------------------------------------------------------
# 6. Pagos
# ---------------------------------------------------------------------------


def q06(min_pedidos_categoria: int = 100) -> dict:
    pregunta = (
        "¿Cómo pagan los clientes (método, cuotas) y qué categorías se pagan más "
        "a plazos?"
    )
    conn = _conn()
    try:
        sql_tipo = """
        WITH pagos_no_definidos_excluidos AS (
            SELECT * FROM order_payments WHERE payment_type != 'not_defined'
        )
        SELECT
            payment_type,
            COUNT(DISTINCT order_id) AS pedidos,
            ROUND(AVG(valor_tipo), 2) AS ticket_promedio
        FROM (
            SELECT order_id, payment_type, SUM(payment_value) AS valor_tipo
            FROM pagos_no_definidos_excluidos
            GROUP BY order_id, payment_type
        )
        GROUP BY payment_type
        ORDER BY pedidos DESC
        """
        por_tipo = _run(conn, sql_tipo)

        sql_pedido_pagos = """
        pedido_pagos AS (
            SELECT order_id, SUM(payment_value) AS ticket_total, MAX(payment_installments) AS max_cuotas
            FROM order_payments
            WHERE payment_type != 'not_defined'
            GROUP BY order_id
        )"""

        sql_cuotas = f"""
        WITH {sql_pedido_pagos},
        rangos AS (
            SELECT
                ticket_total,
                CASE
                    WHEN max_cuotas <= 1 THEN '1'
                    WHEN max_cuotas <= 3 THEN '2-3'
                    WHEN max_cuotas <= 6 THEN '4-6'
                    WHEN max_cuotas <= 10 THEN '7-10'
                    ELSE '11+'
                END AS rango_cuotas,
                CASE
                    WHEN max_cuotas <= 1 THEN 1
                    WHEN max_cuotas <= 3 THEN 2
                    WHEN max_cuotas <= 6 THEN 3
                    WHEN max_cuotas <= 10 THEN 4
                    ELSE 5
                END AS orden
            FROM pedido_pagos
        )
        SELECT rango_cuotas, orden, COUNT(*) AS pedidos, ROUND(AVG(ticket_total), 2) AS ticket_promedio
        FROM rangos
        GROUP BY rango_cuotas, orden
        ORDER BY orden
        """
        por_rango_cuotas = _run(conn, sql_cuotas)

        sql_categorias_plazos = f"""
        WITH {VENTAS_VALIDAS_CTE},
        {sql_pedido_pagos},
        categoria_pedido AS (
            SELECT DISTINCT categoria, order_id FROM ventas_validas
        )
        SELECT
            cp.categoria,
            COUNT(*) AS pedidos,
            ROUND(100.0 * SUM(CASE WHEN pp.max_cuotas > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_mas_de_1_cuota
        FROM categoria_pedido cp
        JOIN pedido_pagos pp ON pp.order_id = cp.order_id
        GROUP BY cp.categoria
        HAVING COUNT(*) >= ?
        ORDER BY pct_mas_de_1_cuota DESC
        LIMIT 10
        """
        categorias_plazos = _run(conn, sql_categorias_plazos, (min_pedidos_categoria,))
    finally:
        conn.close()

    top_tipo = por_tipo.iloc[0] if not por_tipo.empty else None
    top_categoria_plazos = categorias_plazos.iloc[0] if not categorias_plazos.empty else None

    respuesta_clave = ""
    if top_tipo is not None:
        respuesta_clave += (
            f"El método más usado es {top_tipo['payment_type']} ({top_tipo['pedidos']:,} pedidos, "
            f"ticket promedio {_money(top_tipo['ticket_promedio'])}). "
        )
    if top_categoria_plazos is not None:
        respuesta_clave += (
            f"La categoría con mayor % de pedidos pagados a más de 1 cuota "
            f"(mín. {min_pedidos_categoria} pedidos) es {top_categoria_plazos['categoria']} "
            f"({top_categoria_plazos['pct_mas_de_1_cuota']:.1f}%)."
        )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {
            "por_metodo_pago": por_tipo,
            "ticket_por_rango_cuotas": por_rango_cuotas,
            "categorias_mas_pagadas_a_plazos": categorias_plazos,
        },
        "parametros": {"min_pedidos_categoria": min_pedidos_categoria},
        "sql": "\n\n".join([sql_tipo, f"WITH {sql_pedido_pagos} SELECT * FROM pedido_pagos", sql_cuotas, sql_categorias_plazos]),
        "notas": (
            "Se excluye payment_type = 'not_defined'. Los pagos se agregan primero "
            "por pedido (un pedido puede tener varias filas en order_payments, p.ej. "
            "voucher + tarjeta): ticket por método = suma de payment_value de ESE "
            "método dentro del pedido, promediado entre los pedidos que usaron ese "
            "método. Para el rango de cuotas se usa MAX(payment_installments) del "
            "pedido (si usó varios métodos con distinta cantidad de cuotas, se toma "
            "la mayor). 'Categorías pagadas a plazos' cuenta pedidos DISTINTOS por "
            "categoría (un pedido con items de varias categorías se cuenta en cada "
            "una) con HAVING pedidos >= min_pedidos_categoria."
        ),
    }


# ---------------------------------------------------------------------------
# 7. Estacionalidad
# ---------------------------------------------------------------------------


def q07(pct_umbral_bajo_volumen: float = 0.2) -> dict:
    pregunta = (
        "¿Cómo varían las ventas mes a mes, qué meses son incompletos y cómo "
        "creció el negocio de 2017 a 2018?"
    )
    conn = _conn()
    try:
        sql = f"""
        WITH {VENTAS_VALIDAS_CTE}
        SELECT
            strftime('%Y-%m', order_purchase_timestamp) AS mes,
            COUNT(DISTINCT order_id) AS pedidos,
            ROUND(SUM(price), 2) AS ingresos
        FROM ventas_validas
        GROUP BY mes
        ORDER BY mes
        """
        meses = _run(conn, sql)
    finally:
        conn.close()

    meses = meses.sort_values("mes").reset_index(drop=True)
    mediana_pedidos = meses["pedidos"].median()
    umbral_pedidos = mediana_pedidos * pct_umbral_bajo_volumen

    meses["excluido"] = False
    meses["motivo_exclusion"] = ""
    if len(meses):
        meses.loc[0, "excluido"] = True
        meses.loc[0, "motivo_exclusion"] = "primer mes del dataset"
        meses.loc[len(meses) - 1, "excluido"] = True
        meses.loc[len(meses) - 1, "motivo_exclusion"] = "último mes del dataset"
    bajo_volumen = meses["pedidos"] < umbral_pedidos
    meses.loc[bajo_volumen & ~meses["excluido"], "motivo_exclusion"] = (
        f"volumen < {pct_umbral_bajo_volumen * 100:.0f}% de la mediana mensual"
    )
    meses.loc[bajo_volumen, "excluido"] = True

    comparables = meses[~meses["excluido"]].copy()
    comparables["anio"] = comparables["mes"].str.slice(0, 4)
    comparables["mes_num"] = comparables["mes"].str.slice(5, 7)

    p17 = comparables[comparables["anio"] == "2017"][["mes_num", "ingresos", "pedidos"]].rename(
        columns={"ingresos": "ingresos_2017", "pedidos": "pedidos_2017"}
    )
    p18 = comparables[comparables["anio"] == "2018"][["mes_num", "ingresos", "pedidos"]].rename(
        columns={"ingresos": "ingresos_2018", "pedidos": "pedidos_2018"}
    )
    crecimiento = p17.merge(p18, on="mes_num", how="inner")
    crecimiento["crecimiento_ingresos_pct"] = (
        100.0 * (crecimiento["ingresos_2018"] / crecimiento["ingresos_2017"] - 1)
    ).round(2)
    crecimiento = crecimiento.sort_values("mes_num").reset_index(drop=True)

    mes_pico = comparables.loc[comparables["ingresos"].idxmax()] if not comparables.empty else None
    crecimiento_prom = float(crecimiento["crecimiento_ingresos_pct"].mean()) if not crecimiento.empty else 0.0

    respuesta_clave = (
        f"Excluyendo meses incompletos (primero, último y de volumen anómalo), "
        f"quedan {len(comparables)} meses comparables. "
    )
    if not crecimiento.empty:
        respuesta_clave += (
            f"En los {len(crecimiento)} meses comparables entre 2017 y 2018, el "
            f"crecimiento promedio de ingresos año contra año fue de "
            f"{crecimiento_prom:.1f}%. "
        )
    if mes_pico is not None:
        respuesta_clave += (
            f"El mes pico (entre los comparables) fue {mes_pico['mes']} con "
            f"{_money(mes_pico['ingresos'])} en ingresos."
        )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {
            "ingresos_por_mes": meses,
            "crecimiento_yoy_meses_comparables": crecimiento,
        },
        "parametros": {"pct_umbral_bajo_volumen": pct_umbral_bajo_volumen},
        "sql": sql,
        "notas": (
            "mes = strftime('%Y-%m', order_purchase_timestamp) sobre pedidos válidos. "
            "Un mes se marca 'excluido' si es el primero o el último del dataset "
            "(casi seguro truncados a mitad de mes), o si su número de pedidos es "
            "menor a pct_umbral_bajo_volumen (default 20%) de la MEDIANA mensual de "
            "pedidos de todo el dataset (criterio explícito de esta función, no un "
            "estándar externo). El crecimiento YoY solo compara meses NO excluidos "
            "presentes en ambos años (2017 y 2018)."
        ),
    }


# ---------------------------------------------------------------------------
# 8. Insatisfacción
# ---------------------------------------------------------------------------


def q08(min_resenas: int = 100) -> dict:
    pregunta = (
        "¿Qué categorías tienen más insatisfacción y es por producto (mala "
        "calificación sin ser por retrasos) o por logística (mala calificación "
        "ligada a retrasos)?"
    )
    conn = _conn()
    try:
        sql = f"""
        WITH {VENTAS_VALIDAS_CTE},
        categoria_pedido AS (
            SELECT DISTINCT categoria, order_id FROM ventas_validas
        ),
        resenas_categoria AS (
            SELECT cp.categoria, r.review_score
            FROM categoria_pedido cp
            JOIN order_reviews r ON r.order_id = cp.order_id
        ),
        entregas_categoria AS (
            SELECT
                cp.categoria,
                CASE WHEN julianday(o.order_delivered_customer_date) > julianday(o.order_estimated_delivery_date)
                     THEN 1 ELSE 0 END AS entrega_tardia
            FROM categoria_pedido cp
            JOIN orders o ON o.order_id = cp.order_id
            WHERE o.order_delivered_customer_date IS NOT NULL
        ),
        resumen_categoria AS (
            SELECT
                rc.categoria,
                COUNT(*) AS num_resenas,
                ROUND(AVG(rc.review_score), 2) AS calificacion_promedio,
                ROUND(100.0 * SUM(CASE WHEN rc.review_score = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_1_estrella
            FROM resenas_categoria rc
            GROUP BY rc.categoria
            HAVING COUNT(*) >= ?
        ),
        tardios_categoria AS (
            SELECT categoria, ROUND(100.0 * SUM(entrega_tardia) / COUNT(*), 2) AS pct_tardios
            FROM entregas_categoria
            GROUP BY categoria
        ),
        global AS (
            SELECT
                (SELECT ROUND(AVG(review_score), 4) FROM order_reviews r
                    JOIN orders o ON o.order_id = r.order_id
                    WHERE o.order_status NOT IN ('canceled', 'unavailable')) AS calificacion_global,
                (SELECT ROUND(100.0 * SUM(entrega_tardia) / COUNT(*), 4)
                    FROM (
                        SELECT CASE WHEN julianday(order_delivered_customer_date) > julianday(order_estimated_delivery_date)
                                    THEN 1 ELSE 0 END AS entrega_tardia
                        FROM orders
                        WHERE order_delivered_customer_date IS NOT NULL
                          AND order_status NOT IN ('canceled', 'unavailable')
                    )) AS pct_tardios_global
        )
        SELECT
            rc.categoria,
            rc.num_resenas,
            rc.calificacion_promedio,
            rc.pct_1_estrella,
            tc.pct_tardios,
            g.calificacion_global,
            g.pct_tardios_global
        FROM resumen_categoria rc
        LEFT JOIN tardios_categoria tc ON tc.categoria = rc.categoria
        CROSS JOIN global g
        ORDER BY rc.pct_1_estrella DESC
        """
        tabla = _run(conn, sql, (min_resenas,))
    finally:
        conn.close()

    calificacion_global = float(tabla["calificacion_global"].iloc[0]) if not tabla.empty else 0.0
    pct_tardios_global = float(tabla["pct_tardios_global"].iloc[0]) if not tabla.empty else 0.0

    def _clasificar(row):
        mala_calificacion = row["calificacion_promedio"] < calificacion_global
        if not mala_calificacion:
            return "otro"
        if pd.isna(row["pct_tardios"]):
            return "otro"
        if row["pct_tardios"] < pct_tardios_global:
            return "problema_de_producto"
        return "problema_logistico"

    tabla["clasificacion"] = tabla.apply(_clasificar, axis=1)

    n_producto = int((tabla["clasificacion"] == "problema_de_producto").sum())
    n_logistico = int((tabla["clasificacion"] == "problema_logistico").sum())
    peor = tabla.iloc[0] if not tabla.empty else None

    respuesta_clave = (
        f"De {len(tabla)} categorías con >= {min_resenas} reseñas (calificación global "
        f"promedio {calificacion_global:.2f}/5, {pct_tardios_global:.1f}% de entregas "
        f"tardías global), {n_producto} se clasifican como 'problema de producto' y "
        f"{n_logistico} como 'problema logístico'."
    )
    if peor is not None:
        respuesta_clave += (
            f" La categoría con mayor % de 1 estrella es {peor['categoria']} "
            f"({peor['pct_1_estrella']:.1f}%, clasificada como {peor['clasificacion']})."
        )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {"insatisfaccion_por_categoria": tabla},
        "parametros": {"min_resenas": min_resenas},
        "sql": sql,
        "notas": (
            "Reseñas y % de 1 estrella se toman de order_reviews.review_score "
            "directo (no promediado por pedido), unidas a la categoría vía los "
            "pedidos válidos que contienen esa categoría (un pedido con items de "
            "varias categorías aporta su(s) reseña(s) a cada una). % tardíos usa "
            "solo pedidos entregados de esa categoría. 'Mala calificación' = "
            "calificación promedio de la categoría por debajo del promedio GLOBAL "
            "de todas las reseñas de pedidos válidos. Clasificación: si no hay mala "
            "calificación -> 'otro'; si hay mala calificación y % tardíos de la "
            "categoría < % tardíos global -> 'problema_de_producto' (la insatisfacción "
            "no se explica por retrasos); si es mala calificación y % tardíos > "
            "global -> 'problema_logistico'."
        ),
    }


# ---------------------------------------------------------------------------
# 9. Recompra (clientes de 1 pedido y 5 estrellas)
# ---------------------------------------------------------------------------


def q09() -> dict:
    pregunta = (
        "¿Qué tan grande es la audiencia de clientes satisfechos (5 estrellas) que "
        "solo compraron una vez, y qué compran?"
    )
    conn = _conn()
    try:
        sql_base = f"""
        WITH {PEDIDOS_CLIENTE_CTE},
        {REVIEW_PEDIDO_CTE},
        clientes AS (
            SELECT customer_unique_id, COUNT(DISTINCT order_id) AS num_pedidos
            FROM pedidos_cliente
            GROUP BY customer_unique_id
        ),
        unico_pedido AS (
            SELECT pc.customer_unique_id, pc.order_id
            FROM pedidos_cliente pc
            JOIN clientes cl ON cl.customer_unique_id = pc.customer_unique_id
            WHERE cl.num_pedidos = 1
        ),
        audiencia AS (
            SELECT up.customer_unique_id, up.order_id
            FROM unico_pedido up
            JOIN review_pedido rp ON rp.order_id = up.order_id
            WHERE rp.review_score_promedio = 5
        )
        SELECT customer_unique_id, order_id FROM audiencia
        """
        audiencia = _run(conn, sql_base)

        sql_total_clientes = f"""
        WITH {PEDIDOS_CLIENTE_CTE}
        SELECT COUNT(DISTINCT customer_unique_id) AS total_clientes
        FROM pedidos_cliente
        """
        total_clientes = int(_run(conn, sql_total_clientes)["total_clientes"].iloc[0])

        sql_categorias = f"""
        WITH {PEDIDOS_CLIENTE_CTE},
        {REVIEW_PEDIDO_CTE},
        clientes AS (
            SELECT customer_unique_id, COUNT(DISTINCT order_id) AS num_pedidos
            FROM pedidos_cliente
            GROUP BY customer_unique_id
        ),
        unico_pedido AS (
            SELECT pc.customer_unique_id, pc.order_id
            FROM pedidos_cliente pc
            JOIN clientes cl ON cl.customer_unique_id = pc.customer_unique_id
            WHERE cl.num_pedidos = 1
        ),
        audiencia AS (
            SELECT up.customer_unique_id, up.order_id
            FROM unico_pedido up
            JOIN review_pedido rp ON rp.order_id = up.order_id
            WHERE rp.review_score_promedio = 5
        ),
        {VENTAS_VALIDAS_CTE}
        SELECT
            v.categoria,
            COUNT(DISTINCT v.customer_unique_id) AS clientes
        FROM ventas_validas v
        JOIN audiencia a ON a.order_id = v.order_id
        GROUP BY v.categoria
        ORDER BY clientes DESC
        LIMIT 10
        """
        top_categorias = _run(conn, sql_categorias)

        sql_estados = f"""
        WITH {PEDIDOS_CLIENTE_CTE},
        {REVIEW_PEDIDO_CTE},
        clientes AS (
            SELECT customer_unique_id, COUNT(DISTINCT order_id) AS num_pedidos
            FROM pedidos_cliente
            GROUP BY customer_unique_id
        ),
        unico_pedido AS (
            SELECT pc.customer_unique_id, pc.order_id
            FROM pedidos_cliente pc
            JOIN clientes cl ON cl.customer_unique_id = pc.customer_unique_id
            WHERE cl.num_pedidos = 1
        ),
        audiencia AS (
            SELECT up.customer_unique_id, up.order_id
            FROM unico_pedido up
            JOIN review_pedido rp ON rp.order_id = up.order_id
            WHERE rp.review_score_promedio = 5
        )
        SELECT pc.customer_state, COUNT(DISTINCT a.customer_unique_id) AS clientes
        FROM audiencia a
        JOIN pedidos_cliente pc ON pc.customer_unique_id = a.customer_unique_id
        GROUP BY pc.customer_state
        ORDER BY clientes DESC
        LIMIT 10
        """
        top_estados = _run(conn, sql_estados)
    finally:
        conn.close()

    n_audiencia = audiencia["customer_unique_id"].nunique()
    pct_audiencia = 100.0 * n_audiencia / total_clientes if total_clientes else 0.0

    respuesta_clave = (
        f"{n_audiencia:,} clientes ({pct_audiencia:.1f}% del total de {total_clientes:,}) "
        f"hicieron un único pedido válido y lo calificaron con 5 estrellas. "
        + (
            f"Top categoría: {top_categorias.iloc[0]['categoria']} "
            f"({top_categorias.iloc[0]['clientes']:,} clientes). "
            if not top_categorias.empty
            else ""
        )
        + (
            f"Top estado: {top_estados.iloc[0]['customer_state']} "
            f"({top_estados.iloc[0]['clientes']:,} clientes)."
            if not top_estados.empty
            else ""
        )
    )

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {
            "top_10_categorias_audiencia": top_categorias,
            "top_10_estados_audiencia": top_estados,
        },
        "parametros": {},
        "sql": "\n\n".join([sql_base, sql_total_clientes, sql_categorias, sql_estados]),
        "notas": (
            "Audiencia = customer_unique_id con exactamente 1 pedido válido "
            "(order_status NOT IN canceled/unavailable) y calificación 5 en ese "
            "pedido (promedio de order_reviews del pedido = 5; si el pedido tiene "
            "una sola reseña, es simplemente esa reseña). % del total = audiencia / "
            "clientes con al menos un pedido válido. Top categorías/estados cuentan "
            "clientes DISTINTOS; como el pedido único puede tener items de varias "
            "categorías, un mismo cliente puede aparecer en más de una categoría "
            "(pero solo un estado, el de su dirección)."
        ),
    }


# ---------------------------------------------------------------------------
# 10. Oportunidad geográfica
# ---------------------------------------------------------------------------


def q10() -> dict:
    pregunta = (
        "¿En qué estados hay más clientes por vendedor activo (oportunidad de "
        "expandir la base de vendedores) y cómo es la logística ahí?"
    )
    conn = _conn()
    try:
        sql = f"""
        WITH {VENTAS_VALIDAS_CTE},
        clientes_estado AS (
            SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS clientes
            FROM ventas_validas
            GROUP BY customer_state
        ),
        vendedores_estado AS (
            SELECT seller_state, COUNT(DISTINCT seller_id) AS vendedores
            FROM ventas_validas
            WHERE seller_state IS NOT NULL
            GROUP BY seller_state
        ),
        items_otro_estado AS (
            SELECT
                customer_state,
                COUNT(*) AS items_totales,
                SUM(CASE WHEN seller_state IS NOT NULL AND seller_state != customer_state THEN 1 ELSE 0 END) AS items_otro_estado
            FROM ventas_validas
            GROUP BY customer_state
        ),
        entrega_estado AS (
            SELECT
                c.customer_state,
                ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS dias_promedio_entrega
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            WHERE o.order_delivered_customer_date IS NOT NULL
              AND o.order_status NOT IN ('canceled', 'unavailable')
            GROUP BY c.customer_state
        ),
        flete_pedido AS (
            SELECT customer_state, order_id, SUM(freight_value) AS flete_pedido
            FROM ventas_validas
            GROUP BY customer_state, order_id
        ),
        flete_estado AS (
            SELECT customer_state, ROUND(AVG(flete_pedido), 2) AS flete_promedio
            FROM flete_pedido
            GROUP BY customer_state
        )
        SELECT
            ce.customer_state AS estado,
            ce.clientes,
            COALESCE(ve.vendedores, 0) AS vendedores,
            ROUND(1.0 * ce.clientes / NULLIF(ve.vendedores, 0), 2) AS clientes_por_vendedor,
            ROUND(100.0 * io.items_otro_estado / io.items_totales, 2) AS pct_items_otro_estado,
            ee.dias_promedio_entrega,
            fe.flete_promedio
        FROM clientes_estado ce
        LEFT JOIN vendedores_estado ve ON ve.seller_state = ce.customer_state
        LEFT JOIN items_otro_estado io ON io.customer_state = ce.customer_state
        LEFT JOIN entrega_estado ee ON ee.customer_state = ce.customer_state
        LEFT JOIN flete_estado fe ON fe.customer_state = ce.customer_state
        ORDER BY clientes_por_vendedor DESC
        """
        tabla = _run(conn, sql)
    finally:
        conn.close()

    con_vendedores = tabla[tabla["vendedores"] > 0].sort_values(
        "clientes_por_vendedor", ascending=False
    )
    top3 = con_vendedores.head(3)

    respuesta_clave = "Los 3 estados con más clientes por vendedor son " + ", ".join(
        f"{r.estado} ({r.clientes_por_vendedor:.1f} clientes/vendedor, "
        f"{r.clientes:,} clientes, {r.vendedores:,} vendedores)"
        for r in top3.itertuples()
    ) + "."

    return {
        "pregunta": pregunta,
        "respuesta_clave": respuesta_clave,
        "tablas": {"oportunidad_por_estado": tabla},
        "parametros": {},
        "sql": sql,
        "notas": (
            "clientes = customer_unique_id distintos con pedidos válidos con destino "
            "a ese estado (customer_state). vendedores = seller_id distintos con al "
            "menos una venta válida (item de order_items) desde ese estado "
            "(seller_state); estados sin vendedores activos quedan con "
            "clientes_por_vendedor nulo (división entre 0) y se excluyen del ranking "
            "de la respuesta_clave. pct_items_otro_estado = % de líneas de "
            "order_items (de pedidos válidos) de clientes de ese estado cuyo "
            "vendedor está en OTRO estado. dias_promedio_entrega = promedio de "
            "(entrega real - compra) en días, solo pedidos entregados. "
            "flete_promedio = promedio del flete TOTAL por pedido (sumado entre "
            "líneas del mismo pedido primero), no por línea."
        ),
    }
