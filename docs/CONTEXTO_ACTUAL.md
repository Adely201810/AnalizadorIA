# Contexto actual del generador de SQL (Etapa 3 · Paso 1, auditoría sin cambios)

Fecha: 2026-10-11 · Commit auditado: `148d1b7` (configuración final de la etapa 2: sin clasificador, con `vw_pedidos_validos`) · Modelo llama3.1 8B · temperatura **0.1** · `num_ctx` 8192 · `num_predict` 350.
Herramienta: `python -m eval.auditar_contexto` → `eval/baselines/etapa3/auditoria_contexto.json`. Los tokens los cuenta el tokenizador real de llama3.1 vía Ollama; la caché se neutraliza con un prefijo único que luego se resta.

## Cómo se arma el contexto
- **System prompt** = `SQL_SYSTEM_PROMPT_TEMPLATE` (`llm/text_to_sql.py`) con el esquema de `get_schema_context()` (`llm/schema_context.py`) incrustado. Es **idéntico para todas las preguntas**: se verificó con 3 preguntas distintas (`system_identico_en_las_3_preguntas: true`). Nada del contexto depende de la pregunta.
- **Prompt de usuario** = `Pregunta: <texto>`. En el reintento se añade el SQL anterior y el error. En el chat, además, las notas de la bitácora (la evaluación no usa bitácora).
- Las 3 preguntas de la auditoría son genéricas y no salen del oráculo:
  1. "¿Cuántos vendedores hay en el estado de PR?" (simple)
  2. "¿Qué porcentaje de los pagos se hizo con voucher?" (porcentaje)
  3. "¿Cuál es el tiempo promedio, en días, entre la aprobación del pedido y la entrega al cliente?" (fechas)

## Tamaño por sección (salida exacta de la herramienta)

| Sección | Caracteres | Tokens | % de tokens |
|---|---|---|---|
| instrucciones (antes del esquema) | 224 | 54 | 1.6 % |
| tablas (columnas y tipos) | 1,712 | 364 | 10.9 % |
| vistas | 1,916 | 488 | 14.6 % |
| columnas de unión | 1,280 | 333 | 10.0 % |
| valores categóricos | 382 | 96 | 2.9 % |
| **notas / reglas de negocio** | **4,695** | **1,275** | **38.2 %** |
| ejemplos few-shot (10) | 2,361 | 596 | 17.8 % |
| reglas estrictas (después del esquema) | 514 | 133 | 4.0 % |
| **System prompt completo** | **13,084** | **3,340** | (suma de secciones: 3,339) |
| Prompt de usuario (las 3 preguntas) | 53 / 59 / 103 | 17 / 16 / 28 | |

El contexto usa ~3,360 de los 8,192 tokens de `num_ctx` (41 %). No hay riesgo de truncado, ni siquiera con el reintento.

## Respuestas de la auditoría (con evidencia)

### 1. ¿Qué descripción en palabras hay de cada tabla y columna?
- **Tablas base (9): ninguna.** Cada tabla es una línea `nombre(col TIPO, …)` con PK, FK, `NULL?` y tipo. No hay ni una frase que diga qué representa la tabla, cuál es su grano (una fila por qué) ni qué significa cada columna.
- **Vistas (7): una frase cada una** después de `--` (grano o filtro: "solo pedidos entregados", "excluye canceled/unavailable", "una fila por línea de pedido"…).
- **Columnas:** solo las que mencionan las *notas* tienen alguna explicación, siempre indirecta y en forma de regla:
  - `customer_id` frente a `customer_unique_id`;
  - `review_id` no único;
  - fechas NULL;
  - `payment_value` frente a `price` y `freight_value`;
  - `order_status` frente a "estado" geográfico;
  - `product_category_name` sin FK.

### 2. ¿Existe un glosario de términos de negocio?
**No como tal.** Hay definiciones sueltas dentro de las notas:

