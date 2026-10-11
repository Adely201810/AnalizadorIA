"""
Construye el oráculo v4 (Etapa 3, Paso 2).

- El conjunto PRUEBA de la v3 ya fue visto (Etapa 2, Paso 5): sus 10 preguntas pasan a
  DESARROLLO. DESARROLLO = 30 (las 20 de antes + las 10 de PRUEBA v3). Se guarda el
  conjunto original en `conjunto_v3`.
- PRUEBA_2: 20 preguntas NUEVAS, escritas en este paso, congeladas y no consultadas
  hasta la evaluación final de la etapa 3. Cada una lleva `tipo`: simple, porcentaje,
  pedido_valido, ranking o varios_pasos.
- `resultado_esperado` se obtiene EJECUTANDO cada SQL de referencia (solo lectura) y
  `dashboard/verify_pandas.py` lo recalcula con pandas desde los CSV, de forma independiente.

Idempotente: si el archivo ya es v4, conserva las preguntas de DESARROLLO tal cual y
regenera PRUEBA_2, así que reconstruirlo da exactamente el mismo archivo.

Uso:
    python -m eval.construir_oraculo_v4 --explorar   # solo imprime resultados y chequeos de empate
    python -m eval.construir_oraculo_v4              # escribe ground_truth_olist.json (v4) y split_oraculo.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
V = "o.order_status NOT IN ('canceled','unavailable')"
VALIDOS = "(sin contar pedidos cancelados o no disponibles)"

# (id, tipo, pregunta, sql_referencia, tipos_columnas, orden_importa, chequeo_empates)
PRUEBA_2 = [
    # --- simples ---
    ("p2_01_vendedores_rio", "simple",
     "¿Cuántos vendedores están registrados en la ciudad de rio de janeiro?",
     "SELECT COUNT(*) FROM sellers WHERE seller_city = 'rio de janeiro'",
     ["conteo"], False, None),
    ("p2_02_pagos_debito", "simple",
     "¿Cuántos pagos se registraron con tarjeta de débito (debit_card)?",
     "SELECT COUNT(*) FROM order_payments WHERE payment_type = 'debit_card'",
     ["conteo"], False, None),
    # (Sustituye a una pregunta sobre cuotas máximas con tarjeta, que chocaba con un few-shot del contexto:
    #  texto 0.364, SQL 0.500.)
    ("p2_03_productos_mas_10kg", "simple",
     "¿Cuántos productos del catálogo pesan más de 10 kilos (más de 10000 gramos)?",
     "SELECT COUNT(*) FROM products WHERE product_weight_g > 10000",
     ["conteo"], False, None),
    ("p2_04_resenas_con_mensaje", "simple",
     "¿Cuántas reseñas tienen un mensaje de comentario registrado (no nulo)?",
     "SELECT COUNT(*) FROM order_reviews WHERE review_comment_message IS NOT NULL",
     ["conteo"], False, None),
    # --- porcentajes con denominador explícito ---
    ("p2_05_pct_entrega_7_dias", "porcentaje",
     f"De los pedidos válidos {VALIDOS} que tienen fecha de entrega al cliente registrada, ¿qué porcentaje se "
     "entregó en 7 días o menos desde la compra?",
     f"SELECT ROUND(100.0 * SUM(CASE WHEN julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp) <= 7 "
     f"THEN 1 ELSE 0 END) / COUNT(*), 2) FROM orders o WHERE {V} AND o.order_delivered_customer_date IS NOT NULL",
     ["porcentaje"], False, None),
    ("p2_06_pct_vendedores_sin_ventas", "porcentaje",
     f"Del total de vendedores registrados, ¿qué porcentaje no tiene ningún artículo vendido en pedidos válidos {VALIDOS}?",
     "SELECT ROUND(100.0 * SUM(CASE WHEN s.seller_id NOT IN (SELECT oi.seller_id FROM order_items oi JOIN orders o "
     f"ON o.order_id = oi.order_id WHERE {V}) THEN 1 ELSE 0 END) / COUNT(*), 2) FROM sellers s",
     ["porcentaje"], False, None),
    ("p2_07_pct_ingresos_vendedores_mg", "porcentaje",
     f"¿Qué porcentaje de los ingresos (suma de price en pedidos válidos {VALIDOS}) generaron los vendedores del estado MG?",
     "SELECT ROUND(100.0 * SUM(CASE WHEN s.seller_state = 'MG' THEN oi.price ELSE 0 END) / SUM(oi.price), 2) "
     f"FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN sellers s ON s.seller_id = oi.seller_id WHERE {V}",
     ["porcentaje"], False, None),
    ("p2_08_pct_resenas_titulo_bajas", "porcentaje",
     "De las reseñas que tienen un título de comentario registrado (no nulo), ¿qué porcentaje tiene una calificación de 1 o 2 estrellas?",
     "SELECT ROUND(100.0 * SUM(CASE WHEN review_score <= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) FROM order_reviews "
     "WHERE review_comment_title IS NOT NULL",
     ["porcentaje"], False, None),
    ("p2_09_pct_articulos_flete_mayor_precio", "porcentaje",
     f"¿Qué porcentaje de los artículos vendidos en pedidos válidos {VALIDOS} tiene un flete mayor que su precio?",
     "SELECT ROUND(100.0 * SUM(CASE WHEN oi.freight_value > oi.price THEN 1 ELSE 0 END) / COUNT(*), 2) "
     f"FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V}",
     ["porcentaje"], False, None),
    # --- filtro de pedido válido ---
    ("p2_10_pedidos_validos_2017", "pedido_valido",
     f"¿Cuántos pedidos válidos {VALIDOS} se compraron durante el año 2017?",
     f"SELECT COUNT(*) FROM orders o WHERE {V} AND strftime('%Y', o.order_purchase_timestamp) = '2017'",
     ["conteo"], False, None),
    ("p2_11_ticket_promedio", "pedido_valido",
     f"¿Cuál es el ticket promedio de los pedidos válidos {VALIDOS}, es decir, el total pagado promedio por pedido "
     "según la suma de sus pagos?",
     "SELECT ROUND(AVG(t), 2) FROM (SELECT o.order_id, SUM(p.payment_value) AS t FROM orders o "
     f"JOIN order_payments p ON p.order_id = o.order_id WHERE {V} GROUP BY o.order_id)",
     ["dinero"], False, None),
    ("p2_12_precio_promedio_nov_2017", "pedido_valido",
     f"¿Cuál es el precio promedio por artículo vendido en los pedidos válidos {VALIDOS} comprados en noviembre de 2017?",
     "SELECT ROUND(AVG(oi.price), 2) FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
     f"WHERE {V} AND strftime('%Y-%m', o.order_purchase_timestamp) = '2017-11'",
     ["dinero"], False, None),
    ("p2_13_articulos_clientes_rs", "pedido_valido",
     f"¿Cuántos artículos se vendieron en pedidos válidos {VALIDOS} de clientes del estado RS?",
     "SELECT COUNT(*) FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
     f"JOIN customers c ON c.customer_id = o.customer_id WHERE {V} AND c.customer_state = 'RS'",
     ["conteo"], False, None),
    # --- rankings ---
    ("p2_14_categoria_mas_articulos", "ranking",
     f"¿Qué categoría de producto (nombre en inglés) tiene más artículos vendidos en pedidos válidos {VALIDOS} y cuántos artículos son?",
     "SELECT COALESCE(t.product_category_name_english, 'sin_categoria') AS categoria, COUNT(*) AS articulos "
     "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id "
     f"LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name WHERE {V} "
     "GROUP BY categoria ORDER BY articulos DESC LIMIT 1",
     ["texto", "conteo"], False,
     "SELECT COALESCE(t.product_category_name_english, 'sin_categoria') AS categoria, COUNT(*) AS articulos "
     "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id "
     f"LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name WHERE {V} "
     "GROUP BY categoria ORDER BY articulos DESC LIMIT 3"),
    ("p2_15_top3_estados_vendedores", "ranking",
     "¿Cuáles son los 3 estados con más vendedores registrados y cuántos vendedores tiene cada uno, de mayor a menor?",
     "SELECT seller_state, COUNT(*) AS vendedores FROM sellers GROUP BY seller_state ORDER BY vendedores DESC LIMIT 3",
     ["texto", "conteo"], True,
     "SELECT seller_state, COUNT(*) AS vendedores FROM sellers GROUP BY seller_state ORDER BY vendedores DESC LIMIT 5"),
    ("p2_16_dia_semana_mas_pedidos", "ranking",
     f"¿Qué día de la semana, como número (0 = domingo, 1 = lunes, …, 6 = sábado) según la fecha de compra, tiene más "
     f"pedidos válidos {VALIDOS} y cuántos son?",
     "SELECT CAST(strftime('%w', o.order_purchase_timestamp) AS INTEGER) AS dia, COUNT(*) AS pedidos FROM orders o "
     f"WHERE {V} GROUP BY dia ORDER BY pedidos DESC LIMIT 1",
     ["conteo", "conteo"], False,
     "SELECT CAST(strftime('%w', o.order_purchase_timestamp) AS INTEGER) AS dia, COUNT(*) AS pedidos FROM orders o "
     f"WHERE {V} GROUP BY dia ORDER BY pedidos DESC LIMIT 3"),
    # --- varios pasos ---
    ("p2_17_gasto_clientes_2_pedidos", "varios_pasos",
     f"Entre los clientes únicos con al menos 2 pedidos válidos {VALIDOS}, ¿cuál es el gasto total promedio por cliente, "
     "sumando los pagos (payment_value) de sus pedidos válidos?",
     f"WITH pc AS (SELECT c.customer_unique_id AS u, o.order_id FROM orders o JOIN customers c ON c.customer_id = o.customer_id WHERE {V}), "
     "n AS (SELECT u FROM pc GROUP BY u HAVING COUNT(DISTINCT order_id) >= 2), "
     "g AS (SELECT pc.u, SUM(COALESCE(p.payment_value, 0)) AS t FROM pc LEFT JOIN order_payments p ON p.order_id = pc.order_id "
     "WHERE pc.u IN (SELECT u FROM n) GROUP BY pc.u) SELECT ROUND(AVG(t), 2) FROM g",
     ["dinero"], False, None),
    ("p2_18_dias_entrega_por_flete", "varios_pasos",
     f"Para los pedidos válidos {VALIDOS} entregados al cliente, ¿cuántos días tarda en promedio la entrega desde la compra "
     "cuando el flete total del pedido supera 50 y cuántos cuando es de 50 o menos?",
     "WITH f AS (SELECT order_id, SUM(freight_value) AS fl FROM order_items GROUP BY order_id), "
     "d AS (SELECT o.order_id, julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp) AS dias "
     f"FROM orders o WHERE {V} AND o.order_delivered_customer_date IS NOT NULL) "
     "SELECT ROUND(AVG(CASE WHEN f.fl > 50 THEN d.dias END), 2) AS mas_de_50, ROUND(AVG(CASE WHEN f.fl <= 50 THEN d.dias END), 2) AS hasta_50 "
     "FROM d JOIN f ON f.order_id = d.order_id",
     ["decimal", "decimal"], False, None),
    ("p2_19_vendedor_mejor_calificado", "varios_pasos",
     f"Entre los vendedores con al menos 50 artículos vendidos en pedidos válidos {VALIDOS}, ¿qué vendedor (seller_id) "
     "tiene la calificación promedio más alta, promediando la calificación de cada pedido, y cuál es esa calificación?",
     f"WITH art AS (SELECT oi.seller_id FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V} "
     "GROUP BY oi.seller_id HAVING COUNT(*) >= 50), "
     "rp AS (SELECT order_id, AVG(review_score) AS s FROM order_reviews GROUP BY order_id), "
     f"sp AS (SELECT DISTINCT oi.seller_id, oi.order_id FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V}) "
     "SELECT sp.seller_id, ROUND(AVG(rp.s), 2) AS calificacion FROM sp JOIN rp ON rp.order_id = sp.order_id "
     "WHERE sp.seller_id IN (SELECT seller_id FROM art) GROUP BY sp.seller_id ORDER BY calificacion DESC LIMIT 1",
     ["texto", "decimal"], False,
     f"WITH art AS (SELECT oi.seller_id FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V} "
     "GROUP BY oi.seller_id HAVING COUNT(*) >= 50), "
     "rp AS (SELECT order_id, AVG(review_score) AS s FROM order_reviews GROUP BY order_id), "
     f"sp AS (SELECT DISTINCT oi.seller_id, oi.order_id FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE {V}) "
     "SELECT sp.seller_id, AVG(rp.s) AS calificacion FROM sp JOIN rp ON rp.order_id = sp.order_id "
     "WHERE sp.seller_id IN (SELECT seller_id FROM art) GROUP BY sp.seller_id ORDER BY calificacion DESC LIMIT 3"),
    ("p2_20_pct_pagado_varios_metodos", "varios_pasos",
     f"¿Qué porcentaje del total pagado (suma de payment_value) en pedidos válidos {VALIDOS} corresponde a pedidos que "
     "se pagaron con más de un método de pago distinto?",
     "WITH pp AS (SELECT p.order_id, SUM(p.payment_value) AS t, COUNT(DISTINCT p.payment_type) AS m FROM order_payments p "
     f"JOIN orders o ON o.order_id = p.order_id WHERE {V} GROUP BY p.order_id) "
     "SELECT ROUND(100.0 * SUM(CASE WHEN m > 1 THEN t ELSE 0 END) / SUM(t), 2) FROM pp",
     ["porcentaje"], False, None),
]


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{RAIZ / 'db' / 'olist.db'}?mode=ro", uri=True)


def explorar():
    conn = _conn()
    for qid, tipo, preg, sql, tipos, orden, chequeo in PRUEBA_2:
        filas = conn.execute(sql).fetchall()
        extra = f" | top: {conn.execute(chequeo).fetchall()}" if chequeo else ""
        print(f"{qid} [{tipo}] -> {filas}{extra}")


def construir():
    conn = _conn()
    actual = json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))
    if actual.get("version") == 3:
        base = []
        for q in actual["preguntas"]:
            q = dict(q)
            q["conjunto_v3"] = q["conjunto"]
            q["conjunto"] = "desarrollo"
            base.append(q)
    elif actual.get("version") == 4:
        base = [q for q in actual["preguntas"] if q["conjunto"] == "desarrollo"]
    else:
        raise SystemExit(f"versión de oráculo inesperada: {actual.get('version')}")
    assert len(base) == 30, len(base)
    nuevas = []
    for qid, tipo, preg, sql, tipos, orden, _ in PRUEBA_2:
        nuevas.append({"id": qid, "pestana_dashboard": None, "necesidad": None, "pregunta": preg, "sql_referencia": sql,
                       "tipos_columnas": tipos, "orden_importa": orden, "dificultad": tipo, "tipo": tipo, "origen_v1": None,
                       "conjunto": "prueba_2", "conjunto_v3": None,
                       "resultado_esperado": [list(f) for f in conn.execute(sql).fetchall()]})
    datos = {
        "version": 4,
        "descripcion": ("Oráculo de Olist. 50 preguntas, cada una resoluble con UNA consulta. conjunto = 'desarrollo' (30: las "
                        "20 de DESARROLLO v3 + las 10 de PRUEBA v3, que ya fue vista en la Etapa 2) o 'prueba_2' (20 nuevas, "
                        "Etapa 3: held-out, no se usan para ajustar nada y se evalúan una sola vez al final). Las 10 con "
                        "pestana_dashboard son las necesidades del dueño. Pedido válido = order_status NOT IN "
                        "('canceled','unavailable'). resultado_esperado se obtuvo ejecutando sql_referencia y se verifica con "
                        "dashboard/verify_pandas.py (pandas desde los CSV). Construido con eval/construir_oraculo_v4.py."),
        "cargado_con": "python seeder/load_olist_csv.py",
        "semilla_split": actual.get("semilla_split"),
        "preguntas": base + nuevas,
    }
    (RAIZ / "eval" / "ground_truth_olist.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    split = {"version": 4,
             "desarrollo": [q["id"] for q in datos["preguntas"] if q["conjunto"] == "desarrollo"],
             "prueba_2": [q["id"] for q in datos["preguntas"] if q["conjunto"] == "prueba_2"]}
    (RAIZ / "eval" / "split_oraculo.json").write_text(json.dumps(split, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"desarrollo: {len(split['desarrollo'])} | prueba_2: {len(split['prueba_2'])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorar", action="store_true")
    a = ap.parse_args()
    explorar() if a.explorar else construir()
