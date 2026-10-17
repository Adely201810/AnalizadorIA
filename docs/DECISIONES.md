# Registro de decisiones

Cada entrada: decisión, alternativas, motivo, cómo revertirla. **U** = decidida por el usuario; **C** = decidida por Claude en modo autónomo (conviene revisarla).

---

## D-01 (U) "Pedido válido" excluye `canceled`/`unavailable` en todo el proyecto
- **Decisión:** ingresos, pagos y ticket se calculan solo sobre pedidos con `order_status NOT IN ('canceled','unavailable')`. Aplicado a las preguntas q2, q6 y q10 del oráculo y a q06 del dashboard (antes, sus agregados de pagos incluían todos los estatus).
- **Cambios de valor en el oráculo:**

  | Pregunta | Antes | Después | Cambio |
  |---|---|---|---|
  | q2 categoría con más ingresos (health_beauty) | 1,258,681.34 | 1,255,695.13 | −2,986.21 (−0.237 %) |
  | q6 método de pago con mayor promedio (credit_card) | 163.94 | 163.32 | −0.62 (−0.378 %) |
  | q10 ticket promedio por pedido | 160.58 | 160.24 | −0.34 (−0.212 %) |

  Dashboard q06: el ticket promedio por método pasa a credit_card 163.32, boleto 144.67, debit_card 140.21 y voucher 93.42.
- **Alternativas:** incluir todos los estatus (definición anterior de q2/q6/q10).
- **Revertir:** quitar el `JOIN orders … WHERE order_status NOT IN (…)` de esas tres referencias y de `dashboard/queries.py:q06`, y restaurar los valores de la tabla.

## D-02 (U) q4 exige ≥ 500 pedidos válidos por categoría
- **Decisión:** el umbral pasa de "≥ 50 clientes" a "≥ 500 pedidos válidos por categoría". El top 5 queda sin empates: consoles_games 99.62, electronics 99.61, cool_stuff 99.56, small_appliances 99.52, construction_tools_construction 99.46 (6.º: luggage_accessories 99.41).
- **Advertencia:** la pregunta **discrimina poco**, porque todas las categorías rondan el 99.5 % (la recompra global es ≈3 %) y el top se separa por centésimas. Es candidata a reemplazo en la Fase 5.
- **Revertir:** restaurar el SQL anterior de q4 desde git (commit previo a este cambio).

## D-03 (C) q4 excluye explícitamente los productos sin categoría
- **Problema detectado:** al verificar con pandas, el grupo "sin categoría" (NULL; 1,437 pedidos, 99.58 %) entraba 4.º en el top 5 de pandas, pero no en el SQL. Causa: el SQL une por `categoria` y en SQLite `NULL = NULL` es falso, así que el JOIN lo descartaba en silencio.
- **Decisión:** excluirlo de forma explícita (`categoria_ingles IS NOT NULL` en el SQL y `notna()` en pandas), y decir "con nombre de categoría" en la pregunta.
- **Motivo:** "sin categoría" no es una categoría sobre la que el negocio pueda actuar, y el comportamiento ya no depende de un efecto accidental del JOIN.
- **Alternativas:** incluirlo como `sin_categoria`; el top 5 cambiaría (entraría en 4.º lugar).
- **Revertir:** quitar el `IS NOT NULL` y usar `COALESCE(categoria, 'sin_categoria')` en ambos lados.

## D-04 (C) q2: la pregunta dice explícitamente "sin contar pedidos cancelados o no disponibles"
- **Motivo:** que pregunta y referencia digan lo mismo; el modelo no debe adivinar la definición. Se aplicó igual a q6 y q10.
- **Revertir:** quitar esa frase de las preguntas en `eval/ground_truth_olist.json`.

## D-05 (C) Disyunción few-shot ↔ oráculo medida con Jaccard léxico
- **Decisión:** un ejemplo few-shot es aceptable si su Jaccard con **toda** pregunta del oráculo es < 0.25 en texto y < 0.5 en SQL (`tests/test_fewshot_disjunto.py`). Los umbrales se calibraron con la matriz previa a la separación (duplicados: ≥ 0.294 / ≥ 0.667; resto: ≤ 0.167 / ≤ 0.389).
- **Alternativas:** similitud por embeddings (requiere descargar un modelo) o solo revisión manual.
- **Motivo:** es reproducible, no requiere descargas y separa con claridad los casos observados. Como no es una garantía semántica, se complementa con revisión manual.
- **Revertir:** borrar el test; los ejemplos originales están en git (commit `0982d27`).

## D-06 (C) Tolerancias del árbitro determinista por tipo de columna
- **Decisión** (`eval/comparador.py`): conteo exacto; dinero ≤ 0.01 o ≤ 0.1 % de la referencia; porcentaje ≤ 0.05 puntos (se acepta también la escala de fracción, 0.0304 = 3.04 %); decimal (días, calificaciones) ≤ 0.01; texto igual sin distinguir mayúsculas.
- **Motivo:** las tres primeras las fijó el plan. Para "decimal" se eligió 0.01 porque las referencias están redondeadas a 2 decimales. La escala de fracción se acepta porque es la misma cifra expresada de otra forma, no otra respuesta.
- **Alternativas:** exigir igualdad exacta a 2 decimales (penalizaría al modelo por no usar `ROUND`), o mantener tolerancias por pregunta (la causa de la inflación de baseline_00).
- **Revertir:** cambiar las constantes `TOL_*` de `eval/comparador.py`.

