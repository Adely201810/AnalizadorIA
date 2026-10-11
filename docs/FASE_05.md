# Fase 5 — Las 10 necesidades de negocio como fuente única de verdad

Fecha: 2026-10-10 · Estado: **COMPLETA** · Verificación: SQL 10/10, pandas 10/10, pruebas 37/37

## Punto de partida (dos conjuntos desconectados)

| Dashboard (`dashboard/queries.py`, necesidades compuestas) | Oráculo v1 (`ground_truth_olist.json`, hechos sueltos) |
|---|---|
| q01 Retención: % recurrentes, comparación, qué compran, dónde recompran | q1 total de pedidos |
| q02 Desde cuántos días de retraso cae la calificación | q2 categoría con más ingresos |
| q03 Concentración en categorías **y** vendedores | q3 % clientes recurrentes ↔ **dash q01** |
| q04 Vendedores con mucho ingreso y mala calificación o entregas tardías | q4 categorías con más compra única ↔ **dash q01/q09** (recompra) |
| q05 Flete por estado **y** categoría | q5 calificación con retraso vs a tiempo ↔ **dash q02** |
| q06 Método, cuotas **y** categorías a plazos | q6 método con mayor ticket ↔ **dash q06** (parcial) |
| q07 Meses, meses incompletos **y** crecimiento 2017→2018 | q7 estado con más pedidos entregados |
| q08 Insatisfacción: producto vs logística | q8 días promedio de entrega |
| q09 Audiencia satisfecha de compra única | q9 pedidos sin entrega |
| q10 Clientes por vendedor **y** logística por estado | q10 ticket promedio |

Solo 3 preguntas del oráculo se parecían a una necesidad del dashboard (q3, q4, q5), y solo en parte q6.

## Qué se implementó
- **`eval/ground_truth_olist.json` v2**: 10 necesidades, una por pestaña, cada una con UNA consulta sobre tablas base. Detalle de la reescritura y de las preguntas de v1 que salen en **D-10**; simplificaciones en **D-11**. `resultado_esperado` se generó **ejecutando** cada SQL. La v1 queda en `eval/ground_truth_olist_v1.json` (referencia de las líneas base anteriores).
- **Dashboard** (`pages/1_Dashboard.py`): cada pestaña empieza con la pregunta de la necesidad, la tabla de su respuesta de referencia y el SQL (en un desplegable). El Resumen muestra "Pregunta de referencia", "Respuesta de referencia" y, aparte, el "Análisis ampliado" que ya existía.
- **`dashboard/verify_pandas.py`**: recalcula con pandas, **desde los CSV**, las 10 necesidades y las compara contra `resultado_esperado` con el mismo árbitro de la evaluación, en **todas** las columnas.
- **`eval/compute_ground_truth.py`**: además de mostrar, comprueba que el SQL sigue dando `resultado_esperado` (sale con código 1 si no).
- **Few-shot** sin las métricas de v2 (**D-12**).
- Los ejemplos de la app de chat salen de v2 (`app.py` lee las preguntas del oráculo).

Antes de fijar cada SQL se comprobó que no hubiera empates en el primer puesto (salida de la exploración):
```
N05 (3.4 s): [('RR', 28.55), ('MA', 26.32), ('RO', 24.75)]
N06 (2.1 s): [('credit_card', 75618), ('boleto', 19539), ('voucher', 3745)]
N07 (0.9 s): [('2017-11', 1003862.14), ('2018-04', 993592.98), ('2018-05', 992871.75)]
N08 (3.0 s): [('fashion_male_clothing', 22.73, 110), ('office_furniture', 17.92, 1267), ('construction_tools_safety', 17.68, 164)]
N10 (4.4 s): [('BA', 170.74, 3244, 19), ('CE', 108.42, 1301, 12), ('ES', 84.78, 1950, 23)]
N02_vista (1.4 s): [(2.57, 4.29)]
```
(N02 sobre tablas base da lo mismo que la vista del chatbot, `vw_entregas_retrasos`.)

## Verificación (salida exacta)

`python eval/compute_ground_truth.py`:
```
[OK] n01_pct_clientes_recurrentes           -> [(3.04,)]
[OK] n02_calificacion_retraso_vs_a_tiempo   -> [(2.57, 4.29)]
[OK] n03_pct_ingresos_top5_categorias       -> [(39.82,)]
[OK] n04_vendedores_mala_calificacion       -> [(24,)]
[OK] n05_estado_mayor_peso_flete            -> [('RR', 28.55)]
[OK] n06_metodo_pago_mas_usado              -> [('credit_card', 75618)]
[OK] n07_mes_mayores_ingresos               -> [('2017-11', 1003862.14)]
[OK] n08_categoria_mas_resenas_1_estrella   -> [('fashion_male_clothing', 22.73, 110)]
[OK] n09_categorias_mas_compra_unica        -> [('consoles_games', 1054, 1050, 99.62), ('electronics', 2543, 2533, 99.61), ('cool_stuff', 3616, 3600, 99.56), ('small_appliances', 622, 619, 99.52), ('construction_tools_construction', 746, 742, 99.46)]
[OK] n10_estado_mas_clientes_por_vendedor   -> [('BA', 170.74, 3244, 19)]
[exit code: 0]
```

