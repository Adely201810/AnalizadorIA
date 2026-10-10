# Fase 1 (afinar) — Tipos completos en el esquema y few-shot disjuntos del oráculo

Fecha: 2026-10-10 · Estado: **COMPLETA** · Pruebas: `python -m unittest tests.test_fewshot_disjunto -v` (6/6 OK)

## Qué se implementó

### 1. Tipos en el contexto de esquema (`llm/schema_context.py`)
- **Antes:** `_column_line` omitía el tipo `INTEGER`/`BOOLEAN` (ej. `review_score`, `payment_installments`, `order_item_id` aparecían sin tipo) y escribía **`STRING`** (nombre de la clase de SQLAlchemy, que no es un tipo de SQLite) para las columnas de texto. Las vistas se listaban **sin ningún tipo**, escritas a mano.
- **Después:** el tipo se compila con el dialecto SQLite y se normaliza (`_tipo_corto`: TEXT / INTEGER / NUMERIC / REAL / DATETIME). Las columnas de las vistas se leen de la base (`PRAGMA table_info`). Cuando una columna es una expresión sin tipo declarado, el tipo se infiere del primer valor no nulo de una muestra de 200 filas, más 4 anotaciones semánticas a mano (`es_recurrente` y `entrega_con_retraso` → `INTEGER 0/1`; `primera_compra` y `ultima_compra` → `DATETIME`).
- Tamaño del prompt de esquema: **12,235 → 12,501 caracteres** (`~1404` → `~1476` palabras).

Antes (extracto de `python -m llm.schema_context`):
```
order_payments(order_id PK FK->orders.order_id STRING, payment_sequential PK, payment_type STRING, payment_installments, payment_value NUMERIC)
order_reviews(id PK, review_id STRING, order_id FK->orders.order_id STRING, review_score, review_comment_title NULL? STRING, review_comment_message NULL? TEXT, review_creation_date DATETIME, review_answer_timestamp DATETIME)
- vw_ventas_pedido(order_id, order_item_id, customer_unique_id, customer_state, seller_id, seller_state, categoria_ingles, price, freight_value, order_status, order_purchase_timestamp, review_score_promedio) -- grano: una fila por línea de pedido
```
Después:
```
order_payments(order_id PK FK->orders.order_id TEXT, payment_sequential PK INTEGER, payment_type TEXT, payment_installments INTEGER, payment_value NUMERIC)
order_reviews(id PK INTEGER, review_id TEXT, order_id FK->orders.order_id TEXT, review_score INTEGER, review_comment_title NULL? TEXT, review_comment_message NULL? TEXT, review_creation_date DATETIME, review_answer_timestamp DATETIME)
- vw_ventas_pedido(order_id TEXT, order_item_id INTEGER, customer_unique_id TEXT, customer_state TEXT, seller_id TEXT, seller_state TEXT, categoria_ingles TEXT, price NUMERIC, freight_value NUMERIC, order_status TEXT, order_purchase_timestamp DATETIME, review_score_promedio REAL) -- grano: una fila por línea de pedido
- vw_clientes_recurrentes(customer_unique_id TEXT, num_pedidos INTEGER, primera_compra DATETIME, ultima_compra DATETIME, gasto_total REAL, es_recurrente INTEGER 0/1) -- excluye pedidos canceled/unavailable
- vw_entregas_retrasos(order_id TEXT, order_status TEXT, order_purchase_timestamp DATETIME, order_estimated_delivery_date DATETIME, order_delivered_customer_date DATETIME, dias_retraso REAL, entrega_con_retraso INTEGER 0/1, review_score_promedio REAL) -- solo pedidos entregados
```

### 2. Conjuntos disjuntos: few-shot (entrenamiento) vs oráculo (evaluación)
- Los ejemplos pasan de un bloque de texto a la lista `EJEMPLOS_FEW_SHOT` (`llm/schema_context.py`); `EJEMPLOS_TEXTO` se genera a partir de ella. Se verificó que el refactor no cambiaba el texto: `EJEMPLOS_TEXTO idéntico al original: True`.
- El conjunto de evaluación es `eval/ground_truth_olist.json`.
- Medida objetiva: `eval/similitud.py` (índice de Jaccard de tokens significativos, en texto y en SQL).