## D-07 (C) Estructura estricta: mismas filas y columnas requeridas por pregunta
- **Decisión:** el modelo debe devolver el mismo número de filas que la referencia; cada columna marcada en `tipos_columnas` debe aparecer (en cualquier posición; se permiten columnas extra). Un resultado "transpuesto" (por ejemplo, q5 con 2 filas en lugar de 2 columnas) cuenta como fallo.
- **Columnas requeridas = lo que la pregunta pide explícitamente:** q4 solo exige las categorías, en orden (no los conteos); q7 solo el estado. A q2 se le añadió "y cuánto suman" y a q6 "y de cuánto es ese promedio", porque su valor numérico siempre formó parte del oráculo.
- **Alternativas:** comparar solo la primera columna o aceptar transposiciones (más permisivo, más lógica ad hoc).
- **Revertir:** poner `null` en `tipos_columnas` para dejar de exigir una columna; quitar las frases añadidas a q2/q6.

## D-08 (C) Límite de 60 s para ejecutar el SQL generado por el modelo
- **Problema real:** en la primera corrida de baseline_01, el SQL de q4 quedó ejecutándose más de 10 min (el proceso de Python consumió CPU sin parar, sin llamadas a Ollama desde las 17:20:29). `execute_readonly` no tenía límite de tiempo.
- **Decisión:** se corta la consulta desde dentro de SQLite (`set_progress_handler`) pasados `TEXT2SQL_LIMITE_EJECUCION_S` (60 s por defecto) y el error se trata como un error de ejecución más (se reintenta con ese mensaje). Las consultas de referencia del oráculo no tienen límite.
- **Motivo:** la consulta de referencia más lenta tarda 9.93 s; 60 s es 6 veces eso.
- **Revertir:** `TEXT2SQL_LIMITE_EJECUCION_S=0` desactiva el límite.

## D-09 (C) Reglas de clasificación de fallos (Fase 2)
- **Decisión:** 0 filas → `semantico` (corre, pero no responde); SQL vacío o texto en lugar de SQL (p. ej. una negativa del modelo) → `ejecucion` (no hay SQL ejecutable), no `seguridad`; literal inventado o JOIN entre dominios → `semantico`; tabla o columna inexistente → `ejecucion`; pregunta descompuesta en sub-consultas → `semantico`; excepción de Python sin intentos registrados → `infra`.
- **Motivo:** las definiciones del plan (ejecución = no corre; semántico = corre pero responde otra cosa) aplicadas a cada rama existente del pipeline.
- **Alternativas:** tratar 0 filas como `ejecucion`, o las negativas como `seguridad` (lo que pasaba antes del ajuste).
- **Revertir:** `clasificar_excepcion` en `llm/text_to_sql.py` y `clasificar_intentos` en `eval/run_eval.py`.

## D-10 (C) Oráculo v2 = las 10 necesidades del dashboard, una consulta cada una (Fase 5)
- **Decisión:** la fuente única es `eval/ground_truth_olist.json` v2, con una necesidad por pestaña del dashboard. Cada una tiene `sql_referencia` (una sola consulta sobre tablas base), `tipos_columnas`, `orden_importa` y `resultado_esperado`. El dashboard la lee y muestra su respuesta de referencia en cada pestaña; `run_eval.py` la usa como oráculo. La v1 queda en `eval/ground_truth_olist_v1.json` (referencia de baseline_00, baseline_01 y fase2).
- **Cómo se reescribieron las necesidades compuestas** (se conservó lo central de cada una, alineado con la "respuesta clave" que ya mostraba el dashboard):

  | Pestaña | Necesidad compuesta (dashboard) | Pregunta única (v2) | Referencia |
  |---|---|---|---|
  | 1 Retención | % recurrentes + comparación + qué compran + dónde | % de clientes con >1 pedido válido (= q3 de v1) | 3.04 |
  | 2 Retraso vs reseñas | umbral de días donde cae la calificación | calificación promedio con retraso vs a tiempo (= q5 de v1, reescrita sobre tablas base) | 2.57 / 4.29 |
  | 3 Concentración | categorías **y** vendedores | % de ingresos de las 5 categorías top | 39.82 % |
  | 4 Vendedores problemáticos | top 25 % de ingresos **y** (calif < 3.5 **o** > 15 % tardías) | nº de vendedores con ≥ 30 pedidos válidos y calificación < 3.5 | 24 |
  | 5 Flete | estados **y** categorías | estado con mayor flete/precio | RR 28.55 % |
  | 6 Pagos | método, cuotas **y** categorías a plazos | método usado en más pedidos válidos | credit_card 75,618 |
  | 7 Estacionalidad | meses, incompletos **y** crecimiento interanual | mes con más ingresos | 2017-11, 1,003,862.14 |
  | 8 Insatisfacción | % 1 estrella **y** clasificación producto/logística | categoría (≥ 100 reseñas) con mayor % de 1 estrella | fashion_male_clothing 22.73 % |
  | 9 Recompra | audiencia satisfecha de compra única | q4 de v1 (top 5 compra única, ≥ 500 pedidos), según la decisión D-02 del usuario | consoles_games … |
  | 10 Oportunidad geográfica | clientes por vendedor **y** logística | estado (≥ 10 vendedores activos) con más clientes por vendedor | BA 170.74 |
