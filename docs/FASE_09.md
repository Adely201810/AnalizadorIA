# Fase 9 — La cadena de intentos se corta en el primer ACIERTO

Fecha: 2026-10-10 · Estado: **COMPLETA (con un hallazgo sobre la tolerancia de porcentajes)** · Código: `a6b75fb` (+ `--ids` en `run_eval.py`)

## Qué se implementó
Antes, el bucle (`text_to_sql.py:493-496` original) aceptaba el **primer SQL que corría y devolvía filas**, fuera correcto o no. Ahora `answer_question(..., verificador=…)` recibe un verificador que, tras cada ejecución, decide si el resultado es correcto:
- **acepta** → la cadena se corta ahí (aunque queden intentos);
- **rechaza** → se envía una pista (Fase 7) y se gasta otro intento.

En la evaluación (`run_eval.py --cadena`) el verificador es el **árbitro determinista** contra la referencia. En el chat no hay referencia: sin verificador, se mantiene "primer SQL que corre y devuelve filas" (D-14).

## Demostración determinista (`tests/test_cadena.py::TestCorteEnPrimerAcierto`)
- Sin verificador: con un guion MAL, BIEN, … se queda con el primer SQL (incorrecto, `100.0`), es decir, 1 intento.
- Con verificador y N=4 sobre un guion MAL, BIEN, MAL, MAL: se detiene en el 2.º intento (`verificado` = `[False, True]`), se piden **solo 2 SQL** al modelo y el resultado es `3.04`.

## Corrida a temperatura alta (`eval/baselines/fase9_n3_cadena_temp08.json`)
`--intentos 3 --cadena --feedback generico --temperature 0.8`. Inicio 19:51:54, fin 19:59:34.
```
=== RESULTADO FINAL: correctas 1/10 (10.0%) | texto respaldado 5/10 | latencia media 42.86 s | origen {'llm': 7, 'sin_origen': 3} | recursos {'size_bytes': 5804392447, 'size_vram_bytes': 5804392447, 'pct_gpu': 100.0, 'context_length': 8192} ===
=== CLASIFICACIÓN FINAL (por pregunta): {'ok': 1, 'ejecucion': 2, 'semantico': 7, 'seguridad': 0, 'infra': 0} ===
n01_pct_clientes_recurrentes | correcto True | intentos 1 [('ok', True)]
n03_pct_ingresos_top5_categorias | correcto False | intentos 3 [('semantico', False), ('semantico', False), ('semantico', False)]
n07_mes_mayores_ingresos | correcto False | intentos 3 [('semantico', False), ('semantico', False), ('semantico', False)]
n08_categoria_mas_resenas_1_estrella | correcto False | intentos 3 [('semantico', False), ('semantico', False), ('semantico', False)]
```
(extracto; el JSON tiene las 10.) n01 acierta en el 1.er intento con `3.04` exacto y **se corta** (1 de 3 intentos). Las preguntas rechazadas agotan los 3.

## Corridas dirigidas para capturar "falla → acierta → corta" (`eval/baselines/fase9_dirigida_r*.json`)
En las corridas completas ningún acierto llegó después de un rechazo. Para buscarlo con el modelo real: `--ids n01 n07 n03 --intentos 5 --cadena --feedback generico --temperature 0.9`, hasta 3 repeticiones:
```
r1 [('n01', [None, None, True]), ('n03', [None, False, False, False, False]), ('n07', [False, False, False, False, False])]
r2 [('n01', [None, None, None, False, False]), ('n03', [None, None, None, None, None]), ('n07', [False, False, False, False, False])]
r3 [('n01', [False, False, False, True]), ('n03', [None, None, None, None, None]), ('n07', [True])]
CASO FALLO->ACIERTO ENCONTRADO en r3
```
(`None` = el intento falló antes de llegar al verificador: error de ejecución o 0 filas.)

r3, n01 (N=5): 3 rechazos del árbitro, aceptado en el **intento 4** y **cortado ahí** (no se usó el 5.º):
```
--- intento 1 | tipo ok | verificado False
    SQL: SELECT ROUND(100.0 * COUNT(DISTINCT c.customer_unique_id) / (SELECT COUNT(DISTINCT customer_unique_id) FROM vw_clientes_recurrentes), 2) AS porcentaje_recurrencia FROM customers c
    pista enviada al siguiente intento: El resultado tiene la forma esperada, pero sus valores no son los correctos: revisa la lógica del cálculo.
--- intento 2 | tipo ok | verificado False
    SQL: SELECT ROUND(100.0 * (SELECT COUNT(DISTINCT customer_unique_id) FROM customers c WHERE c.customer_unique_id IN (SELECT customer_unique_id FROM vw_clientes_recurrentes)), 2) AS porcentaje_recurrencia
    pista enviada al siguiente intento: El resultado tiene la forma esperada, pero sus valores no son los correctos: revisa la lógica del cálculo.
--- intento 3 | tipo ok | verificado False
    SQL: SELECT ROUND( 100.0 * COUNT(DISTINCT customer_unique_id) / (SELECT COUNT(DISTINCT customer_unique_id) FROM customers), 2) AS porcentaje_recurrencia FROM vw_clientes_recurrentes
    pista enviada al siguiente intento: El resultado tiene la forma esperada, pero sus valores no son los correctos: revisa la lógica del cálculo.
--- intento 4 | tipo ok | verificado True
    SQL: SELECT ROUND( 100.0 * COUNT(DISTINCT customer_unique_id) / (SELECT COUNT(DISTINCT customer_unique_id) FROM customers), 2) AS porcentaje_recurrencia FROM ( SELECT DISTINCT customer_unique_id FROM vw_clientes_recurrentes WHERE es_recurrente = 1 ) AS clientes_recurrentes
filas finales: [[3.01]] | referencia: [[3.04]] | correcto: True | coincide (columna referencia -> columna modelo: {0: 0})
```
**El mecanismo de corte funciona**: se detuvo en la primera aceptación del árbitro.

### ⚠ Hallazgo: esa aceptación es un FALSO ACIERTO por la tolerancia de porcentajes
`3.01` no es la cifra correcta redondeada: es **otro cálculo**, con un denominador equivocado (todos los clientes, incluidos los que solo tienen pedidos cancelados):
```
recurrentes/clientes con pedido válido: (2888, 94990, 3.0403)
recurrentes/todos los clientes      : (2888, 96096, 3.0053)
```
La diferencia (0.03 puntos) cae dentro de la tolerancia de porcentajes **≤ 0.05 puntos** que fijó el plan, así que el árbitro lo aceptó. Pasa lo mismo en r1 (`[[3.01]]`). Revisión de **todos** los aciertos de todas las corridas: estos dos son los únicos no exactos; el resto coincide exactamente con la referencia.

**No cambié la tolerancia**, porque la fijó el usuario. **Recomendación (D-17):** bajar la tolerancia de porcentajes a ≤ 0.006 puntos, que solo admite diferencias de redondeo a 2 decimales. Con ella, estos dos casos se rechazan y ningún otro acierto cambia.

## Lectura
- El corte en el primer acierto está implementado y demostrado: de forma determinista con un caso verdadero, y con el modelo real con un caso cuyo acierto resultó ser un falso positivo de la tolerancia.
- Con este modelo, la cadena casi nunca encuentra un acierto después de un rechazo (ver FASE_07.md).