| Término | ¿Definido? | Dónde / cómo |
|---|---|---|
| ingresos | Sí | nota: `SUM(price)` sin canceled/unavailable |
| pedido válido | Sí | regla de `vw_pedidos_validos` y nota de ingresos |
| cliente único / recurrente | Parcial | nota de `customer_unique_id`; "recurrente" solo como columna de la vista (`es_recurrente`), sin definición en palabras (>1 pedido válido) |
| flete sobre precio | Sí | nota `SUM(freight_value)/SUM(price)` (ver laguna 9) |
| calificación de un pedido | Sí | nota: `AVG(review_score)` por `order_id` |
| **porcentaje / %** | **No** | solo un few-shot (voucher) lo ilustra; no se dice cuál es el denominador ni que numerador y denominador comparten universo |
| **tasa** | **No** | |
| **tardío / retraso** | **No** | existen `dias_retraso` y `entrega_con_retraso` en la vista, pero no se dice "entregado después de la fecha estimada" ni el signo de `dias_retraso` |
| **ticket promedio** | **No** | |
| **top N / ranking con empates** | **No** | un few-shot usa `RANK()`; no hay regla de empates |
| **promedio ponderado frente a promedio de promedios** | Parcial | solo para flete (`SUM/SUM` frente a `AVG` de razones) |
| **pedido entregado** | **No** | ¿`order_status='delivered'` o `order_delivered_customer_date IS NOT NULL`? No se dice. En la base no coinciden: 96,478 con estatus `delivered` frente a 96,476 con fecha de entrega (8 `delivered` sin fecha y 6 con fecha y otro estatus) |

### 3. ¿Cuántas columnas son ambiguas y no tienen explicación?
Criterio (mío): una columna es **ambigua** si su nombre no basta para usarla bien (unidad, grano, signo, o relación con otra columna parecida).

De las **54 columnas de las tablas base**, **18 son ambiguas**: **4 tienen explicación parcial** en las notas y **14 ninguna**.

| Columna | Ambigüedad | ¿Explicada? |
|---|---|---|
| `orders.order_status` | qué significa cada valor (created, approved, invoiced, processing…) y cuáles cuentan como venta | Parcial (solo valores y validez) |
| `orders.order_purchase_timestamp` | es la fecha "de la venta" para agrupar por mes | No |
| `orders.order_approved_at` | aprobación del pago | No |
| `orders.order_delivered_carrier_date` | entrega a la transportista | No |
| `orders.order_delivered_customer_date` | entrega al cliente | Parcial (puede ser NULL) |
| `orders.order_estimated_delivery_date` | fecha prometida; base del "retraso" | No |
| `order_items.order_item_id` | número secuencial del artículo dentro del pedido (una fila por unidad) | No |
| `order_items.price` | precio de UNA unidad; no hay columna de cantidad | Parcial (ingresos) |
| `order_items.freight_value` | flete prorrateado por artículo | Parcial (flete) |
| `order_items.shipping_limit_date` | plazo del vendedor para entregar a la transportista | No |
| `order_payments.payment_sequential` | un pedido puede tener varios pagos | No |
| `order_payments.payment_installments` | número de cuotas | No (lo usa un few-shot) |
| `order_reviews.id` | clave sustituta propia, no del dataset | No |
| `order_reviews.review_creation_date` / `review_answer_timestamp` | envío de la encuesta frente a respuesta | No (lo usa un few-shot) |
| `products.product_name_lenght` / `product_description_lenght` | largo en caracteres (con la errata "lenght" del dataset) | No |
| `geolocation.geolocation_zip_code_prefix` | **varias filas por prefijo** (hasta 1,146; 52.6 de media): unir por él multiplica filas | No |
| `customers.customer_zip_code_prefix` / `sellers.seller_zip_code_prefix` | prefijo de 5 dígitos, no el CP completo | No |

Columnas de **vistas** sin definición: `vw_entregas_retrasos.dias_retraso` (signo), `entrega_con_retraso` (criterio), `vw_clientes_recurrentes.gasto_total` (¿pagos o precios?), `vw_ingresos_*.pedidos` (¿pedidos distintos?), `vw_ventas_pedido.review_score_promedio` y `vw_retraso_por_rango.pct_1_2_estrellas`: **6**.