- **Preguntas de v1 que salen del oráculo:** q1 (total de pedidos), q2 (categoría con más ingresos), q6 (método con mayor ticket), q7 (estado con más entregas), q8 (días de entrega), q9 (pedidos sin entrega) y q10 (ticket promedio). Son hechos simples, no necesidades del dueño.
- **Revertir:** copiar `eval/ground_truth_olist_v1.json` sobre `eval/ground_truth_olist.json`; quitar `bloque_necesidad_oraculo` de `pages/1_Dashboard.py`.

## D-11 (C) Necesidad 4 simplificada (solo calificación) y Necesidad 10 con ≥ 10 vendedores
- **N4:** el criterio del dashboard (top 25 % de ingresos **y** (calif < 3.5 **o** tardías > 15 %), contando pedidos de todos los estatus) es una consulta con percentiles y dos condiciones; se dejó solo "≥ 30 pedidos válidos y calificación promedio por pedido < 3.5" (24 vendedores). El dashboard conserva su análisis ampliado (13 vendedores) en la misma pestaña.
- **N10:** sin mínimo, el ranking lo encabezan estados con **un solo vendedor** (PA: 944 clientes por 1 vendedor), lo que no es una oportunidad comparable. Con ≥ 10 vendedores activos, el primero es BA (170.74).
- **Revertir:** cambiar los umbrales en `sql_referencia` y regenerar `resultado_esperado`.

## D-12 (C) Few-shot sin las métricas del oráculo v2
- **Decisión:** se retiró todo ejemplo que calcule **la misma métrica** que una necesidad, aunque sea en otra dimensión: los 3 de flete/precio (≈ N5), los 2 de Pareto (≈ N3), % de reseñas de 1-2 estrellas (≈ N8), vendedores por estado (componente de N10), umbral de retraso vs reseñas (≈ N2) y "mis clientes recurrentes" (con `es_recurrente`, N1 es trivial). Se reemplazaron por ejemplos con la misma **técnica** (julianday, LEFT JOIN, promedio por pedido, literal de enum, razón de sumas, ranking con `RANK() OVER`) sobre métricas que no se evalúan.
- **Motivo:** la prueba léxica (D-05) solo marcaba 3 de ellos; el resto era fuga de método, no de texto.
- **Efecto esperado:** puede bajar la precisión en flete y concentración, que antes tenían ejemplo casi exacto. Es la medida honesta.
- **Revertir:** restaurar `EJEMPLOS_FEW_SHOT` desde git (commit `f23c019`).

## D-13 (C) `n_intentos` reemplaza a `max_retries`; por defecto 2
- **Decisión:** `answer_question(n_intentos=N)` = intentos TOTALES (N=1 sin reintentos). Cada problema (error de ejecución/calidad, 0 filas, Ollama caído, rechazo del verificador) consume un intento; seguridad corta siempre. Por defecto N=2 (variable `TEXT2SQL_N_INTENTOS`), que reproduce el comportamiento **efectivo** anterior (máximo 2 intentos) y no alarga la latencia del chat. `run_eval.py --max-retries` se sustituye por `--intentos`.
- **Alternativas:** mantener `max_retries` con su significado corregido (N-1); subir el valor por defecto a 3 (más latencia en el chat, sin datos aún de que ayude sin verificador).
- **Revertir:** `TEXT2SQL_N_INTENTOS=3` para más reintentos; el código anterior está en git.

## D-14 (C) Cadena de intentos con verificador; el juez opina solo si se pide
- **Decisión:** el corte "en el primer acierto" (Fase 9) existe solo donde hay árbitro (evaluación, `--cadena`). En el chat no hay referencia, así que se acepta el primer SQL que corre y devuelve filas. El juez-LLM (`llm/juez.py`) es un componente separado: `opinar` solo con `--juez` (para medirlo contra el árbitro), `diagnosticar` solo con `--feedback juez`. Nunca decide el veredicto.
- **Motivo:** el juez es una llamada extra al LLM por intento; una prueba detectó que se pedía su opinión aunque nadie la usara (`test_juez_que_filtra_el_valor…`).

## D-15 (C) Pistas sin cifras + guarda que censura formas de la referencia
- **Decisión:** la pista traduce el motivo del árbitro a un texto **sin números** (el árbitro informa cuántas filas tiene la referencia; eso no se pasa). La guarda `eval/pistas.py:censurar` reemplaza por `[valor omitido]` cualquier forma escrita de los valores comparados: 0-3 decimales, coma o punto decimal, separadores de miles y escalas ×100 y ÷100. Se excluyen los enteros < 10 y los textos de menos de 3 caracteres, porque aparecen en cualquier frase ("5 categorías").
- **Limitación:** una referencia que sea un entero < 10 no queda protegida por la guarda. En el oráculo v2 no hay ninguna (el entero más chico es 24).
- **Revertir:** `--feedback ninguno` desactiva toda pista semántica.

## D-16 (C) Protocolo del benchmark: 1 repetición, worktree aislado; no se cambia el modelo
- **Decisión:** 1 repetición por modelo (se estimaban ~25 min por corrida por la lentitud anómala de llama3.1), desde un git worktree fijo (`4562e4e`), para que los cambios de código en paralelo no afectaran la comparación. El modelo por defecto sigue siendo `llama3.1:8b-instruct-q4_K_M` (instrucción del usuario).
- **Revertir/ampliar:** `python -m eval.benchmark_modelos --modelos … --repeticiones 3`, después de reiniciar el equipo y con el oráculo ampliado.

