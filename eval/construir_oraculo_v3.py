"""
Construye el oráculo v3 (Etapa 2, Paso 2): 30 preguntas de negocio sobre Olist,
cada una resoluble con UNA consulta, divididas en DESARROLLO (20) y PRUEBA (10).

- Las 10 necesidades del dashboard (v2) van todas a DESARROLLO; la necesidad 4
  recupera su criterio completo (D-20).
- Las 20 preguntas nuevas se reparten 10/10 entre DESARROLLO y PRUEBA con un
  sorteo de semilla fija (SEMILLA_SPLIT), no a mano.
- `resultado_esperado` se obtiene EJECUTANDO cada SQL de referencia (solo
  lectura); `dashboard/verify_pandas.py` lo cruza con pandas (30/30).
- Para los rankings, `chequeo_empates` comprueba que el 1.er puesto no empata
  ni queda a centésimas del 2.º.

Uso:
    python -m eval.construir_oraculo_v3 --explorar   # solo imprime resultados y chequeos
    python -m eval.construir_oraculo_v3              # escribe ground_truth_olist.json (v3) y el split
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SEMILLA_SPLIT = 20261011
V = "o.order_status NOT IN ('canceled','unavailable')"
VALIDOS = "(sin contar pedidos cancelados o no disponibles)"

# Necesidad 4 con el criterio completo del dashboard (una sola consulta, D-20).
N04_COMPLETA = dict(
    pregunta=("Entre los vendedores con al menos 30 pedidos válidos " + VALIDOS + ", ¿cuántos están en el 25 % con más "
              "ingresos y además tienen una calificación promedio menor a 3.5 (promediando la calificación de cada pedido) "
              "o más del 15 % de sus pedidos entregados con retraso respecto de la fecha estimada?"),
    sql=(f"WITH ped AS (SELECT DISTINCT oi.seller_id, o.order_id, o.order_delivered_customer_date AS entregado, "
         f"o.order_estimated_delivery_date AS estimado FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V}), "
         f"ing AS (SELECT oi.seller_id, SUM(oi.price) AS ingresos FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
         f"WHERE {V} GROUP BY oi.seller_id), "
         "rev AS (SELECT order_id, AVG(review_score) AS calif FROM order_reviews GROUP BY order_id), "
         "vend AS (SELECT ped.seller_id, COUNT(*) AS pedidos, AVG(rev.calif) AS calif, "
         "100.0 * SUM(CASE WHEN ped.entregado IS NOT NULL AND julianday(ped.entregado) > julianday(ped.estimado) THEN 1 ELSE 0 END) "
         "/ NULLIF(SUM(CASE WHEN ped.entregado IS NOT NULL THEN 1 ELSE 0 END), 0) AS pct_tardias "
         "FROM ped LEFT JOIN rev ON rev.order_id = ped.order_id GROUP BY ped.seller_id), "
         "elegibles AS (SELECT v.seller_id, v.calif, v.pct_tardias, CUME_DIST() OVER (ORDER BY i.ingresos DESC) AS cd "
         "FROM vend v JOIN ing i ON i.seller_id = v.seller_id WHERE v.pedidos >= 30) "
         "SELECT COUNT(*) AS vendedores FROM elegibles WHERE cd <= 0.25 AND (calif < 3.5 OR pct_tardias > 15)"),
    tipos=["conteo"], orden=False,
)

# 20 preguntas nuevas: (id, dificultad, pregunta, sql, tipos, orden, sql_chequeo_empates|None)
NUEVAS = [
    ("x01_pedidos_cancelados", "conteo",
     "¿Cuántos pedidos tienen el estatus cancelado (canceled)?",
     "SELECT COUNT(*) AS pedidos FROM orders WHERE order_status = 'canceled'", ["conteo"], False, None),
    ("x02_pct_entregas_con_retraso", "porcentaje",
     f"De los pedidos válidos {VALIDOS} que ya fueron entregados al cliente, ¿qué porcentaje llegó después de la fecha estimada de entrega?",
     f"SELECT ROUND(100.0 * SUM(CASE WHEN julianday(o.order_delivered_customer_date) > julianday(o.order_estimated_delivery_date) THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct FROM orders o WHERE {V} AND o.order_delivered_customer_date IS NOT NULL",
     ["porcentaje"], False, None),
    ("x03_flete_promedio_por_articulo", "promedio",
     f"¿Cuál es el valor promedio del flete por artículo vendido en pedidos válidos {VALIDOS}?",
     f"SELECT ROUND(AVG(oi.freight_value), 2) AS flete_promedio FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V}",
     ["dinero"], False, None),
    ("x04_pct_resenas_5_estrellas", "porcentaje",
     "¿Qué porcentaje de todas las reseñas tiene una calificación de 5 estrellas?",
     "SELECT ROUND(100.0 * SUM(CASE WHEN review_score = 5 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct FROM order_reviews",
     ["porcentaje"], False, None),
    ("x05_vendedor_mas_ingresos", "ranking",
     f"¿Qué vendedor (seller_id) generó más ingresos (suma de price) en pedidos válidos {VALIDOS} y cuánto suman?",
     f"SELECT oi.seller_id, ROUND(SUM(oi.price), 2) AS ingresos FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V} GROUP BY oi.seller_id ORDER BY ingresos DESC LIMIT 1",
     ["texto", "dinero"], False,
     f"SELECT oi.seller_id, ROUND(SUM(oi.price), 2) AS v FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V} GROUP BY oi.seller_id ORDER BY v DESC LIMIT 3"),
    ("x06_pct_pedidos_varios_articulos", "porcentaje",
     f"¿Qué porcentaje de los pedidos válidos {VALIDOS} tiene más de un artículo?",
     f"WITH n AS (SELECT oi.order_id, COUNT(*) AS articulos FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V} GROUP BY oi.order_id) SELECT ROUND(100.0 * SUM(CASE WHEN articulos > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct FROM n",
     ["porcentaje"], False, None),
    ("x07_calificacion_pedidos_bed_bath_table", "joins",
     f"¿Cuál es la calificación promedio (promediando la de cada pedido) de los pedidos válidos {VALIDOS} que contienen al menos un producto de la categoría bed_bath_table?",
     f"WITH ped AS (SELECT DISTINCT oi.order_id FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id JOIN product_category_translation t ON t.product_category_name = p.product_category_name WHERE {V} AND t.product_category_name_english = 'bed_bath_table'), rev AS (SELECT order_id, AVG(review_score) AS calif FROM order_reviews GROUP BY order_id) SELECT ROUND(AVG(rev.calif), 2) AS calificacion FROM ped JOIN rev ON rev.order_id = ped.order_id",
     ["decimal"], False, None),
    ("x08_dias_entrega_rj", "promedio",
     f"¿Cuántos días tarda en promedio, desde la compra hasta la entrega al cliente, un pedido válido {VALIDOS} entregado a clientes del estado RJ?",
     f"SELECT ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS dias FROM orders o JOIN customers c ON c.customer_id = o.customer_id WHERE {V} AND o.order_delivered_customer_date IS NOT NULL AND c.customer_state = 'RJ'",
     ["decimal"], False, None),
    ("x09_mes_mas_cancelados", "ranking",
     "¿En qué mes (formato AAAA-MM, según la fecha de compra) hubo más pedidos con estatus cancelado y cuántos fueron?",
     "SELECT strftime('%Y-%m', order_purchase_timestamp) AS mes, COUNT(*) AS cancelados FROM orders WHERE order_status = 'canceled' GROUP BY mes ORDER BY cancelados DESC LIMIT 1",
     ["texto", "conteo"], False,
     "SELECT strftime('%Y-%m', order_purchase_timestamp) AS mes, COUNT(*) AS v FROM orders WHERE order_status = 'canceled' GROUP BY mes ORDER BY v DESC LIMIT 3"),
    ("x10_categoria_precio_promedio_mas_alto", "ranking",
     f"Entre las categorías de producto (en inglés) con al menos 200 artículos vendidos en pedidos válidos {VALIDOS}, ¿cuál tiene el precio promedio por artículo más alto y cuál es ese precio?",
     f"SELECT t.product_category_name_english AS categoria, ROUND(AVG(oi.price), 2) AS precio_promedio FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id JOIN product_category_translation t ON t.product_category_name = p.product_category_name WHERE {V} GROUP BY t.product_category_name_english HAVING COUNT(*) >= 200 ORDER BY precio_promedio DESC LIMIT 1",
     ["texto", "dinero"], False,
     f"SELECT t.product_category_name_english, ROUND(AVG(oi.price), 2) AS v FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id JOIN product_category_translation t ON t.product_category_name = p.product_category_name WHERE {V} GROUP BY t.product_category_name_english HAVING COUNT(*) >= 200 ORDER BY v DESC LIMIT 3"),
    ("x11_clientes_unicos_sp", "conteo",
     f"¿Cuántos clientes únicos del estado SP hicieron al menos un pedido válido {VALIDOS}?",
     f"SELECT COUNT(DISTINCT c.customer_unique_id) AS clientes FROM customers c JOIN orders o ON o.customer_id = c.customer_id WHERE {V} AND c.customer_state = 'SP'",
     ["conteo"], False, None),
    ("x12_vendedores_health_beauty", "joins",
     f"¿Cuántos vendedores distintos vendieron al menos un producto de la categoría health_beauty en pedidos válidos {VALIDOS}?",
     f"SELECT COUNT(DISTINCT oi.seller_id) AS vendedores FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id JOIN product_category_translation t ON t.product_category_name = p.product_category_name WHERE {V} AND t.product_category_name_english = 'health_beauty'",
     ["conteo"], False, None),
    ("x13_estado_mayor_gasto_promedio", "ranking",
     f"Entre los estados de cliente con al menos 1000 pedidos válidos {VALIDOS}, ¿cuál tiene el mayor gasto promedio por pedido (precio más flete) y cuál es ese promedio?",
     f"WITH ped AS (SELECT c.customer_state, oi.order_id, SUM(oi.price + oi.freight_value) AS total FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN customers c ON c.customer_id = o.customer_id WHERE {V} GROUP BY c.customer_state, oi.order_id) SELECT customer_state, ROUND(AVG(total), 2) AS gasto_promedio FROM ped GROUP BY customer_state HAVING COUNT(*) >= 1000 ORDER BY gasto_promedio DESC LIMIT 1",
     ["texto", "dinero"], False,
     f"WITH ped AS (SELECT c.customer_state, oi.order_id, SUM(oi.price + oi.freight_value) AS total FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN customers c ON c.customer_id = o.customer_id WHERE {V} GROUP BY c.customer_state, oi.order_id) SELECT customer_state, ROUND(AVG(total), 2) AS v FROM ped GROUP BY customer_state HAVING COUNT(*) >= 1000 ORDER BY v DESC LIMIT 3"),
    ("x14_ingresos_vendedores_sp_fuera_sp", "joins",
     f"¿Cuántos ingresos (suma de price) generaron, en pedidos válidos {VALIDOS}, los vendedores del estado SP con clientes de otros estados?",
     f"SELECT ROUND(SUM(oi.price), 2) AS ingresos FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN customers c ON c.customer_id = o.customer_id JOIN sellers s ON s.seller_id = oi.seller_id WHERE {V} AND s.seller_state = 'SP' AND c.customer_state <> 'SP'",
     ["dinero"], False, None),
    ("x15_calificacion_pedidos_boleto", "joins",
     f"¿Cuál es la calificación promedio de las reseñas de los pedidos válidos {VALIDOS} que se pagaron, al menos en parte, con boleto?",
     f"SELECT ROUND(AVG(r.review_score), 2) AS calificacion FROM order_reviews r WHERE r.order_id IN (SELECT op.order_id FROM order_payments op JOIN orders o ON o.order_id = op.order_id WHERE {V} AND op.payment_type = 'boleto')",
     ["decimal"], False, None),
    ("x16_pct_productos_sin_categoria", "porcentaje",
     "¿Qué porcentaje de los productos del catálogo no tiene una categoría asignada?",
     "SELECT ROUND(100.0 * SUM(CASE WHEN product_category_name IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct FROM products",
     ["porcentaje"], False, None),
    ("x17_top2_ciudades_vendedores", "ranking",
     f"¿Cuáles son las 2 ciudades de vendedores con más pedidos válidos {VALIDOS}, de mayor a menor?",
     f"SELECT s.seller_city, COUNT(DISTINCT oi.order_id) AS pedidos FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN sellers s ON s.seller_id = oi.seller_id WHERE {V} GROUP BY s.seller_city ORDER BY pedidos DESC LIMIT 2",
     ["texto", None], True,
     f"SELECT s.seller_city, COUNT(DISTINCT oi.order_id) AS v FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN sellers s ON s.seller_id = oi.seller_id WHERE {V} GROUP BY s.seller_city ORDER BY v DESC LIMIT 3"),
    ("x18_peso_promedio_furniture_decor", "joins",
     f"¿Cuál es el peso promedio, en gramos, de los artículos vendidos en pedidos válidos {VALIDOS} de la categoría furniture_decor?",
     f"SELECT ROUND(AVG(p.product_weight_g), 2) AS peso FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id JOIN product_category_translation t ON t.product_category_name = p.product_category_name WHERE {V} AND t.product_category_name_english = 'furniture_decor'",
     ["decimal"], False, None),
    ("x19_anio_mas_ingresos", "ranking",
     f"¿Qué año (según la fecha de compra) tuvo más ingresos por ventas (suma de price) en pedidos válidos {VALIDOS} y cuánto sumaron?",
     f"SELECT strftime('%Y', o.order_purchase_timestamp) AS anio, ROUND(SUM(oi.price), 2) AS ingresos FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V} GROUP BY anio ORDER BY ingresos DESC LIMIT 1",
     ["texto", "dinero"], False,
     f"SELECT strftime('%Y', o.order_purchase_timestamp) AS anio, ROUND(SUM(oi.price), 2) AS v FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V} GROUP BY anio ORDER BY v DESC LIMIT 3"),
    ("x20_pct_clientes_resena_1_estrella", "porcentaje",
     f"De los clientes únicos con al menos un pedido válido {VALIDOS}, ¿qué porcentaje dejó al menos una reseña de 1 estrella en esos pedidos?",
     f"WITH cli AS (SELECT DISTINCT c.customer_unique_id, o.order_id FROM customers c JOIN orders o ON o.customer_id = c.customer_id WHERE {V}) SELECT ROUND(100.0 * COUNT(DISTINCT CASE WHEN r.review_score = 1 THEN cli.customer_unique_id END) / COUNT(DISTINCT cli.customer_unique_id), 2) AS pct FROM cli LEFT JOIN order_reviews r ON r.order_id = cli.order_id",
     ["porcentaje"], False, None),
]


def _conn():
    return sqlite3.connect(f"file:{(RAIZ / 'db' / 'olist.db').resolve()}?mode=ro", uri=True)


def explorar():
    conn = _conn()
    print("n04 (criterio completo):", conn.execute(N04_COMPLETA["sql"]).fetchall())
    for qid, dif, preg, sql, tipos, orden, chequeo in NUEVAS:
        filas = conn.execute(sql).fetchall()
        extra = ""
        if chequeo:
            top = conn.execute(chequeo).fetchall()
            extra = f" | top: {top}"
        print(f"{qid} [{dif}] -> {filas}{extra}")


def construir():
    conn = _conn()
    v2 = json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))
    assert v2.get("version") == 2, "se esperaba el oráculo v2 como punto de partida"
    preguntas = []
    for n in v2["preguntas"]:
        n = dict(n)
        if n["id"] == "n04_vendedores_mala_calificacion":
            n.update(id="n04_vendedores_problematicos", pregunta=N04_COMPLETA["pregunta"], sql_referencia=N04_COMPLETA["sql"],
                     tipos_columnas=N04_COMPLETA["tipos"], orden_importa=N04_COMPLETA["orden"])
        n["dificultad"] = n.get("dificultad", "necesidad")
        n["conjunto"] = "desarrollo"
        preguntas.append(n)
    sorteo = random.Random(SEMILLA_SPLIT)
    ids_nuevas = [q[0] for q in NUEVAS]
    prueba = set(sorteo.sample(ids_nuevas, 10))
    for qid, dif, preg, sql, tipos, orden, chequeo in NUEVAS:
        preguntas.append({"id": qid, "pestana_dashboard": None, "necesidad": None, "pregunta": preg, "sql_referencia": sql,
                          "tipos_columnas": tipos, "orden_importa": orden, "dificultad": dif, "origen_v1": None,
                          "conjunto": "prueba" if qid in prueba else "desarrollo"})
    for p in preguntas:
        p["resultado_esperado"] = [list(f) for f in conn.execute(p["sql_referencia"]).fetchall()]
    datos = {
        "version": 3,
        "descripcion": ("30 preguntas de negocio sobre Olist, cada una resoluble con UNA consulta. Las 10 con "
                        "pestana_dashboard son las necesidades del dueño (alimentan el dashboard). conjunto = "
                        "'desarrollo' (20: las 10 necesidades + 10 nuevas) o 'prueba' (10, held-out: no se usan para "
                        "ajustar nada; solo se evalúan una vez al final). El reparto de las 20 nuevas es un sorteo con "
                        f"semilla {SEMILLA_SPLIT} (eval/construir_oraculo_v3.py). Pedido válido = order_status NOT IN "
                        "('canceled','unavailable'). resultado_esperado se obtuvo ejecutando sql_referencia y se "
                        "verifica con eval/compute_ground_truth.py (SQL) y dashboard/verify_pandas.py (pandas)."),
        "cargado_con": "python seeder/load_olist_csv.py",
        "semilla_split": SEMILLA_SPLIT,
        "preguntas": preguntas,
    }
    (RAIZ / "eval" / "ground_truth_olist.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    split = {"semilla": SEMILLA_SPLIT,
             "desarrollo": [p["id"] for p in preguntas if p["conjunto"] == "desarrollo"],
             "prueba": [p["id"] for p in preguntas if p["conjunto"] == "prueba"]}
    (RAIZ / "eval" / "split_oraculo.json").write_text(json.dumps(split, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"desarrollo: {len(split['desarrollo'])} | prueba: {len(split['prueba'])}")
    print("prueba (ids):", split["prueba"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorar", action="store_true")
    a = ap.parse_args()
    explorar() if a.explorar else construir()