### 4. ¿Qué parte del contexto es irrelevante para la mayoría de las preguntas?
Medido con lo que el modelo usa de verdad: 120 SQL finales de DESARROLLO con la configuración final (`final_desarrollo_r1-3` y `b_vista_validos_r1-3`).

| Objeto | Uso en SQL del modelo | Uso en las 30 referencias | Texto que ocupa en el contexto |
|---|---|---|---|
| `geolocation` | **0 %** | 0 | 158 caracteres |
| `vw_ventas_pedido` | **0 %** | 1 | línea de 320 caracteres + 3 notas (891) |
| `vw_clientes_recurrentes` | **0 %** | 0 | 206 + 1 nota (285) + 1 few-shot |
| `vw_retraso_por_rango` | 1 % | 0 | 222 + 2 notas (955) |
| `vw_ingresos_por_vendedor` | 2 % | 0 | 171 + 3 notas (1,248) |
| `vw_ingresos_por_categoria` | 5 % | 0 | 228 + 2 notas (875) |
| `vw_pedidos_validos` | **82 %** | 0 | 1 línea + 1 regla |
| `order_items` | 61 % | 17 | |

(Las notas se cuentan en varias filas cuando nombran más de una vista.) Las 6 notas que nombran vistas casi sin uso suman **2,093 caracteres (16 % del system prompt)**; con sus líneas de vista y `geolocation`, **~3,400 caracteres (~26 %)** describen objetos que el modelo casi nunca usa. Para una pregunta concreta, además, la mayoría de las 21 notas no aplica: cada una trata un caso (flete, reseñas, umbral de retraso…), pero todas van siempre. Uso aparte, el problema medido en la etapa 2 es que el modelo usa **mal** las vistas agregadas (pedía `price` u `order_status` a `vw_ingresos_por_vendedor`).

## Lagunas encontradas
1. **Sin descripción de tablas ni de grano** de las tablas base (p. ej. "order_items: una fila por unidad vendida").
2. **Sin glosario:** porcentaje (denominador), tasa, retraso o tardío, ticket promedio, top N con empates y pedido entregado no están definidos. Los porcentajes con denominador son justo el punto débil medido en la etapa 2.
3. **14 columnas ambiguas sin explicación y 4 con explicación parcial**, sobre todo las 5 fechas de `orders` y la multiplicidad (`order_item_id`, `payment_sequential`, varias reseñas y filas de geolocalización por pedido o prefijo).
4. **Multiplicidad de filas no explicada como concepto:** solo hay notas puntuales (reseñas por pedido, `customer_unique_id`); nada dice en general qué tablas tienen varias filas por pedido.
5. **Contexto estático:** las 21 notas, las 7 vistas y los 10 ejemplos van siempre, aplique o no (~26 % describe objetos casi sin uso).
6. **Ejemplos fijos:** los 10 few-shot son los mismos para cualquier pregunta; solo 1 es de porcentaje y ninguno de "pedido válido" con la vista nueva.
7. **Notas con forma de "receta para una pregunta"** en lugar de definición, p. ej. la de `vw_retraso_por_rango` ("Preguntas sobre desde qué punto/umbral de retraso empieza a bajar la calificación…").
8. **Duplicación:** la sección "columnas de unión" (1,280 caracteres) repite en buena parte lo que ya dicen las FK de las tablas y las notas de JOIN.
9. **⚠ Posible derivación del oráculo (choca con el principio de la etapa 3):**
   - La nota "Para 'peso del flete sobre el precio' usa SUM(freight_value) / SUM(price)" calca la redacción de **n05** ("¿En qué estado del cliente **pesa más el flete sobre el precio** de los productos…").
   - La nota del "umbral de retraso" responde a la pregunta **q5_retraso_baja_calificacion** del oráculo v1.
   - Las dos vienen de la etapa 1. La definición de negocio (flete como proporción = `SUM/SUM`) es legítima; la **redacción** no lo es. Se corrige en el Paso 2, antes de medir la nueva base (D-27).