## D-17 (U, resuelta en la etapa 2: tolerancia = 0.006) La tolerancia de porcentajes (≤ 0.05 puntos) aceptaba un cálculo distinto
- **Hallazgo (Fase 9):** el árbitro aceptó `3.01` para n01 (referencia `3.04`). Es otro cálculo, con un denominador equivocado: 2,888 / 96,096 en vez de 2,888 / 94,990. Pasó porque 0.03 < 0.05.
- **Decisión:** **no** se cambió la tolerancia, porque la fijó el usuario en el plan. Se documenta y se recomienda.
- **Recomendación:** ≤ 0.006 puntos (solo diferencias de redondeo a 2 decimales). Con ella, los 2 casos `3.01` se rechazan y ningún otro acierto de las corridas cambia (todos los demás son exactos).
- **Aplicar:** `TOL_PORCENTAJE = 0.006` en `eval/comparador.py` y volver a correr la evaluación.

## D-18 (C) Dashboard: selector de sección en vez de pestañas; no se aplican índices
- **Selector:** `st.tabs` ejecuta las 11 pestañas en cada carga (≈193-221 s en frío). Con un selector (`st.radio`), solo se calcula la sección elegida (≈25-30 s la carga inicial). Contrapartida: cambiar de sección dispara el cálculo de esa sección (q01 ≈30-40 s la primera vez; después queda en caché).
- **Índices:** medidos sobre una copia, **empeoran** q01 (32 → 39-41 s) y q09 (13.4 → 16.6-17.8 s). No se aplicaron y la base no se tocó.
- **Revertir:** restaurar `st.tabs` desde git (commit `3223ace`).

## D-19 (C) Limpieza: `legacy/gimnasio/` con la misma estructura; documentos históricos intactos
- **Decisión:** los 10 archivos del gimnasio se movieron con `git mv` a `legacy/gimnasio/{db,seeder,eval,docs}`, con sus importaciones actualizadas; siguen funcionando (seed y ground truth verificados contra una base temporal). `DIAGNOSTICO.md` y los `FASE_XX.md` anteriores no se editaron, porque describen el estado en su momento.
- **Revertir:** `git mv` inverso (los renombres están en el commit de J).

---
# Etapa 2

## D-20 (C) Necesidad 4 con su criterio completo (restaurado)
- **Decisión:** n04 vuelve al criterio del dashboard en **una sola consulta** (CTE + `CUME_DIST()`): entre vendedores con ≥ 30 pedidos válidos, los que están en el 25 % con más ingresos (`CUME_DIST() OVER (ORDER BY ingresos DESC) <= 0.25`) y tienen calificación promedio por pedido < 3.5 **o** > 15 % de sus pedidos entregados con retraso. Resultado: **13** (la simplificación D-11 daba 24). Las diferencias con el dashboard original: solo pedidos válidos (D-01) y el percentil definido como `CUME_DIST`.
- **Revertir:** restaurar el SQL de D-11 en `eval/construir_oraculo_v3.py` (`N04_COMPLETA`).

## D-21 (C) Split DESARROLLO/PRUEBA por sorteo con semilla fija
- **Decisión:** las 10 necesidades van a DESARROLLO (instrucción del usuario); las 20 nuevas se reparten 10/10 con `random.Random(20261011).sample` (`eval/construir_oraculo_v3.py`), sin elegir a mano. Resultado registrado en `eval/split_oraculo.json`.
- **Consecuencia aceptada:** el sorteo dejó PRUEBA con más conteos y porcentajes (conteo 2, porcentaje 3, joins 3, promedio 1, ranking 1) y DESARROLLO con más rankings (ranking 5, porcentaje 2, joins 2, promedio 1, además de las 10 necesidades). No se repitió el sorteo para "equilibrar", porque eso reintroduciría la elección humana.
- **Revertir:** cambiar `SEMILLA_SPLIT` y reconstruir (invalida toda medición previa sobre PRUEBA; hasta el Paso 5 no hay ninguna).

## D-22 (C) Blindaje del conjunto de PRUEBA
- **Decisión:** `tests/test_heldout.py` (8 pruebas) impide que el texto, el SQL o los resultados de PRUEBA aparezcan en few-shot, clasificador, prompt completo o bitácora. Además: `run_eval.py` evalúa **solo DESARROLLO por defecto** (`--conjunto prueba` hay que pedirlo explícitamente), la evaluación no usa bitácora y la app de chat solo ofrece como ejemplos las 10 necesidades (antes ofrecía todo el oráculo, así que una pregunta de prueba podía terminar en la bitácora).
- **Cambios provocados por la prueba:** 2 few-shot reemplazados (uno rozaba x16 con Jaccard 0.250; otro compartía con x08 el fragmento "en promedio desde la compra hasta"). Un ajuste de la propia prueba: para valores no enteros, el redondeo a entero (15.31 → "15") no cuenta como fuga, porque chocaba con el rango "15+" de una vista, que es anterior y ajeno a x08.

