# Línea base 00 — estado "tal como está"

| Campo | Valor |
|---|---|
| Fecha | 2026-10-10, 17:04:13 → 17:07:35 (3 min 22 s) |
| Modelo | `llama3.1:8b-instruct-q4_K_M` (Ollama 0.40.2, Vulkan, 100 % GPU) |
| Código | commit `5dd3215`; lógica de `llm/` y `eval/run_eval.py` sin cambios desde el commit inicial |
| Oráculo | `eval/ground_truth_olist.json` con las decisiones D-01 a D-04 aplicadas (pedido válido en q2/q6/q10; q4 con ≥500 pedidos) |
| Configuración | `temperature=0.1`, `num_ctx=8192`, `timeout=300 s`, `--max-retries 2` (en la práctica, máximo 1 reintento; ver DIAGNOSTICO.md, Fase 6), plantillas y fallback **activados** |
| Comando | `python eval/run_eval.py --output eval/baselines/baseline_00_actual.json` |
| Resultado detallado | `eval/baselines/baseline_00_actual.json` |

## Cifra real

**SQL correcto: 6/10 (60.0 %) · Texto confiable: 10/10 (100.0 %)**

## Por qué esta cifra probablemente está inflada

Es la cifra que da el evaluador actual. Al revisar las 10 respuestas, los propios datos de la corrida muestran **3 aciertos que no lo son**:

| Pregunta | Marcada | Lo que muestran los datos |
|---|---|---|
| q7 | ✅ | El SQL falló (usa `customer_state` en `orders`, donde no existe) y la respuesta fue el mensaje fijo `No logré armar una consulta…`. El evaluador buscó "SP" sin distinguir mayúsculas y lo encontró dentro de "re**sp**onder". |
| q5 | ✅ | El SQL calcula ambos promedios sobre pedidos **con** retraso (`WHERE vr.entrega_con_retraso = 1`); la respuesta dice "No, … tienen la misma calificación promedio, que es de 2,57", que es lo contrario de la referencia (2.57 frente a 4.29). Pasó porque 2.5665 cae en ±0.1 de 2.57. |
| q6 | ✅ | Promedia `payment_value` por fila de pago, no por pedido: 162.70 frente a 163.32. Pasó por la tolerancia del 2 % y la presencia de "credit_card". El propio pipeline descartó el resumen (`MENSAJE_RESUMEN_NO_CONFIABLE`). |

Sin esos 3, solo q1, q2 y q9 son aciertos inequívocos. Esto es una revisión manual, no una cifra oficial; la cifra honesta saldrá del evaluador endurecido (baseline_01).

Otras causas de inflación ya diagnosticadas (DIAGNOSTICO.md) que estaban activas en esta corrida:
- **Few-shot casi idénticos al oráculo:** el prompt traía ejemplos casi iguales a q2, q4, q5 y q8 (Jaccard de SQL de 0.667 con q2 y 0.714 con q8; ver docs/FASE_01.md). Aun así, q8 falló: el modelo copió el ejemplo de "retraso" (fecha estimada) en lugar de usar la fecha de compra.
- **Comparación en cualquier celda/texto:** la causa directa de q7, q5 y q6.
- **Plantillas/fallback activados:** en esta corrida ninguna pregunta se resolvió con plantilla, pero el evaluador no registraba el `origen`, así que no se podía saber.
- **"Texto confiable" 10/10:** también cuenta como confiables los mensajes fijos de error (no contienen cifras), así que no mide fidelidad útil.

## Salida exacta de la corrida

