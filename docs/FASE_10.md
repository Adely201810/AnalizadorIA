# Fase 10 — Chat libre: juez de sensatez + bitácora persistente de errores de esquema

Fecha: 2026-10-10 · Estado: **COMPLETA (con una limitación de la demostración real, ver abajo)** · Pruebas: `tests.test_bitacora` (4/4)

## Qué se implementó

### Juez de sensatez en el chat (`llm/juez.py: evaluar_sensatez`, `answer_question(juez_sensatez=…)`)
- Tras responder, el juez-LLM revisa **solo si el SQL tiene sentido** para la pregunta: columnas y tablas adecuadas, JOINs entre llaves del mismo tipo, nivel de agregación y filtros. No conoce ninguna referencia y **no juzga la cifra**.
- La UI (`app.py`, en el desplegable del detalle) y el CLI lo muestran con un texto fijo que **lo dice explícitamente** (`llm/juez.py: texto_revision`): *"Revisión automática del SQL (un segundo modelo revisó si la consulta tiene sentido para la pregunta; no comprueba que la cifra sea correcta)"*. Nunca dice "verificada". Una prueba lo comprueba (`test_revision_del_juez_y_texto_no_dice_verificado`).
- Se puede apagar con `TEXT2SQL_JUEZ_CHAT=0` (cuesta una llamada extra al LLM por pregunta).

### Bitácora persistente de errores de esquema (`llm/bitacora.py`)
- Registra cada uso de una columna o tabla inexistente, detectado por el validador (que ahora adjunta `detalles` estructurados a `SQLQualityError`) o por SQLite (`no such column/table`). Cada entrada lleva una **corrección concreta**: dónde existe de verdad esa columna, según el esquema real.
- **Archivo propio** (`runtime/bitacora_esquema.json`, fuera de git; `TEXT2SQL_BITACORA` para otra ruta). **Nunca** escribe en las tablas de Olist: la prueba comprueba que la fecha de modificación de `db/olist.db` no cambia.
- **Límites:** como mucho 100 entradas en el archivo (se descartan las menos recientes), 64 KB de archivo y **5 entradas de hasta 220 caracteres en el prompt** (las más frecuentes y recientes).
- **Uso en preguntas futuras:** las entradas se añaden al prompt **de usuario** del generador de SQL, no al de sistema, para no invalidar la caché del prefijo del esquema (Fase 4).
- Activa en el chat (`app.py`, `llm/cli.py`). **Desactivada en la evaluación**, para que las preguntas del oráculo no se "enseñen" entre sí y las corridas sean comparables.
- Una prueba detectó que se contaba dos veces la misma columna repetida en un SQL (`SELECT o.customer_state … GROUP BY o.customer_state` → `4 != 2`); corregido: cada error cuenta una vez por intento.

## Pruebas deterministas (`python -m unittest tests.test_bitacora -v`)
```
test_error_de_sqlite_sin_calificar ... ok
test_limites ... ok
test_registra_error_y_lo_usa_en_una_pregunta_distinta_posterior ... ok
test_revision_del_juez_y_texto_no_dice_verificado ... ok

----------------------------------------------------------------------
Ran 4 tests in 16.782s

OK
```
`test_registra_error_y_lo_usa_en_una_pregunta_distinta_posterior`: la pregunta A usa `orders.customer_state` (no existe) dos veces y queda registrado `columna:orders.customer_state` (veces=2, con "customers" en la corrección). La pregunta B, **distinta**, recibe la corrección en su prompt, el modelo guionado la sigue (`ok` en el 1.er intento) y el contador no sube.