## D-23 (C) Regla para conservar una mejora en el A/B
- **Decisión:** una mejora se conserva solo si, con 3 repeticiones en DESARROLLO, **la media sube al menos 1 acierto y el mínimo de la nueva configuración es ≥ la media de la anterior**. Con 20 preguntas, los intervalos de Wilson de dos configuraciones casi siempre se solapan, así que no se exige significancia (sería inalcanzable). Esta regla evita conservar cambios que solo ganan en una repetición afortunada. Las mejoras se prueban **acumulativamente**: cada una sobre la última configuración conservada, en el orden a → b → c → d1 → d2 → d3.
- **Revertir:** cada mejora está tras un interruptor de entorno apagado por defecto (`llm/schema_context.py`, `llm/text_to_sql.py`); basta con no encenderlo.

## D-24 (C) Vista `vw_pedidos_validos` (mejora b) y retoques de las mejoras d2 y c
- **Vista:** se añadió a `db/olist_views.sql` y se creó con `create_views()`. Solo recrea vistas: tablas sin cambios (conteos antes/después en `eval/baselines/etapa2/p3_conteos_bd_*.txt`). Tiene 98,207 filas = 99,441 − 625 canceled − 609 unavailable. La vista existe siempre en la base y el validador la conoce, pero solo aparece en el prompt si `TEXT2SQL_VISTA_VALIDOS=1`. Se reconstruye con el loader (`db/olist_init_db.py`).
- **d2 (vistas ocultas):** de cada nota se quitan solo las frases que nombran una vista oculta; si la nombra la primera frase, se quita la nota entera. Así no se pierde la regla general de "Ingresos = SUM(price) sin canceled/unavailable", y el A/B de d2 mide solo el efecto de ocultar las vistas.
- **c (denominadores):** los 2 primeros ejemplos genéricos fallaron la prueba de disyunción (SQL 0.529 frente a x04/x16, texto 0.286 frente a x16, este último de PRUEBA). Se reemplazaron por ejemplos sobre `geolocation` y `order_payments` (SQL ≤ 0.438, texto ≤ 0.056).

## D-25 (C) Configuración final del Paso 3 y modelo por defecto
- **Decisión:** quedan por defecto **(a) sin clasificador** y **(b) `vw_pedidos_validos` en el prompt**. Son las dos únicas mejoras que cumplieron D-23 (3/3/3 → 5/5/5 → 8/9/8 en DESARROLLO). c, d1, d2 y d3 empeoraron sobre b (medias 5, 5, 7 y 4.67) y siguen apagadas.
- **Modelo:** sigue **llama3.1 8B**. qwen2.5-coder 7B empató exactamente (8/8/9, media 8.33) y es más lento (18.74 s frente a 15.38 s); llama3.2 3B dio 3/2/3. La regla exige ser mejor en DESARROLLO, y un empate no lo es, así que tampoco se evalúa qwen en PRUEBA.
- **Contrapartida:** sin clasificador, el chat ya no parte en sub-consultas las preguntas compuestas de verdad ("X y además Y"); se responden con una sola consulta.
- **Revertir:** `TEXT2SQL_CLASIFICADOR=1` y/o `TEXT2SQL_VISTA_VALIDOS=0`, o los valores por defecto anteriores desde git (commit `57b5902`).

## D-26 (C) Paso 4: alcance de los cambios
- **q01:** se calcula en 2 consultas + pandas en lugar de 4 consultas que repetían CTEs; el empate en la tasa de recompra se desempata por nombre de categoría. No se usaron tablas temporales: la conexión es de solo lectura y no hacía falta.
- **Negativa del modelo:** solo cambia el texto y el `tipo_error`; se mantiene el corte sin reintento, para no alterar lo que midió el Paso 3. Reintentar tras una negativa queda como posible mejora, sin medir.
- **Fecha:** se muestran los años en la métrica y las fechas exactas debajo, en vez de reducir el tamaño de letra de todas las métricas.
- **Bitácora:** el diagnóstico nuevo solo cambia lo que se registra y se inyecta en preguntas futuras; la pista del reintento dentro de la misma pregunta no cambió.
- **Revertir:** cada punto está en el commit del Paso 4 y se puede deshacer por separado con `git revert`/`git checkout` de su archivo.

---
# Etapa 3

## D-27 (C) Dos notas del contexto calcaban preguntas del oráculo: reescritas antes de la nueva base
- **Hallazgo (Paso 1):** la nota "Para 'peso del flete sobre el precio' usa SUM(freight_value)/SUM(price)" repetía la redacción de n05 ("pesa más el flete sobre el precio"), y la nota "Preguntas sobre desde qué punto/umbral de retraso empieza a bajar la calificación…" respondía a q5 del oráculo v1. Las dos venían de la etapa 1.
- **Decisión:** se mantiene la definición de negocio, pero no la redacción. La regla `SUM(freight_value)/SUM(price)` queda en la nota general de "flete como proporción de las ventas"; `vw_retraso_por_rango` se describe como vista (qué trae y cómo ordenarla). El cambio entra **antes** de medir la nueva base, así que la base ya lo incluye.
- **Prueba nueva:** `tests/test_heldout.py::TestContextoNoDerivaDelOraculo` exige que ningún fragmento de 4 palabras de las 50 preguntas aparezca en el prompt. Con 5 o 6 palabras, la nota de n05 no se detectaba.
- **Revertir:** `git show 762cadd:llm/schema_context.py`.