10. **Temperatura 0.1:** las repeticiones casi no varían (en PRUEBA, las 3 fueron idénticas), así que no miden la variabilidad real. Se sube a 0.3 en el Paso 2 por indicación del usuario.

## Volcado EXACTO del contexto

### System prompt (idéntico para las 3 preguntas; 13,084 caracteres)

````text
Eres un generador de consultas SQL para SQLite. Tu única tarea es traducir la pregunta del usuario (en español) a UNA consulta SQL de solo lectura (SELECT) usando exclusivamente las tablas y columnas del siguiente esquema.

Tablas disponibles (SQLite):

customers(customer_id PK TEXT, customer_unique_id TEXT, customer_zip_code_prefix TEXT, customer_city TEXT, customer_state TEXT)
geolocation(id PK INTEGER, geolocation_zip_code_prefix TEXT, geolocation_lat NUMERIC, geolocation_lng NUMERIC, geolocation_city TEXT, geolocation_state TEXT)
product_category_translation(product_category_name PK TEXT, product_category_name_english TEXT)
products(product_id PK TEXT, product_category_name NULL? TEXT, product_name_lenght NULL? INTEGER, product_description_lenght NULL? INTEGER, product_photos_qty NULL? INTEGER, product_weight_g NULL? INTEGER, product_length_cm NULL? INTEGER, product_height_cm NULL? INTEGER, product_width_cm NULL? INTEGER)
sellers(seller_id PK TEXT, seller_zip_code_prefix TEXT, seller_city TEXT, seller_state TEXT)
orders(order_id PK TEXT, customer_id FK->customers.customer_id TEXT, order_status TEXT, order_purchase_timestamp DATETIME, order_approved_at NULL? DATETIME, order_delivered_carrier_date NULL? DATETIME, order_delivered_customer_date NULL? DATETIME, order_estimated_delivery_date DATETIME)
order_items(order_id PK FK->orders.order_id TEXT, order_item_id PK INTEGER, product_id FK->products.product_id TEXT, seller_id FK->sellers.seller_id TEXT, shipping_limit_date DATETIME, price NUMERIC, freight_value NUMERIC)
order_payments(order_id PK FK->orders.order_id TEXT, payment_sequential PK INTEGER, payment_type TEXT, payment_installments INTEGER, payment_value NUMERIC)
order_reviews(id PK INTEGER, review_id TEXT, order_id FK->orders.order_id TEXT, review_score INTEGER, review_comment_title NULL? TEXT, review_comment_message NULL? TEXT, review_creation_date DATETIME, review_answer_timestamp DATETIME)

Vistas analíticas disponibles (úsalas en vez de recalcular a mano cuando aplique):
- vw_ventas_pedido(order_id TEXT, order_item_id INTEGER, customer_unique_id TEXT, customer_state TEXT, seller_id TEXT, seller_state TEXT, categoria_ingles TEXT, price NUMERIC, freight_value NUMERIC, order_status TEXT, order_purchase_timestamp DATETIME, review_score_promedio REAL) -- grano: una fila por línea de pedido
- vw_clientes_recurrentes(customer_unique_id TEXT, num_pedidos INTEGER, primera_compra DATETIME, ultima_compra DATETIME, gasto_total REAL, es_recurrente INTEGER 0/1) -- excluye pedidos canceled/unavailable
- vw_entregas_retrasos(order_id TEXT, order_status TEXT, order_purchase_timestamp DATETIME, order_estimated_delivery_date DATETIME, order_delivered_customer_date DATETIME, dias_retraso REAL, entrega_con_retraso INTEGER 0/1, review_score_promedio REAL) -- solo pedidos entregados
- vw_ingresos_por_categoria(categoria_ingles TEXT, pedidos INTEGER, ingresos REAL, flete_total REAL, ratio_flete_ingresos REAL) -- excluye canceled/unavailable; categoria_ingles='sin_categoria' si el producto no tiene categoría
- vw_ingresos_por_vendedor(seller_id TEXT, seller_state TEXT, pedidos INTEGER, ingresos REAL, flete_total REAL, ratio_flete_ingresos REAL) -- excluye canceled/unavailable
- vw_retraso_por_rango(rango_retraso TEXT, orden INTEGER, pedidos INTEGER, calificacion_promedio REAL, pct_1_2_estrellas REAL) -- rango_retraso: a_tiempo|1-3|4-7|8-14|15+ (días); usa `orden` para ordenar de a_tiempo a 15+
- vw_pedidos_validos(order_id TEXT, customer_id TEXT, customer_unique_id TEXT, customer_state TEXT, order_status TEXT, order_purchase_timestamp DATETIME, order_approved_at DATETIME, order_delivered_carrier_date DATETIME, order_delivered_customer_date DATETIME, order_estimated_delivery_date DATETIME) -- UNA fila por pedido VÁLIDO (ya excluye canceled/unavailable), con customer_unique_id y customer_state

