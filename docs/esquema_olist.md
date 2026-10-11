# Diccionario de datos — Olist (e-commerce brasileño)

Base de datos relacional con el dataset público de Olist: ~100,000 pedidos de un
marketplace brasileño entre 2016 y 2018, con sus clientes, productos, vendedores,
pagos, reseñas y geolocalización.

Motor de referencia: **SQLite** (`db/olist.db`). El esquema está definido en
SQLAlchemy (`db/olist_models.py`) y es portable a **PostgreSQL** cambiando la
variable de entorno `OLIST_DATABASE_URL` (mismo patrón que `legacy/gimnasio/db/database.py`).

Este documento es la fuente de verdad que se inyecta como contexto al LLM en el
módulo Text-to-SQL (`llm/text_to_sql.py`), para reducir alucinaciones y anclar al
modelo a los nombres reales de tablas/columnas.

> Convenciones: PK = llave primaria · FK = llave foránea · montos en **BRL**
> (reales brasileños) · fechas/horas en **UTC** sin zona horaria explícita.

---

## ⚠️ Cuidados importantes del dataset (leer antes de escribir SQL)

1. **`customer_id` NO es la persona.** Es un identificador único **por pedido**.
   La misma persona que compra dos veces tiene dos filas distintas en
   `customers`, cada una con un `customer_id` diferente pero el mismo
   `customer_unique_id`. **Toda pregunta sobre clientes recurrentes, número de
   clientes únicos o comportamiento de compra de una persona debe agrupar por
   `customer_unique_id`**, nunca por `customer_id`. Usa la vista
   `vw_clientes_recurrentes`, ya resuelta.
2. **`geolocation` no tiene llave única.** Hay muchas filas por
   `geolocation_zip_code_prefix` (distintas coordenadas dentro del mismo prefijo
   postal). No asumas una fila por código postal; si necesitas una sola
   coordenada representativa, agrega con `AVG()` o `LIMIT 1`.
3. **`order_reviews` tiene duplicados.** El mismo `review_id` puede aparecer en
   pedidos distintos, y un mismo pedido puede tener más de una reseña. No trates
   `review_id` como único. Para calificación por pedido usa `AVG(review_score)`
   agrupado por `order_id` (así lo hacen `vw_ventas_pedido` y
   `vw_entregas_retrasos`).
4. **Fechas NULL en `orders` son normales**, no errores: `order_approved_at`,
   `order_delivered_carrier_date` y `order_delivered_customer_date` quedan NULL
   cuando el pedido no llegó a esa etapa (típicamente en `order_status IN
   ('canceled', 'unavailable', 'created', 'processing', 'invoiced', 'shipped')`).
   Para hablar de "tiempo de entrega" o "retraso", filtra siempre por
   `order_delivered_customer_date IS NOT NULL` (o usa `vw_entregas_retrasos`,
   que ya lo hace).
5. **`products` tiene columnas con typo original del dataset**:
   `product_name_lenght` y `product_description_lenght` (falta la "t" de
   "length"). Se conservaron tal cual para no desincronizar de la fuente.
6. **La traducción de categorías está incompleta.** `product_category_translation`
   no cubre todas las categorías que aparecen en `products.product_category_name`
   (hay categorías sin traducción). Por eso no hay FK formal entre ambas tablas:
   siempre usa `LEFT JOIN` (nunca `JOIN`), con `COALESCE` al nombre en portugués
   si no hay traducción — así lo hace `vw_ventas_pedido`.

---

## Índice de tablas

| Dominio | Tablas |
|---|---|
| Clientes / Geografía | `customers`, `geolocation` |
| Vendedores | `sellers` |
| Catálogo | `products`, `product_category_translation` |
| Pedidos | `orders`, `order_items`, `order_payments`, `order_reviews` |
| Vistas analíticas | `vw_ventas_pedido`, `vw_clientes_recurrentes`, `vw_entregas_retrasos` |

---