## D-28 (C) PRUEBA_2, oráculo v4 y temperatura de evaluación
- **Oráculo v4** (`eval/construir_oraculo_v4.py`, idempotente): las 10 de PRUEBA v3 pasan a DESARROLLO (campo `conjunto_v3` para la historia). DESARROLLO queda en 30 preguntas y PRUEBA_2 en 20 nuevas: simple 4, porcentaje 5, pedido_valido 4, ranking 3, varios_pasos 4.
- **Verificación:** cada referencia se ejecutó en SQL y se recalculó con pandas desde los CSV, de forma independiente (`dashboard/verify_pandas.py`): 50/50 OK. `verificar_oraculo` ahora también falla si una pregunta no tiene recálculo.
- **Disyunción:** una pregunta inicial de PRUEBA_2 (cuotas máximas con tarjeta) chocaba con un few-shot del contexto (texto 0.364, SQL 0.500) y se reemplazó antes de congelar. Frente a DESARROLLO hay preguntas "hermanas" (misma estructura, otra condición; p. ej. p2_05 frente a x02, SQL 0.833). Es esperable en un held-out del mismo dominio y no es una fuga, porque DESARROLLO no entra al contexto; queda anotado como limitación.
- **Limitación honesta:** escribí PRUEBA_2 y voy a diseñar las mejoras del contexto. Las mitigaciones son tres: PRUEBA_2 se escribió y congeló **antes** de diseñar E1-E7, las pruebas de disyunción cubren las 50 preguntas, y PRUEBA_2 no se vuelve a ejecutar hasta el final.
- **Temperatura:** la evaluación usa **0.3** por defecto (`eval/run_eval.py`, `TEMPERATURA_EVAL`; queda en la configuración de cada corrida). El chat conserva 0.1 (`llm/ollama_client.py`), así que las cifras de evaluación describen el sistema a 0.3, no exactamente el chat. Revertir: `--temperature 0.1`.
- **Medición del tamaño del prompt:** `run_eval` envuelve al cliente (`MedidorPrompt`, no cambia nada del pipeline) y guarda `prompt_sql_caracteres` por pregunta. `eval.ab` reporta el tamaño medio y un intervalo de Wilson **por pregunta** (acierta en la mayoría de las repeticiones).
- **Medido después (Paso 2):** a T=0.3 la base da 13/14/13 y a T=0.1, con el mismo commit, 16/16/17. La 0.3 cambia el SQL en 24 de 30 preguntas, pero el acierto es mixto solo en 2 de 30. **Se mantiene 0.3 como se pidió** (los A/B comparan a igual temperatura), pero las cifras absolutas subestiman el chat, que usa 0.1. **Para revisión del usuario.**

## D-29 (C) Diseño de los experimentos de contexto E1-E7
- **Interruptores apagados por defecto** (`llm/contexto_e3.py`, `llm/schema_context.py`). Con todos apagados, el system prompt es idéntico byte a byte al del Paso 2 (verificado).
- **Lo dinámico va en el prompt de usuario** (E1 glosario, E5 ejemplos), para que el system siga siendo cacheable. E2 (esquema por pregunta) cambia el system por pregunta, y eso tiene un costo de caché que se mide en la latencia.
- **E1 glosario** (`llm/glosario_negocio.json`, 14 términos): definiciones de negocio estándar y fragmentos SQL genéricos (`<condición>`, `<universo>`). Se inyectan solo las entradas cuyo disparador aparece en la pregunta. "Tasa" se fusionó con "porcentaje". Quité un disparador ("más de un pedido") y una referencia al día de la semana porque coincidían con redacciones del oráculo o venían de conocer PRUEBA_2.
- **E2:** palabras clave por tabla escritas desde el significado de cada tabla; añade las tablas puente (`orders`; `order_items` para productos y vendedores; `products` para la traducción). `vw_pedidos_validos` siempre visible.
- **E3:** 21 columnas descritas desde la documentación pública del dataset de Olist.
- **E4:** 3 vistas de negocio (`vw_pedidos_entregados`, `vw_totales_pedido`, `vw_articulos_vendidos`), todas sobre `vw_pedidos_validos`. Se crearon con `create_views()` y las tablas no cambiaron (`eval/baselines/etapa3/e4_conteos_bd_*.txt`). Cada vista se verificó contra su definición (filas e ingresos al centavo). **Descarté** una columna "número de métodos de pago" en `vw_totales_pedido` porque se me ocurrió al conocer una pregunta de PRUEBA_2.
- **E5:** banco de 32 ejemplos genéricos (`llm/fewshot_banco.json`). Los 13 primeros intentos que chocaban con el oráculo se reformularon antes de usarlos; los porcentajes usan la forma `AVG(CASE … THEN 100.0 ELSE 0 END)`. Selección por TF-IDF propio (sin dependencias nuevas): 3 ejemplos en lugar de los 10 fijos.
- **E6:** reemplaza la regla "solo el SQL" por "plan de 2 a 4 líneas y luego el SQL"; `num_predict` 350 → 700.
- **E7:** solo en el primer intento. Genera k SQL, ejecuta los que pasan las validaciones y elige el resultado más frecuente (empate: el primero). No usa la referencia. Si ninguno corre con filas, sigue el flujo normal con el primero.
- **Causa objetivo por experimento:** heurística escrita en `eval/ab_acumulativo_e3.py` (`DETALLE`). Es aproximada, igual que `eval/causas.py`.