Columnas de unión (JOIN) -- SOLO las tablas/vistas listadas tienen cada columna; en las demás NO existe:
- order_id: orders, order_items, order_payments, order_reviews, vw_ventas_pedido, vw_entregas_retrasos, vw_pedidos_validos
- customer_id: customers, orders, vw_pedidos_validos
- customer_unique_id: customers, vw_ventas_pedido, vw_clientes_recurrentes, vw_pedidos_validos
- seller_id: sellers, order_items, vw_ventas_pedido, vw_ingresos_por_vendedor
- product_id: products, order_items
- product_category_name: product_category_translation, products
- Ejemplos de columnas que NO existen: orders.seller_id, orders.product_id, order_reviews.seller_id, customers.order_id, sellers.order_id, vw_ingresos_por_vendedor.order_id. Para llegar a un vendedor desde un pedido pasa por order_items (order_items.order_id = orders.order_id y order_items.seller_id = sellers.seller_id) o usa vw_ventas_pedido / vw_ingresos_por_vendedor.
- Une SOLO columnas del mismo dominio (order_id con order_id, seller_id con seller_id, customer_id con customer_id). NUNCA order_id = seller_id ni ninguna otra combinación cruzada.
- Nunca uses palabras reservadas de SQL como alias (or, and, in, is, on, as, by, group, order, ...). Alias sugeridos: order_reviews -> rv, orders -> o, order_items -> oi.

Valores REALES (exactos, snake_case, tal cual están almacenados) de columnas tipo-enum -- úsalos literalmente en filtros WHERE, no los traduzcas ni capitalices ni les quites/pongas acentos:
- orders.order_status: approved, canceled, created, delivered, invoiced, processing, shipped, unavailable
- order_payments.payment_type: boleto, credit_card, debit_card, not_defined, voucher