`python -m dashboard.verify_pandas` (**10/10**):
```
=== Verificación pandas (CSV) vs SQL (olist.db) ===
[OK] Clientes únicos con pedido válido: pandas=94,990.00 | sql=94,990.00 | diff=0.0000
[OK] % clientes recurrentes: pandas=3.04 | sql=3.04 | diff=0.0000
[OK] Ingresos categoría top (R$): pandas=1,255,695.13 | sql=1,255,695.13 | diff=0.0000
[OK] % ingresos top 5 categorías: pandas=39.82 | sql=39.82 | diff=0.0032
[OK] % pedidos tardíos (global): pandas=8.11 | sql=8.11 | diff=0.0000

=== Verificación pandas (CSV) vs oráculo (eval/ground_truth_olist.json) ===
[OK] n01_pct_clientes_recurrentes: pandas=[[3.04]] | oráculo=[[3.04]]
[OK] n02_calificacion_retraso_vs_a_tiempo: pandas=[[2.57, 4.29]] | oráculo=[[2.57, 4.29]]
[OK] n03_pct_ingresos_top5_categorias: pandas=[[39.82]] | oráculo=[[39.82]]
[OK] n04_vendedores_mala_calificacion: pandas=[[24]] | oráculo=[[24]]
[OK] n05_estado_mayor_peso_flete: pandas=[['RR', 28.55]] | oráculo=[['RR', 28.55]]
[OK] n06_metodo_pago_mas_usado: pandas=[['credit_card', 75618]] | oráculo=[['credit_card', 75618]]
[OK] n07_mes_mayores_ingresos: pandas=[['2017-11', 1003862.14]] | oráculo=[['2017-11', 1003862.14]]
[OK] n08_categoria_mas_resenas_1_estrella: pandas=[['fashion_male_clothing', 22.73, 110]] | oráculo=[['fashion_male_clothing', 22.73, 110]]
[OK] n09_categorias_mas_compra_unica: pandas=[['consoles_games', 1054, 1050, 99.62], ['electronics', 2543, 2533, 99.61], ['cool_stuff', 3616, 3600, 99.56], ['small_appliances', 622, 619, 99.52], ['construction_tools_construction', 746, 742, 99.46]] | oráculo=[['consoles_games', 1054, 1050, 99.62], ['electronics', 2543, 2533, 99.61], ['cool_stuff', 3616, 3600, 99.56], ['small_appliances', 622, 619, 99.52], ['construction_tools_construction', 746, 742, 99.46]]
[OK] n10_estado_mas_clientes_por_vendedor: pandas=[['BA', 170.74, 3244, 19]] | oráculo=[['BA', 170.74, 3244, 19]]
[exit code: 0]
```

Pruebas (`tests.test_comparador tests.test_fewshot_disjunto tests.test_clasificacion tests.test_limite_ejecucion`):
```
Ran 37 tests in 116.135s

OK
```
Incluye una prueba nueva que comprueba que las 10 referencias de v2 dan `resultado_esperado` y que el árbitro acepta cada una contra sí misma.

Few-shot frente a v2 (`python -m eval.similitud`): máximo de texto 0.214 y de SQL 0.308, ambos bajo los umbrales (0.25 / 0.5). Con el set anterior, frente a v2: flete por estado 0.333 (texto), flete por estado y categoría 0.308, Pareto de categorías 0.300.

Dashboard (Streamlit, revisado en el navegador): las 10 pestañas muestran `Necesidad N (pregunta de referencia): …` con su tabla. El Resumen muestra las columnas nuevas (p. ej. `pct_recurrentes: 3.04`). La página no mostró errores (`err: []`) y tiene 14 tablas.

## Decisiones propias
D-10 (oráculo v2 y reescritura de las necesidades), D-11 (N4 y N10), D-12 (few-shot). La pregunta de N9 (q4) se mantiene tal cual, según la decisión D-02 del usuario, que la marcó como de **baja capacidad discriminante** (todas las categorías ≈ 99.5 %). Sigue siendo candidata a reemplazo; no la cambié porque el plan pedía mantenerla.

## Pendiente
La precisión del modelo sobre v2 se mide en la Fase 4 (benchmark), con el mismo protocolo para todos los modelos.