## D-30 (C) Configuración congelada para PRUEBA_2 y evaluación de los dos modelos
- **Congelada:** el código del commit que añade esta decisión, más `TEXT2SQL_AUTOCONSISTENCIA=5`, T = 0.3 (la de evaluación), N=2 y sin plantillas. El resto de los interruptores de la etapa 3 quedan apagados (E1-E6 revertidos).
- **Modelos:** qwen2.5-coder superó a llama3.1 en DESARROLLO según D-23 (18.33 frente a 15.33). La regla establecida (etapa 2) exige además que no sea peor en PRUEBA. Por eso **PRUEBA_2 se evalúa una sola vez con ambos modelos** (3 repeticiones cada uno) y después no se ajusta nada.
- **"No peor en PRUEBA_2"** (fijado antes de verla): media de qwen ≥ media de llama3.1 − 1 acierto (de 20).
- **Valores por defecto del código:** no se cambian para el chat hasta tener el resultado. La autoconsistencia multiplica la latencia del chat (~3x) y necesita temperatura > 0.1 para tener efecto; activarla en el chat es decisión del usuario.

## D-31 (C) Modelo por defecto: qwen2.5-coder (por la regla establecida)
- **Datos:** DESARROLLO (E7 k=5): qwen 20/16/19 (18.33) frente a llama3.1 17/15/14 (15.33), D-23 cumplida. PRUEBA_2 (una sola vez): qwen 11/14/13 (12.67) frente a llama3.1 14/13/12 (13.00). Umbral "no peor" fijado antes (D-30): 12.67 ≥ 13.00 − 1.
- **Decisión:** `llm/ollama_client.py` → `DEFAULT_MODEL = qwen2.5-coder:7b-instruct-q4_K_M`. README actualizado (modelo, ID y `ollama pull`).
- **Reservas (para revisión del usuario):** la ventaja de DESARROLLO no se replicó en PRUEBA_2. qwen es más lento (+33 % en DESARROLLO y +16 % en PRUEBA_2). El chat no usa la autoconsistencia, y sin ella los dos modelos empataban en la etapa 2.
- **Revertir:** `OLLAMA_MODEL=llama3.1:8b-instruct-q4_K_M`, o `git show 740066a:llm/ollama_client.py`.

## D-32 (C) Casos del juez iterativo (Fase 1): diseño y verificación
- **Casos** (`eval/casos_juez.json`, generado por `python -m eval.construir_casos_juez`): control (total de pedidos, todos los estatus) + necesidades 2, 4, 5, 6 y 8. Cada necesidad toma **una** cifra de su qNN() que no repite la pregunta del oráculo v4 de esa pestaña. La excepción es la n04, que coincide en cifra con n04 del oráculo (13). Elegidas: n02 = rango de quiebre, n05 = top 3 de categorías por flete, n06 = categoría más pagada a plazos y n08 = conjunto de categorías con "problema de producto".
- **Referencias:** mismos CTE, filtros y redondeos que q02/q04/q05/q06/q08. Lo que qNN() resuelve en pandas (quiebre de q02, filtro de q04, clasificación de q08) se reescribió en SQL. Verificado: las 6 referencias corren contra olist.db y sus cifras son idénticas a la salida de las qNN() (0 fallos).
- **Definiciones fijadas en la pregunta** (para que haya una sola respuesta): n02 usa el criterio del dashboard ("cae notablemente" = primer rango cuyo % de calificación ≤ 2 es ≥ 2 veces el de a tiempo), con días con decimales y calificación del pedido = promedio de sus reseñas. n04 usa los parámetros por defecto de q04.
- **Robustez medida** (alternativas razonables que NO cambian la respuesta): en n04, CUME_DIST vs PERCENT_RANK, ≥ 30 pedidos válidos vs de cualquier estatus y sin redondeo dan 13 y R$ 574,541.26; en n08, el conjunto no cambia sin redondeo; en n02, el filtro de válidos no cambia nada. Trampas que **sí** la cambian (se registran en `dificultades` y en `patrones_error`): reseñas sin promediar por pedido (n02, n04), días enteros (n02), AVG de razones o sin umbral (n05), conteo por artículo o MIN de cuotas (n06).
- **Comparadores:** `criterio_aceptacion.comprobaciones` es una lista y deben cumplirse todas. Se reutilizan las tolerancias de `eval/comparador.py` (conteo exacto, dinero ±0.01 o 0.1 %, porcentaje ±0.006). La etiqueta de rango de n02 no se compara.
- **Patrones de error:** ninguno se activa sobre su propia referencia (verificado en el generador). Son heurísticos: un patrón activado es un indicio para el diagnóstico, no un veredicto.

## D-33 (C) Esquema `completo` y guarda contra truncamiento (Fase 2)
- **Variante seleccionable:** `get_schema_context("completo")` o `TEXT2SQL_ESQUEMA=completo`. Por defecto sigue la compacta, así que el chat y la configuración congelada no cambian (system prompt compacto idéntico: 12,984 caracteres).
- **Contenido:** por tabla, para qué sirve; por columna, descripción, tipo, PK/FK/NULL, formato real leído de la base y la lista completa de valores si la columna tiene ≤ 12 valores distintos (order_status, payment_type, review_score). Luego vistas, columnas de unión, las notas de siempre, la nota nueva de división entera (`100.0 * a / b`) y los mismos 10 ejemplos.
- **Hallazgo:** las fechas reales son `'YYYY-MM-DD HH:MM:SS.ffffff'`, con microsegundos, no `'YYYY-MM-DD HH:MM:SS'` como decía la tarea. El esquema completo dice el formato real.
- **Tamaño medido** (`prompt_eval_count`, con un prefijo único para neutralizar la caché): system compacto 3,333 tokens (qwen) / 3,329 (llama3.1); completo 18,671 caracteres, 5,294 / 5,151 tokens.
- **Guarda:** `OllamaClient.generate_detallado` estima ANTES de llamar (tokens del system medidos + prompt de usuario a 2.5 caracteres/token, por exceso, + 64 de plantilla) y DESPUÉS usa el máximo de esa cifra y `prompt_eval_count`. Si prompt + num_predict deja menos del 10 % libre de num_ctx, lanza `ContextoInsuficienteError`. No se compara solo contra `prompt_eval_count` porque la caché de prefijos de Ollama lo reduce.
- **`generate()` no cambió:** lo nuevo (`format`, `seed`, `keep_alive`, conteo de tokens, `/api/ps`) son métodos aparte.