## `customers`
Una fila **por pedido** (no por persona; ver cuidado #1).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| customer_id | VARCHAR(32) PK | No | Identificador único del pedido-cliente |
| customer_unique_id | VARCHAR(32) | No | Identificador real de la persona; se repite entre pedidos del mismo cliente |
| customer_zip_code_prefix | VARCHAR(10) | No | Primeros dígitos del código postal (string, con ceros a la izquierda) |
| customer_city | VARCHAR(80) | No | |
| customer_state | VARCHAR(2) | No | Sigla del estado brasileño (SP, RJ, ...) |

## `geolocation`
Coordenadas por prefijo de código postal. **Sin llave natural única** (ver cuidado #2).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | PK técnica autoincremental, no viene del dataset original |
| geolocation_zip_code_prefix | VARCHAR(10) | No | |
| geolocation_lat | NUMERIC(11,8) | No | |
| geolocation_lng | NUMERIC(11,8) | No | |
| geolocation_city | VARCHAR(80) | No | |
| geolocation_state | VARCHAR(2) | No | |

## `sellers`
Vendedores del marketplace.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| seller_id | VARCHAR(32) PK | No | |
| seller_zip_code_prefix | VARCHAR(10) | No | |
| seller_city | VARCHAR(80) | No | |
| seller_state | VARCHAR(2) | No | |

## `products`
Catálogo de productos vendidos. ~1.8% de filas (610 de 32,951) tienen
`product_category_name` y las columnas de dimensiones en NULL.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| product_id | VARCHAR(32) PK | No | |
| product_category_name | VARCHAR(80) | Sí | Nombre de categoría **en portugués**; sin FK formal (ver cuidado #6) |
| product_name_lenght | INTEGER | Sí | Longitud del nombre del producto (typo original: "lenght") |
| product_description_lenght | INTEGER | Sí | Longitud de la descripción (typo original: "lenght") |
| product_photos_qty | INTEGER | Sí | Número de fotos publicadas |
| product_weight_g | INTEGER | Sí | Peso en gramos |
| product_length_cm | INTEGER | Sí | |
| product_height_cm | INTEGER | Sí | |
| product_width_cm | INTEGER | Sí | |

## `product_category_translation`
Traducción portugués → inglés del nombre de categoría. **71 categorías**, no
cubre el 100% de las que aparecen en `products` (ver cuidado #6).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| product_category_name | VARCHAR(80) PK | No | Nombre en portugués, igual al de `products.product_category_name` |
| product_category_name_english | VARCHAR(80) | No | Nombre en inglés |

---

## `orders`
Un pedido. Ver cuidado #4 sobre fechas NULL.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| order_id | VARCHAR(32) PK | No | |
| customer_id | VARCHAR(32) FK → customers.customer_id | No | |
| order_status | VARCHAR(20) | No | `delivered` \| `shipped` \| `canceled` \| `unavailable` \| `invoiced` \| `processing` \| `created` \| `approved` |
| order_purchase_timestamp | DATETIME | No | Fecha/hora en que se realizó el pedido |
| order_approved_at | DATETIME | Sí | NULL si nunca se aprobó el pago |
| order_delivered_carrier_date | DATETIME | Sí | NULL si nunca se despachó |
| order_delivered_customer_date | DATETIME | Sí | NULL si nunca se entregó (usar para filtrar "pedidos entregados") |
| order_estimated_delivery_date | DATETIME | No | Fecha estimada de entrega prometida al cliente |

> Casi el 97% de los pedidos tiene `order_status = 'delivered'`; el resto se
> reparte entre `shipped`, `canceled`, `unavailable`, `invoiced`, `processing`,
> `created` y `approved`.

## `order_items`
Línea de producto dentro de un pedido. **PK compuesta** `(order_id, order_item_id)`:
un pedido puede tener varias líneas (una por unidad/producto vendido).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| order_id | VARCHAR(32) PK, FK → orders.order_id | No | |
| order_item_id | INTEGER PK | No | Número de línea dentro del pedido (1, 2, 3, ...) |
| product_id | VARCHAR(32) FK → products.product_id | No | |
| seller_id | VARCHAR(32) FK → sellers.seller_id | No | |
| shipping_limit_date | DATETIME | No | Fecha límite para que el vendedor despache |
| price | NUMERIC(10,2) | No | Precio del producto en esa línea (BRL) |
| freight_value | NUMERIC(10,2) | No | Costo de flete de esa línea (BRL) |

> El total pagado por un pedido NO es solo `SUM(price + freight_value)` de sus
> líneas: para el monto realmente cobrado usa `order_payments.payment_value`
> (puede incluir cuotas, vouchers, etc.).

## `order_payments`
Pago(s) de un pedido. **PK compuesta** `(order_id, payment_sequential)`: un
pedido puede pagarse en más de una transacción (ej. tarjeta + voucher). La
columna del CSV original se llama `payment_sequential`.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| order_id | VARCHAR(32) PK, FK → orders.order_id | No | |
| payment_sequential | INTEGER PK | No | Número de secuencia del pago dentro del pedido |
| payment_type | VARCHAR(20) | No | `credit_card` \| `boleto` \| `voucher` \| `debit_card` \| `not_defined` |
| payment_installments | INTEGER | No | Número de cuotas |
| payment_value | NUMERIC(10,2) | No | Monto de esa transacción (BRL) |

## `order_reviews`
Reseña de un pedido. Ver cuidado #3 sobre duplicados.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | PK técnica autoincremental (no viene del CSV) |
| review_id | VARCHAR(32) | No | **No es único**, ver cuidado #3 |
| order_id | VARCHAR(32) FK → orders.order_id | No | Un pedido puede tener más de una reseña |
| review_score | INTEGER | No | Escala 1 (peor) a 5 (mejor) |
| review_comment_title | VARCHAR(120) | Sí | Título del comentario; falta en la mayoría de las filas |
| review_comment_message | TEXT | Sí | Texto libre del comentario; falta en más de la mitad de las filas |
| review_creation_date | DATETIME | No | |
| review_answer_timestamp | DATETIME | No | Fecha en que el vendedor/plataforma respondió |

---

## Vistas analíticas

### `vw_ventas_pedido`
Grano: **una fila por línea de pedido** (`order_items`). Columnas: `order_id`,
`order_item_id`, `customer_unique_id`, `categoria_ingles` (LEFT JOIN a la
traducción, con fallback al nombre en portugués), `price`, `freight_value`,
`order_status`, `order_purchase_timestamp`, `review_score_promedio` (una sola
calificación por pedido, promediada si hubo más de una reseña).

### `vw_clientes_recurrentes`
Grano: una fila por `customer_unique_id`. Columnas: `customer_unique_id`,
`num_pedidos` (pedidos distintos), `primera_compra`, `ultima_compra`,
`gasto_total` (suma de `order_payments.payment_value` de sus pedidos),
`es_recurrente` (1 si `num_pedidos > 1`). **Excluye pedidos en `order_status
IN ('canceled', 'unavailable')`** del conteo y del gasto total, porque no
representan una compra real completada.

### `vw_entregas_retrasos`
Grano: una fila por pedido **entregado** (`order_delivered_customer_date IS NOT
NULL`). Columnas: `order_id`, `order_status`, `order_purchase_timestamp`,
`order_estimated_delivery_date`, `order_delivered_customer_date`,
`dias_retraso` (positivo = llegó tarde, negativo/cero = a tiempo o antes),
`entrega_con_retraso` (0/1), `review_score_promedio`.

---

## Notas para generar SQL (SQLite)

- Diferencias de fechas en días: `julianday(fecha_a) - julianday(fecha_b)`
  (ej. `julianday(order_delivered_customer_date) -
  julianday(order_estimated_delivery_date)`).
- Agrupar por mes/año: `strftime('%Y-%m', order_purchase_timestamp)`.
- Solo se ejecutan consultas SELECT contra `db/olist.db` en modo **solo
  lectura**; nunca generes INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/ATTACH.