## Demostración con el modelo real (`python -m eval.demo_bitacora`, llama3.1 8B)
El error real más frecuente en las corridas fue `no such column: customer_unique_id` (34 veces, sobre todo en n01).
```
=== 1. CONTROL: pregunta B sin bitácora ===
Pregunta: ¿Cuántos clientes únicos hicieron al menos un pedido entregado?
  intento 1: tipo=ok | error de esquema=False | detalle=''
    SQL: SELECT COUNT(DISTINCT customer_unique_id) FROM customers JOIN orders ON customers.customer_id = orders.customer_id WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL
Filas: [(93350,)] | descompuesta: False

=== 2. Pregunta A con bitácora (vacía al empezar) ===
Pregunta: ¿Qué porcentaje de los clientes únicos hizo más de un pedido válido (sin contar pedidos cancelados o no disponibles)?
¿El 1.er prompt de SQL trae la bitácora?: False
  intento 1: tipo=ejecucion | error de esquema=True | detalle='Error de SQLite al ejecutar la consulta: no such column: customer_unique_id'
    SQL: SELECT ROUND(100.0 * COUNT(DISTINCT customer_unique_id) / (SELECT COUNT(DISTINCT customer_unique_id) FROM vw_clientes_recurrentes), 2) AS porcentaje
  intento 2: tipo=ejecucion | error de esquema=True | detalle='Error de SQLite al ejecutar la consulta: no such column: customer_unique_id'
    SQL: SELECT ROUND(100.0 * COUNT(DISTINCT customer_unique_id) / (SELECT COUNT(*) FROM vw_clientes_recurrentes), 2) AS porcentaje
Filas: [] | descompuesta: False

Bitácora tras la pregunta A:
[
  {
    "clave": "columna:*.customer_unique_id",
    "mensaje": "La columna 'customer_unique_id' está en: customers, vw_clientes_recurrentes, vw_ventas_pedido.",
    "veces": 2,
    "primera": "2026-10-10T20:13:31",
    "ultima": "2026-10-10T20:13:37",
    "ejemplo_pregunta": "¿Qué porcentaje de los clientes únicos hizo más de un pedido válido (sin contar pedidos cancelados o no disponibles)?"
  }
]

=== 3. Pregunta B con bitácora ===
Pregunta: ¿Cuántos clientes únicos hicieron al menos un pedido entregado?
¿El 1.er prompt de SQL trae la bitácora?: True
Fragmento inyectado:
  Errores de esquema cometidos en consultas anteriores (no los repitas):
  - La columna 'customer_unique_id' está en: customers, vw_clientes_recurrentes, vw_ventas_pedido.
  intento 1: tipo=ok | error de esquema=False | detalle=''
    SQL: SELECT COUNT(DISTINCT customer_unique_id) FROM vw_ventas_pedido WHERE order_status = 'delivered'
Filas: [(93358,)] | descompuesta: False
```
Segundo intento, con una pregunta B2 más parecida al patrón que falla:
```
=== 4. CONTROL: pregunta B2 sin bitácora ===
Pregunta: ¿Qué porcentaje de los clientes únicos dejó al menos una reseña de 5 estrellas?
  intento 1: tipo=ok | error de esquema=False | detalle=''
=== 5. Pregunta B2 con bitácora ===
¿El 1.er prompt de SQL trae la bitácora?: True
  intento 1: tipo=ok | error de esquema=False | detalle=''
Bitácora al final: [('columna:*.customer_unique_id', 2)]
```

**Lectura honesta:**
- Con el modelo real quedan **demostrados el registro y el uso en una pregunta distinta**: el error de A se guardó con su corrección y llegó al prompt de B y B2, y ninguna repitió el error.
- **No queda demostrado que la bitácora lo *evite***: en los dos controles, sin bitácora, el modelo **tampoco** cometió el error. El efecto de evitarlo solo está probado con el cliente guionado.
- **Límite de la corrección:** en A, la causa real era un `SELECT` exterior **sin `FROM`** (de ahí `no such column`). La corrección registrada ("la columna está en…") es cierta, pero no diagnostica ese error.

## Juez de sensatez en el chat real
```
===== $ python -m llm.cli "¿Qué método de pago se usa en más pedidos válidos?"
Modelo: llama3.1:8b-instruct-q4_K_M | Ollama: http://localhost:11434

SQL generado:
  SELECT payment_type
FROM order_payments
GROUP BY payment_type
ORDER BY COUNT(*) DESC
LIMIT 1

Filas obtenidas: 1

Respuesta:
No pude redactar un resumen confiable; revisa la tabla de resultados.

Revisión automática del SQL (no comprueba la cifra): parece coherente. La consulta agrupa los pedidos por método de pago, ordena por la cantidad de pedidos en cada grupo en orden descendente y limita el resultado a un solo registro, que corresponde al método de pago más utilizado en pedidos válidos.

[exit code: 0]
```
El juez dijo "parece coherente" aunque el SQL **no filtra pedidos válidos**: es el mismo tipo de falso acierto medido en la Fase 8. Confirma que su revisión **no** debe presentarse como verificación, y por eso el texto de la UI lo advierte.