**Matriz ANTES** (`python -m eval.similitud`):
```
ejemplo few-shot                                                       | oráculo + parecido (texto)             | oráculo + parecido (SQL)
¿Cuántos clientes tenemos?                                             | q3_pct_clientes_recurrentes    0.083 | q1_pedidos_totales             0.200
¿Cuál es el retraso promedio de entrega, en días?                      | q8_tiempo_promedio_entrega     0.429 | q8_tiempo_promedio_entrega     0.714
¿Qué categoría de producto genera más ingresos?                        | q2_categoria_mas_ingresos      0.214 | q2_categoria_mas_ingresos      0.667
¿Cuáles son mis clientes recurrentes?                                  | q3_pct_clientes_recurrentes    0.077 | q3_pct_clientes_recurrentes    0.091
¿Qué categorías tienen más clientes que le compraron una sola vez?     | q4_categorias_mas_compra_unica 0.294 | q4_categorias_mas_compra_unica 0.152
¿Los pedidos con más retraso tienen peor calificación?                 | q5_retraso_baja_calificacion   0.333 | q1_pedidos_totales             0.000
¿Desde cuántos días de demora empiezan a bajar las reseñas?            | q8_tiempo_promedio_entrega     0.100 | q1_pedidos_totales             0.000
¿En qué estados el flete pesa más sobre el precio de los productos?    | q10_ticket_promedio_pedido     0.167 | q10_ticket_promedio_pedido     0.389
¿En qué categorías el flete pesa más sobre lo que se cobra por el prod | q4_categorias_mas_compra_unica 0.100 | q4_categorias_mas_compra_unica 0.031
¿En qué combinaciones de estado y categoría el flete pesa más sobre el | q10_ticket_promedio_pedido     0.154 | q10_ticket_promedio_pedido     0.333
¿Qué categorías concentran el 80% de los ingresos?                     | q2_categoria_mas_ingresos      0.067 | q2_categoria_mas_ingresos      0.062
¿Cuántos vendedores concentran el 80% de los ingresos?                 | q2_categoria_mas_ingresos      0.067 | q3_pct_clientes_recurrentes    0.087
```

**Ejemplos reemplazados y por qué:**

| # | Ejemplo eliminado | Motivo (dato) | Reemplazo (misma técnica, otra métrica) |
|---|---|---|---|
| 2 | ¿Cuál es el retraso promedio de entrega, en días? | ≈ q8: texto 0.429, SQL 0.714 | ¿Cuántos días tardan en promedio los clientes en recibir respuesta a su reseña? (`julianday` sobre `order_reviews`) |
| 3 | ¿Qué categoría de producto genera más ingresos? | ≈ q2: SQL 0.667. Además **contradecía la regla de negocio** del propio prompt: no excluía pedidos cancelados | ¿Cuántos productos distintos hay en cada categoría (en inglés)? (mismo `LEFT JOIN` a la traducción) |
| 5 | ¿Qué categorías tienen más clientes que le compraron una sola vez? | ≈ q4: misma métrica, texto 0.294 | ¿Cuántos vendedores hay en cada estado? (`GROUP BY` + conteo) |
| 6 | ¿Los pedidos con más retraso tienen peor calificación? | ≈ q5: misma pregunta de negocio, texto 0.333 | ¿Qué porcentaje de las reseñas es de 1 o 2 estrellas, por año de compra? (`strftime` + porcentaje con `CASE`) |

Antes de incluirlos, se comprobó que los SQL nuevos se ejecutan y devuelven filas (por ejemplo, `3.15` días promedio de respuesta a reseñas y `('SP', 1849)` vendedores).

Intentos intermedios rechazados por la prueba (no se subió ningún umbral para que pasaran):
- "¿Cuántos días pasan en promedio entre la aprobación del pago y la entrega del pedido a la transportista?" → texto 0.273 con q8.
- "¿Cuántos pedidos hay en cada estatus?" → SQL 0.500 con q1.

**Clasificador** (`llm/text_to_sql.py`, `CLASIFICADOR_SYSTEM_PROMPT`): dos ejemplos coincidían con el oráculo.
- "¿Los pedidos con retraso tienen una calificación más baja que los que llegan a tiempo?" era **casi literal a q5**. Se reemplazó por "¿Los pedidos pagados en varias cuotas tienen un valor más alto que los pagados en una sola?".
- "¿Qué categoría de producto genera más ingresos y cuánto?" se parecía a q2. Se reemplazó por "¿Qué vendedor tiene más pedidos y cuántos?".