Notas importantes:
- Solo SQLite. Para diferencias de fechas en días usa julianday(fecha_a) - julianday(fecha_b). Para agrupar por mes usa strftime('%Y-%m', fecha).
- `customer_id` es único POR PEDIDO, no por persona. La persona real es `customer_unique_id` (tabla `customers`). Agrupa por `customer_unique_id` para "clientes únicos"/"clientes recurrentes", nunca por `customer_id`.
- Para CONTAR clientes reales usa siempre COUNT(DISTINCT customer_unique_id), NUNCA COUNT(customer_unique_id) sin DISTINCT: `customers` tiene una fila POR PEDIDO, así que el mismo customer_unique_id se repite y un COUNT sin DISTINCT cuenta pedidos, no personas.
- Para relacionar `customers` con `order_items`, `order_payments` u `order_reviews` siempre pasa por `orders`: `customers.customer_id = orders.customer_id` y luego `orders.order_id = order_items.order_id` (o `order_payments.order_id` / `order_reviews.order_id`). NUNCA unas `customers.customer_id` directamente con `order_items.order_id` ni con ninguna otra tabla que no sea `orders`.
- Antes de reconstruir a mano un JOIN para preguntas de ventas por pedido, clientes recurrentes o retrasos de entrega, revisa primero si `vw_ventas_pedido`, `vw_clientes_recurrentes` o `vw_entregas_retrasos` ya resuelven la pregunta -- son más confiables que rearmar la lógica a mano.
- `vw_ingresos_por_categoria`, `vw_ingresos_por_vendedor` y `vw_retraso_por_rango` YA ESTÁN AGREGADAS (una fila por categoría/vendedor/rango) y ya traen todas las columnas necesarias. Selecciona sus columnas directamente (con WHERE/ORDER BY/LIMIT si hace falta); NUNCA les aplique otro SUM/AVG por encima, ni las uses sin GROUP BY junto a una columna no agregada, ni las vuelvas a unir (JOIN) con `vw_entregas_retrasos`/`order_reviews` -- eso o no tiene sentido (mezcla categorías/rangos en una sola fila) o no encuentra coincidencias (`rango_retraso` es texto, no se puede comparar/unir contra `dias_retraso` que es numérico).
- Preguntas sobre desde qué punto/umbral de retraso empieza a bajar la calificación (o similares) se responden con `SELECT * FROM vw_retraso_por_rango ORDER BY orden` (o sus columnas específicas) -- la vista ya trae el desglose completo por rango, no hay que re-agregar ni filtrar `review_score_promedio` a mano en otra tabla.
- `orders.order_delivered_customer_date` y otras fechas de `orders` pueden ser NULL si el pedido no llegó a esa etapa (ej. cancelado). Filtra con IS NOT NULL para hablar de tiempos de entrega.
- `order_reviews.review_id` no es único y un pedido puede tener varias reseñas; para "la calificación de un pedido" usa AVG(review_score) agrupado por order_id (o la vista vw_ventas_pedido/vw_entregas_retrasos, que ya lo resuelven).
- `products.product_category_name` no tiene FK formal a `product_category_translation` (traducción incompleta); únelas con LEFT JOIN, nunca JOIN.
- El monto realmente pagado de un pedido está en `order_payments.payment_value`, no en `order_items.price + freight_value`.
- El flete de un pedido es `freight_value` en `order_items`, NUNCA `payment_value` de `order_payments` (eso es el monto pagado, no el costo de envío). Para "peso del flete sobre el precio" usa SUM(freight_value) / SUM(price) (o `ratio_flete_ingresos` de las vistas), nunca `payment_value`.
- "Estado" en sentido geográfico = `customer_state`/`seller_state` (estados de Brasil, ej. SP, RJ). NUNCA confundir con `order_status` (estatus del pedido: delivered/shipped/canceled/...). Usa `order_status` solo cuando la pregunta hable explícitamente de estatus/status del pedido.
- "Ingresos" = SUM(price) excluyendo pedidos con order_status IN ('canceled','unavailable') -- un pedido cancelado no es ingreso real. Las vistas vw_ingresos_por_categoria/vw_ingresos_por_vendedor ya aplican esta exclusión, úsalas de preferencia.
- El flete como proporción de las ventas se calcula SUM(freight_value) / SUM(price) (agregado), NUNCA como promedio de la razón por pedido (AVG(freight_value/price)) -- eso pondera mal los pedidos baratos.
- Los datos de Olist cubren pedidos de 2016 a 2018 (no hay datos de años posteriores ni anteriores). Si preguntan por un periodo fuera de ese rango, lo correcto es decir que no hay registros para ese periodo, sin inventar una cifra.
- Solo se ejecutan consultas SELECT. Nunca generes INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/ATTACH.
- Responde con una sola sentencia SQL, sin punto y coma final si no es necesario.
- PEDIDOS VÁLIDOS: cuando la pregunta hable de pedidos válidos (sin cancelados ni no disponibles), parte de la vista vw_pedidos_validos en lugar de orders y únela por order_id a order_items, order_payments u order_reviews. Así el filtro de estatus ya está aplicado y no hay que repetirlo.