```
inicio: 2026-10-10 17:04:13
=== Evaluación Text-to-SQL | modelo=llama3.1:8b-instruct-q4_K_M | 10 preguntas ===

[1/10] q1_pedidos_totales: ¿Cuántos pedidos hay en total en la base de datos?
   SQL generado: SELECT COUNT(order_id) FROM orders
   Respuesta:    Hay un total de 99,441 pedidos en la base de datos. Esto se debe a que hay 99,441 pedidos registrados.
   SQL correcto: ✅  |  Texto confiable: ✅ — esperado≈99441, hallado=99441.0

[2/10] q2_categoria_mas_ingresos: ¿Qué categoría de producto (en inglés) generó más ingresos totales (suma de price de order_items, sin contar pedidos cancelados o no disponibles)?
   SQL generado: SELECT COALESCE(t.product_category_name_english, p.product_category_name) AS categoria, SUM(oi.price) AS total
FROM order_items oi
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name
WHERE oi.order_id NOT IN (SELECT order_id FROM orders WHERE order_status IN ('canceled', 'unavailable'))
GROUP BY categoria
ORDER BY total DESC
LIMIT 1
   Respuesta:    La categoría de producto que generó más ingresos totales es "health_beauty" con un total de R$1,255,695.13.
   SQL correcto: ✅  |  Texto confiable: ✅ — texto encontrado: ['health_beauty', 'beleza_saude'] | número OK (esperado≈1255695.13, hallado=1255695.13)

[3/10] q3_pct_clientes_recurrentes: ¿Qué porcentaje de clientes únicos (customer_unique_id) hizo más de un pedido válido (sin contar pedidos cancelados o no disponibles)?
   SQL generado: SELECT CAST(COUNT(DISTINCT customer_unique_id) AS REAL) * 100 / COUNT(DISTINCT customer_unique_id) 
FROM vw_clientes_recurrentes
WHERE es_recurrente = 1
   Respuesta:    El 100% de los clientes únicos que hicieron más de un pedido válido son recurrentes. Esto se debe a que el resultado muestra un valor de 100.0.
   SQL correcto: ❌  |  Texto confiable: ✅ — esperado≈3.04, hallado=None

[4/10] q4_categorias_mas_compra_unica: ¿Qué 5 categorías de producto (con nombre de categoría) tienen mayor proporción de clientes que les compraron una sola vez, entre las categorías con al menos 500 pedidos válidos (sin contar pedidos cancelados o no disponibles)?
   SQL generado: SELECT 
  COALESCE(t.product_category_name_english, p.product_category_name) AS categoria, 
  COUNT(DISTINCT v.customer_unique_id) AS clientes_de_una_compra
FROM 
  vw_ventas_pedido v 
  JOIN order_items oi ON oi.order_id = v.order_id 
  JOIN products p ON p.product_id = oi.product_id 
  LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name 
GROUP BY 
  categoria 
HAVING 
  COUNT(DISTINCT v.customer_unique_id) > 500 
ORDER BY 
  clientes_de_una_compra DESC 
LIMIT 5
   Respuesta:    Las 5 categorías de producto con mayor proporción de clientes que les compraron una sola vez son: "bed_bath_table", "health_beauty", "sports_leisure", "computers_accessories" y "furniture_decor". Esto se debe a que estas categorías tienen un número significativo de clientes que solo han realizado una compra.
   SQL correcto: ❌  |  Texto confiable: ✅ — texto NO encontrado: ['consoles_games', 'electronics', 'cool_stuff', 'small_appliances', 'construction_tools_construction'] | número no encontrado (esperado≈99.62, hallado=None)

[5/10] q5_retraso_baja_calificacion: ¿Los pedidos entregados con retraso tienen una calificación promedio más baja que los que llegan a tiempo?
   SQL generado: SELECT AVG(rv.review_score) AS calificacion_promedio_retraso, AVG(rv2.review_score) AS calificacion_promedio_atiempo
FROM order_reviews rv
JOIN orders o ON o.order_id = rv.order_id
JOIN vw_entregas_retrasos vr ON vr.order_id = o.order_id
JOIN order_reviews rv2 ON rv2.order_id = o.order_id
WHERE vr.entrega_con_retraso = 1
   Respuesta:    No, los pedidos entregados con retraso y los que llegan a tiempo tienen la misma calificación promedio, que es de 2,57.
   SQL correcto: ✅  |  Texto confiable: ✅ — esperado≈2.57, hallado=2.566525260316236

[6/10] q6_metodo_pago_mayor_venta_promedio: ¿Qué método de pago deja el mayor valor promedio de venta por pedido (sin contar pedidos cancelados o no disponibles)?
MENSAJE_RESUMEN_NO_CONFIABLE disparado | pregunta='¿Qué método de pago deja el mayor valor promedio de venta por pedido (sin contar pedidos cancelados o no disponibles)?' | respuesta_descartada='El método de pago que deja el mayor valor promedio de venta por pedido es el de tarjeta de crédito, con un valor promedio de R$162.703,94.' | filas=[('credit_card', 162.70393992490614)]
   SQL generado: SELECT payment_type, AVG(payment_value) AS valor_promedio
FROM order_payments
JOIN orders ON orders.order_id = order_payments.order_id
WHERE orders.order_status NOT IN ('canceled', 'unavailable')
GROUP BY payment_type
ORDER BY valor_promedio DESC
LIMIT 1
   Respuesta:    No pude redactar un resumen confiable; revisa la tabla de resultados.
   SQL correcto: ✅  |  Texto confiable: ✅ — texto encontrado: ['credit_card', 'tarjeta de crédito', 'tarjeta de credito'] | número OK (esperado≈163.32, hallado=162.70393992490614)

[7/10] q7_estado_mas_pedidos_entregados: ¿Cuál es el estado (customer_state) con más pedidos entregados?
   SQL generado: SELECT customer_state, COUNT(*) AS pedidos_entregados
FROM orders
WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL
GROUP BY customer_state
ORDER BY pedidos_entregados DESC
LIMIT 1
   Respuesta:    No logré armar una consulta que funcionara bien para responder eso; puede que la lógica no haya sido la correcta. ¿Podrías reformular la pregunta?
   SQL correcto: ✅  |  Texto confiable: ✅ — texto encontrado: ['SP', 'São Paulo', 'Sao Paulo'] | número no encontrado (esperado≈40501, hallado=None)

[8/10] q8_tiempo_promedio_entrega: ¿Cuál es el tiempo promedio de entrega, en días, de los pedidos entregados?
   SQL generado: SELECT ROUND(AVG(julianday(order_delivered_customer_date) - julianday(order_estimated_delivery_date)), 2)
FROM orders
WHERE order_delivered_customer_date IS NOT NULL AND order_status = 'delivered'
   Respuesta:    El tiempo promedio de entrega de los pedidos entregados es de aproximadamente -11,18 días. Esto se debe a que el promedio de entrega es negativo, lo que sugiere que la fecha de entrega se está calculando de manera incorrecta.
   SQL correcto: ❌  |  Texto confiable: ✅ — esperado≈12.56, hallado=None

[9/10] q9_pedidos_sin_entrega: ¿Cuántos pedidos no tienen fecha de entrega registrada (no fueron entregados al cliente)?
   SQL generado: SELECT COUNT(*) 
FROM orders 
WHERE order_delivered_customer_date IS NULL
   Respuesta:    Hay 2965 pedidos que no tienen fecha de entrega registrada. Esto significa que estos pedidos no fueron entregados al cliente.
   SQL correcto: ✅  |  Texto confiable: ✅ — esperado≈2965, hallado=2965.0

[10/10] q10_ticket_promedio_pedido: ¿Cuál es el ticket promedio (precio + flete) por pedido, sin contar pedidos cancelados o no disponibles?
   SQL generado: SELECT AVG(price + freight_value) 
FROM order_items 
WHERE order_id IN (SELECT order_id FROM orders WHERE order_status NOT IN ('canceled', 'unavailable'))
   Respuesta:    El ticket promedio por pedido es de R$140.37. Esto se debe a que el promedio de la suma del precio y el flete de los pedidos es de 140.36919411958857.
   SQL correcto: ❌  |  Texto confiable: ✅ — esperado≈160.24, hallado=None

=== RESULTADO FINAL: SQL correcto 6/10 (60.0%)  |  Texto confiable 10/10 (100.0%) ===
Resultados detallados guardados en: eval\baselines\baseline_00_actual.json
[exit code: 0]
fin: 2026-10-10 17:07:35
```