**Matriz DESPUÉS:**
```
ejemplo few-shot                                                       | oráculo + parecido (texto)             | oráculo + parecido (SQL)
¿Cuántos clientes tenemos?                                             | q3_pct_clientes_recurrentes    0.083 | q1_pedidos_totales             0.200
¿Cuántos días tardan en promedio los clientes en recibir respuesta a s | q8_tiempo_promedio_entrega     0.182 | q8_tiempo_promedio_entrega     0.300
¿Cuántos productos distintos hay en cada categoría (en inglés)?        | q2_categoria_mas_ingresos      0.125 | q2_categoria_mas_ingresos      0.348
¿Cuáles son mis clientes recurrentes?                                  | q3_pct_clientes_recurrentes    0.077 | q3_pct_clientes_recurrentes    0.091
¿Cuántos vendedores hay en cada estado?                                | q7_estado_mas_pedidos_entregados 0.167 | q1_pedidos_totales             0.200
¿Qué porcentaje de las reseñas es de 1 o 2 estrellas, por año de compr | q3_pct_clientes_recurrentes    0.067 | q3_pct_clientes_recurrentes    0.273
¿Desde cuántos días de demora empiezan a bajar las reseñas?            | q8_tiempo_promedio_entrega     0.100 | q1_pedidos_totales             0.000
¿En qué estados el flete pesa más sobre el precio de los productos?    | q10_ticket_promedio_pedido     0.167 | q10_ticket_promedio_pedido     0.389
¿En qué categorías el flete pesa más sobre lo que se cobra por el prod | q4_categorias_mas_compra_unica 0.100 | q4_categorias_mas_compra_unica 0.031
¿En qué combinaciones de estado y categoría el flete pesa más sobre el | q10_ticket_promedio_pedido     0.154 | q10_ticket_promedio_pedido     0.333
¿Qué categorías concentran el 80% de los ingresos?                     | q2_categoria_mas_ingresos      0.067 | q2_categoria_mas_ingresos      0.062
¿Cuántos vendedores concentran el 80% de los ingresos?                 | q2_categoria_mas_ingresos      0.067 | q3_pct_clientes_recurrentes    0.087
```

## Prueba automática (`tests/test_fewshot_disjunto.py`)

Umbrales: texto < 0.25 y SQL < 0.5 contra **todas** las preguntas del oráculo. Están calibrados con la matriz ANTES: los ejemplos que duplicaban el oráculo tenían texto ≥ 0.294 o SQL ≥ 0.667, y los demás, texto ≤ 0.167 y SQL ≤ 0.389. La prueba también exige que cada SQL few-shot se ejecute y devuelva filas, que toda columna del esquema tenga tipo y que no aparezca `STRING`.

Primera corrida (3 fallos, cada uno con su causa y su arreglo):
```
FAIL: test_preguntas_fewshot_lejos_del_oraculo
AssertionError: 0.2727272727272727 not less than 0.25 : '¿Cuántos días pasan en promedio entre la aprobación del pago y la entrega del pedido a la transportista?' ~ q8_tiempo_promedio_entrega (texto 0.273)
FAIL: test_sql_fewshot_lejos_del_oraculo
AssertionError: 0.5 not less than 0.5 : '¿Cuántos pedidos hay en cada estatus?' ~ q1_pedidos_totales (SQL 0.500)
FAIL: test_toda_columna_tiene_tipo
AssertionError: False is not true : vw_retraso_por_rango: 'pct_1_2_estrellas REAL) -- rango_retraso: a_tiempo|1-3|4-7|8-14|15+ (días' sin tipo
Ran 6 tests in 38.236s
FAILED (failures=3)
```
Los dos primeros fallos llevaron a cambiar los ejemplos. El tercero era un error de la propia prueba: una regex voraz que capturaba el paréntesis de la descripción "(días)"; se corrigió con una regex no voraz.

Corrida final:
```
test_ejemplos_del_clasificador_lejos_del_oraculo (tests.test_fewshot_disjunto.TestFewShotDisjunto.test_ejemplos_del_clasificador_lejos_del_oraculo) ... ok
test_preguntas_fewshot_lejos_del_oraculo (tests.test_fewshot_disjunto.TestFewShotDisjunto.test_preguntas_fewshot_lejos_del_oraculo) ... ok
test_sql_fewshot_ejecuta_y_devuelve_filas (tests.test_fewshot_disjunto.TestFewShotDisjunto.test_sql_fewshot_ejecuta_y_devuelve_filas) ... ok
test_sql_fewshot_lejos_del_oraculo (tests.test_fewshot_disjunto.TestFewShotDisjunto.test_sql_fewshot_lejos_del_oraculo) ... ok
test_sin_tipo_string (tests.test_fewshot_disjunto.TestTiposEnEsquema.test_sin_tipo_string) ... ok
test_toda_columna_tiene_tipo (tests.test_fewshot_disjunto.TestTiposEnEsquema.test_toda_columna_tiene_tipo) ... ok

----------------------------------------------------------------------
Ran 6 tests in 37.967s

OK
```

## Decisiones propias
- **D-05** (DECISIONES.md): la disyunción se mide con Jaccard léxico, con umbrales calibrados sobre los datos; es una heurística, no una garantía semántica. Por eso los reemplazos también se revisaron a mano.
- Se mantuvo "¿Cuáles son mis clientes recurrentes?" (SQL 0.091 con q3): usa la misma vista que q3, pero no resuelve el porcentaje que pide q3.

## Efecto en la precisión
Se mide en la Fase 3 (baseline_01), junto con el evaluador endurecido.