## D-34 (C) Juez iterativo (Fase 3)
- **Dónde:** `llm/juez.py` ya existía y lo usa el chat (opinar, diagnosticar, evaluar_sensatez). Se añadió una sección nueva con las funciones del juez iterativo; las clases existentes no se tocaron.
- **Veredicto:** 100 % determinista (`veredicto_caso`), con las tolerancias de `eval/comparador.py`. El LLM solo redacta pistas.
- **Diagnóstico sin valores:** la forma se describe de manera cualitativa ("la pregunta pide una sola fila", "más filas de las esperadas") y nunca se da el número de filas esperado, porque en n08 ese número es la respuesta (11).
- **Escalado de pistas:** intento 1 = tipo de error; 2 = concepto implicado (en la plantilla, los patrones activados); 3+ = la trampa concreta (en la plantilla, además, la lista de conceptos de revisión).
- **Filtro anti-fuga** (`detectar_fuga`), aplicado a TODA pista (LLM o plantilla) antes de que llegue al candidato:
  - Números del resultado esperado y de las cifras clave, también redondeados (19.1 por 19.08). Se permiten los que ya aparecen en la pregunta (umbrales) y los enteros < 10.
  - Valores de texto esperados (categorías), comparados por palabra completa: "art" no bloquea "artículos".
  - 6 o más tokens seguidos del SQL de referencia.
  - Si la pista LLM revela algo, se regenera una vez; si vuelve a revelar, se usa la plantilla. Si aun así algo se cuela, se reemplaza por un texto genérico.
- **Prompt del candidato:** solo la pregunta, su SQL anterior, el resumen de su propio resultado (≤ 5 filas) y las pistas acumuladas. El system prompt es el mismo esquema (se aprovecha la caché). Salida con `format` = JSON schema `{"sql": ...}`, `seed` fija y `keep_alive` de 30 min.
- **Prueba de no fuga:** `tests/test_juez_iterativo.py` corre el ciclo con un candidato falso y un juez que intenta filtrar la respuesta y el SQL de referencia. Comprueba que ningún prompt del candidato contiene el SQL de referencia, la respuesta de referencia ni cifras o valores esperados. Excepción documentada: el SQL anterior del propio candidato puede compartir n-gramas genéricos con la referencia (p. ej. `SELECT COUNT(*) AS`), así que el chequeo de n-gramas excluye ese bloque.

## D-35 (C) Experimentos del juez (Fase 4): modelo juez y num_ctx
- **Juez = mismo modelo que el candidato.** Cargar un modelo cuesta unos 20-23 s (`load_duration` medido: qwen 21-23 s, llama3.1 20-21 s). qwen (5.15 GB) y llama3.1 (5.82 GB) no caben juntos en los 8 GB de la RX 6600, así que alternar candidato y juez recargaría un modelo en cada pista.
- **VRAM por num_ctx** (`/api/ps`): qwen 8192 = 5.15 GB, 12288 = 5.23 GB, 16384 = 5.47 GB, todo en VRAM. llama3.1 8192 = 5.82 GB, 12288 = 6.36 GB, todo en VRAM; 16384 = 7.26 GB con solo 6.50 GB en VRAM (**descarga a CPU**). 16384 queda descartado para llama3.1.
- **num_ctx del barrido (solo intento 1): 8192.** Es el menor que cabe con margen en ambos esquemas: completo 5,294 + ~300 de pregunta + 600 de num_predict ≈ 6,200 < 7,373 (90 %).

## D-36 (C) Configuración del ciclo con juez y manejo de la interrupción
- **Configuración del ciclo:** compacto, T = 0, num_ctx 8192. Se eligió con la regla fijada tras el barrido y antes de correr el ciclo: mayor % de acierto@1 (2/6); si empatan, esquema más corto y T más baja. Toda la diferencia viene de un caso (n05): es ruido.
- **Guarda en el ciclo:** si `ContextoInsuficienteError` salta a mitad de un caso, el caso se cierra como fallo y queda registrado (no se continúa con un prompt recortado). No saltó en ninguna corrida (máximo 4,822 tokens).
- **Interrupción:** Windows Update reinició el equipo (05:07 y 05:09, KB5127648) durante qwen-llm. n08 se repitió en `ciclo_qwen2_5-coder_llm_n08/` con el mismo código de `llm/juez.py` (commit d2c7ecf) y la misma semilla; `eval/tabla_juez.py` recalcula las métricas uniendo los JSON por caso.
- **No se cambió nada entre corridas** (p. ej. el patrón "no filtra pedidos válidos", demasiado amplio): queda como lección en `docs/INFORME_JUEZ.md` para no mezclar condiciones.