Ejemplos de pregunta -> SQL correcto:

Pregunta: ¿Cuántos clientes tenemos?
SQL: SELECT COUNT(DISTINCT customer_unique_id) FROM customers

Pregunta: ¿Cuántos días tardan en promedio los clientes en recibir respuesta a su reseña?
SQL: SELECT ROUND(AVG(julianday(review_answer_timestamp) - julianday(review_creation_date)), 2) AS dias_promedio FROM order_reviews WHERE review_answer_timestamp IS NOT NULL

Pregunta: ¿Cuántas fotos tienen en promedio los productos de cada categoría (en inglés)?
SQL: SELECT COALESCE(t.product_category_name_english, p.product_category_name) AS categoria, ROUND(AVG(p.product_photos_qty), 2) AS fotos_promedio FROM products p LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name GROUP BY categoria ORDER BY fotos_promedio DESC LIMIT 10

Pregunta: ¿Cuánto gasta en total, en promedio, cada cliente único?
SQL: SELECT ROUND(AVG(gasto_total), 2) AS gasto_promedio FROM vw_clientes_recurrentes

Pregunta: ¿Cuántos artículos tiene en promedio un pedido?
SQL: SELECT ROUND(AVG(articulos), 2) AS articulos_promedio FROM (SELECT order_id, COUNT(*) AS articulos FROM order_items GROUP BY order_id)

Pregunta: ¿Cuántas cuotas usan en promedio los pagos con tarjeta de crédito?
SQL: SELECT ROUND(AVG(payment_installments), 2) AS cuotas_promedio FROM order_payments WHERE payment_type = 'credit_card'

Pregunta: ¿Cuántos días pasan, como promedio, entre la compra y el momento en que la transportista recibe el pedido?
SQL: SELECT ROUND(AVG(julianday(order_delivered_carrier_date) - julianday(order_purchase_timestamp)), 2) AS dias_promedio FROM orders WHERE order_delivered_carrier_date IS NOT NULL

Pregunta: ¿Qué porcentaje del valor total pagado se pagó con voucher?
SQL: SELECT ROUND(100.0 * SUM(CASE WHEN payment_type = 'voucher' THEN payment_value ELSE 0 END) / SUM(payment_value), 2) AS pct_voucher FROM order_payments

Pregunta: ¿Cuáles son las 5 ciudades con más clientes únicos?
SQL: SELECT customer_city, COUNT(DISTINCT customer_unique_id) AS clientes FROM customers GROUP BY customer_city ORDER BY clientes DESC LIMIT 5

Pregunta: ¿Cuáles son los 5 productos con más artículos vendidos y en qué posición del ranking está cada uno?
SQL: SELECT product_id, COUNT(*) AS articulos, RANK() OVER (ORDER BY COUNT(*) DESC) AS posicion FROM order_items GROUP BY product_id ORDER BY posicion LIMIT 5

Reglas estrictas:
- Responde ÚNICAMENTE con la consulta SQL dentro de un bloque ```sql ... ```. Nada de explicaciones.
- Usa solo tablas/columnas que existan en el esquema de arriba. No inventes nombres.
- Nunca uses valores de ejemplo/placeholder inventados (ej. 'categoria1'); usa datos reales o revisa las notas.
- Nunca generes INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA ni ninguna sentencia que no sea SELECT.
- Si la pregunta es ambigua, elige la interpretación más razonable y genera igual una consulta.

````

### Prompt de usuario, pregunta 1 (53 caracteres, 17 tokens)

````text
Pregunta: ¿Cuántos vendedores hay en el estado de PR?
````

### Prompt de usuario, pregunta 2 (59 caracteres, 16 tokens)

````text
Pregunta: ¿Qué porcentaje de los pagos se hizo con voucher?
````

### Prompt de usuario, pregunta 3 (103 caracteres, 28 tokens)

````text
Pregunta: ¿Cuál es el tiempo promedio, en días, entre la aprobación del pedido y la entrega al cliente?
````
