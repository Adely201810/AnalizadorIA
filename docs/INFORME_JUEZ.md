# Informe — Juez con retroalimentación iterativa

Fecha: 2026-10-17 · Rama `feat/juez-iterativo` · Ollama 0.40.5 · RX 6600 (Vulkan) · Decisiones D-32 a D-36 en [DECISIONES.md](DECISIONES.md).
Este informe sirve también como documento de fase (Fases 1-5 de la tarea). La Fase 6 (toggle en `app.py`) **no se hizo** por falta de tiempo.

> **acierto@N con juez NO es comparable con PRUEBA_2 ni con DESARROLLO.** El juez conoce la respuesta correcta y solo existe para las preguntas del catálogo (`eval/casos_juez.json`). Mide cuánto ayuda la retroalimentación, no la precisión del chat.

## 1. Resultado en una frase
**El juez no rescató ningún caso.** En las 4 configuraciones del ciclo, acierto@N = acierto@1: 72 reintentos y 0 correcciones. El esquema completo tampoco ayudó (9/42 aciertos en el intento 1, igual que el compacto) y cuesta un 59 % más de tokens. La retroalimentación del LLM empató con la de plantilla y añade unos 9 s por intento.

## 2. Qué se construyó
| Fase | Entregable |
|---|---|
| 1 | `eval/casos_juez.json` (generado y verificado por `eval/construir_casos_juez.py`): control + necesidades 2, 4, 5, 6 y 8. Las referencias salen de las qNN() del dashboard y dan cifras idénticas (0 fallos). |
| 2 | `get_schema_context("completo")` / `TEXT2SQL_ESQUEMA=completo`, y guarda de truncamiento (`ContextoInsuficienteError` si prompt + num_predict deja < 10 % libre de num_ctx). |
| 3 | En `llm/juez.py`: veredicto determinista, diagnóstico sin valores, pistas por niveles (plantilla o LLM a T=0), filtro anti-fuga obligatorio, ciclo `resolver_con_juez` y chequeo de la síntesis. Salida JSON (`format`), `seed` y `keep_alive`. |
| 4 | `eval/run_juez.py` (JSONL por intento, 1 JSON por caso, resumen) y `eval/tabla_juez.py`. Resultados en `eval/baselines/juez/`. |
| Pruebas | `tests/test_juez_iterativo.py` (16 pruebas): comparadores, filtro anti-fuga, guarda de contexto y la garantía de que **ningún prompt del candidato contiene el SQL de referencia, la respuesta de referencia ni cifras o valores esperados**. |

## 3. Tamaño del contexto y VRAM (medido)
| | qwen2.5-coder 7B | llama3.1 8B |
|---|---|---|
| System prompt compacto (12,984 car.) | 3,333 tokens | 3,329 tokens |
| System prompt completo (18,671 car.) | 5,294 tokens (+59 %) | 5,151 tokens (+55 %) |
| num_ctx 8192 | 5.15 GB, todo en VRAM | 5.82 GB, todo en VRAM |
| num_ctx 12288 | 5.23 GB, todo en VRAM | 6.36 GB, todo en VRAM |
| num_ctx 16384 | 5.47 GB, todo en VRAM | **7.26 GB, solo 6.50 GB en VRAM (descarga a CPU)** |
| Carga del modelo (`load_duration`) | 21-23 s | 20-21 s |

Los dos modelos juntos (≈11 GB) no caben en 8 GB, así que alternar candidato y juez costaría unos 20 s por pista. Por eso **el juez es el mismo modelo que el candidato** (D-35). Con esa elección, la carga acumulada en todo el ciclo fue ≤ 0.3 s.

## 4. Barrido rápido (qwen2.5-coder, solo intento 1, sin juez, num_ctx 8192)
84 corridas en 1,476 s (24.6 min, dentro del límite de 30; no se recortó nada).

| esquema | T | semillas | acierto@1 | latencia/intento (s) | prompt_eval máx | por caso |
|---|---|---|---|---|---|---|
| compacto | 0 | 1 | **2/6** | 18.25 | 3,603 | c01 1/1 · n05 1/1 · resto 0 |
| compacto | 0.3 | 3 | 4/18 | 15.44 | 3,603 | c01 3/3 · n05 1/3 · resto 0 |
| compacto | 0.7 | 3 | 3/18 | 13.64 | 3,603 | c01 3/3 · resto 0 |
| completo | 0 | 1 | 1/6 | 21.00 | 5,564 | c01 1/1 · resto 0 |
| completo | 0.3 | 3 | 4/18 | 17.75 | 5,564 | c01 3/3 · n05 1/3 · resto 0 |
| completo | 0.7 | 3 | 4/18 | 14.90 | 5,564 | c01 3/3 · n05 2/3 · resto 0 |

Tipo de resultado por intento:
- **Compacto:** 9 correctos, 16 de validación (columna inexistente), 14 de ejecución y 3 incorrectos.
- **Completo:** 9 correctos, 14 de validación, 13 de ejecución y 6 incorrectos.

**¿Ayudó el esquema completo? No.** Con todas las temperaturas juntas, los dos esquemas tienen 9/42 aciertos. Las necesidades 2, 4, 6 y 8 fallan siempre con ambos. El completo bajó algo los errores de columnas o ejecución (27 frente a 30), pero esos intentos pasaron a dar resultados incorrectos (6 frente a 3). Cuesta +1,961 tokens y entre 1.3 y 2.8 s más por intento.

**Mejor configuración** (regla fijada antes de mirar el ciclo: mayor % de acierto@1; si empatan, el esquema más corto y la T más baja): **compacto, T=0**. **Ojo:** toda la diferencia entre configuraciones viene de un solo caso (n05) y está dentro del ruido.

## 5. Ciclo con juez (compacto, T=0, num_ctx 8192, max-iter 5, juez = mismo modelo)
| modelo | retroalimentación | acierto@1 | acierto@N | intentos hasta acertar | latencia/intento (s) | s por pista LLM | reintentos | con SQL idéntico al anterior | fugas bloqueadas |
|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-coder | plantilla | 2/6 | **2/6** | 1 | 18.78 | — | 16 | 9 | 0 |
| qwen2.5-coder | llm | 2/6 | **2/6** | 1 | 27.75 | 11.7 | 16 | 10 | 0 |
| llama3.1 | plantilla | 1/6 | **1/6** | 1 | 17.82 | — | 20 | 6 | 0 |
| llama3.1 | llm | 1/6 | **1/6** | 1 | 25.05 | 10.5 | 20 | 7 | 0 |

- **El máximo de `prompt_eval_count` fue 4,822**, lejos del límite de 7,373 (90 % de 8192). La guarda de truncamiento nunca saltó.
- **Fugas:** en las corridas reales ninguna pista reveló nada, así que el filtro no tuvo que actuar (0 bloqueos). Que el filtro bloquea fugas está probado en las pruebas unitarias, con un juez falso que intenta filtrar la respuesta y el SQL de referencia.
- **Síntesis final:** solo se ejecutó cuando hubo filas. En c01 y n05 las cifras clave están en el texto (1/1 y 3/3). Pero el texto de n05 salió como "no confiable", porque el chequeo existente no acepta el umbral de la pregunta (R$ 5,000), que no está en las filas.
- **Interrupción:** Windows Update reinició el equipo a las 05:07 y a las 05:09 (KB5127648) durante el ciclo qwen-llm. Ollama devolvió un HTTP 500 a las 05:05:28 y el proceso murió. n08 se repitió aparte (`ciclo_qwen2_5-coder_llm_n08/`), con el mismo código y la misma semilla; `tabla_juez` une las dos carpetas.

**¿La retroalimentación del LLM le ganó a la de plantilla? No.** Empate exacto en ambos modelos (2/6 y 1/6), y el LLM cuesta unos 9 s más por intento. Además, sus pistas fueron a veces **erróneas**:
- Clasificó como "error de agregación" una columna inexistente.
- En n06 dijo que la consulta "cuenta pedidos en lugar de categorías", que es justo lo que pide la pregunta.

La plantilla, en cambio, reproduce el mensaje real del validador.

## 6. Por qué no funcionó el ciclo
1. **A T=0 el candidato se atasca.** Entre el 30 % y el 63 % de los reintentos repiten exactamente el SQL anterior (qwen-plantilla 9/16, qwen-llm 10/16, llama 6/20 y 7/20). La pista no basta para sacarlo de su respuesta más probable.
2. **Los fallos son de estructura, no de lógica fina.** La mayoría son columnas que no existen en la vista que el modelo eligió. El modelo insiste en la misma vista en lugar de cambiar de ruta.

## 7. Recomendaciones (num_ctx y temperatura)
- **num_ctx = 8192.** Es el menor que cabe con margen: prompt máximo de 5,564 tokens en el barrido y de 4,822 en el ciclo. Mantiene los dos modelos enteros en VRAM. Subir a 12288 cuesta +85 MB (qwen) o +541 MB (llama) sin ningún beneficio medido. Con 16384, llama3.1 descarga parte a CPU.
- **Temperatura del intento 1: 0.** Fue la mejor del barrido (2/6), aunque la diferencia con 0.3 (4/18) es ruido y T=0 es reproducible.
- **Para los reintentos, T=0 es mala idea:** la mayoría repite el SQL. Propuesta **no medida**: reintentos a T ≈ 0.3-0.7 o cambio de semilla. Haría falta una corrida para confirmarlo.

## 8. Lecciones generalizables (propuestas; NO aplicadas al chat)
Errores que se repitieron en el barrido y el ciclo:
1. **Columnas que el modelo supone en las vistas:** `vw_entregas_retrasos.seller_id`, `vw_ingresos_por_vendedor.order_id`, `review_score` en `vw_retraso_por_rango` y `product_category_name_english` en `vw_ventas_pedido` (la vista tiene `categoria_ingles`).
   - Auto-chequeo propuesto: cuando el validador rechaza una columna de una vista, el reintento debería incluir la **lista real de columnas de esa vista** y la ruta por tablas base.
   - Antecedente: documentar las columnas de las vistas en el prompt fijo (d1, etapa 2) empeoró el resultado; aquí se daría solo cuando falla.
2. **Detectar SQL repetido en producción:** si el reintento devuelve el mismo SQL, volver a muestrear con T > 0 o con otra semilla. Es barato y el ciclo mostró que pasa en la mayoría de los reintentos.
3. **Ruta producto → pago o reseña:** el modelo une `products` con `order_payments` por `order_id`, que `products` no tiene. Nota de esquema candidata: "de products a pagos/reseñas se pasa por order_items (product_id → order_id)".
4. **Reseñas sin agregar por pedido:** el patrón se activó en 7 de 7 intentos fallidos de n02 y n04. La nota ya existe en el esquema; no basta con decirlo una vez.
5. **El chequeo de "texto confiable" debe aceptar los números de la pregunta** (umbrales como R$ 5,000). Hoy marca como no confiable una síntesis correcta. Además, la síntesis embelleció nombres de categoría ("Christmas Supplies", "Food & Drink") pese a la regla de usar el texto exacto.
6. **Pistas LLM:** si se usan, conviene anteponer siempre el diagnóstico determinista (mensaje real del validador) y quitar el nivel 1, que fue demasiado vago y a veces equivocado.
7. **Patrón "no filtra pedidos válidos" demasiado amplio:** se activa también con vistas que ya excluyen cancelados (`vw_ingresos_por_*`). Hay que afinarlo antes de reutilizarlo.

## 9. Limitaciones
- 6 casos, T=0 y una sola semilla en el ciclo. Una diferencia de 1 caso no es señal.
- `patrones_error` y los chequeos de sensatez son heurísticos; un patrón activado es un indicio, no un veredicto.
- PRUEBA_2 no se tocó. Los casos del juez reutilizan necesidades del dashboard, que ya estaban en DESARROLLO.

---

# Ronda 2 — romper el atasco y reparar con el esquema real

Fecha: 2026-10-17 · Decisiones D-37 (cambios y corrida) y D-38 (modo evaluación en la app) en [DECISIONES.md](DECISIONES.md).

## R2.1 Qué se cambió (todo con flags, apagado por defecto)
| Cambio | Flag (`eval/run_juez.py` / `resolver_con_juez`) | Qué hace |
|---|---|---|
| 1. Anti-repetición | `--reintento-temp` (sin valor: 0.5) | Los reintentos usan T=0.5 y la semilla `seed + intento − 1`. El SQL se normaliza (minúsculas, espacios, `;` final, alias de tabla → nombre de tabla, alias de columna anonimizados). Si coincide con uno ya probado en el caso, se vuelve a muestrear hasta 3 veces sin gastar intento. |
| 2. Reparación con esquema real | `--reparar-esquema` | Si el validador o SQLite rechazan una columna o tabla, la pista añade: el mensaje real, las columnas REALES del objeto implicado (PRAGMA de la base, vía `get_esquema_real`) y la ruta más corta por tablas base hasta una tabla que tenga la columna (BFS por las columnas de unión). No usa el oráculo y pasa por el filtro anti-fuga. |
| 3. Modo edición | `--modo-edicion` | El reintento pide "corrígelo cambiando SOLO lo necesario", con el SQL anterior y su error. **Implementado y con pruebas, pero no medido** (ver R2.2). |
| 4. Pistas v2 | `--pistas-v2` | Se empieza en el nivel de concepto (sin el nivel 1 vago). Con pistas LLM, el diagnóstico determinista va primero. |
| 5a. Texto confiable | `numeros_extra` en `_respuesta_respaldada_por_datos` (el chat no lo pasa) | El juez registra además `texto_confiable_con_umbrales`, que acepta los números que ya vienen en la pregunta. |
| 5b. Patrón "no filtra pedidos válidos" | `eval/casos_juez.json` regenerado | Ya no se activa con las 8 vistas que excluyen cancelados (`vw_ingresos_por_*`, `vw_totales_pedido`, …). Referencias re-verificadas contra qNN(): 0 fallos. |

## R2.2 Corrida (qwen2.5-coder, compacto, intento 1 a T=0, num_ctx 8192, plantilla, max-iter 5, los mismos 6 casos)
- **A** = anti-repetición. **B** = A + reparación + pistas v2. Las pistas v2 van junto con la reparación porque las dos cambian el texto de la pista (D-37), así que **el efecto de B no se puede atribuir solo a la reparación**.
- **C (modo edición) se cortó por tiempo.** A tardó 778 s y B 845 s (27 min); C, con un costo parecido, habría pasado el límite de ~40 min.

| configuración | acierto@1 | acierto@N | reintentos | con SQL repetido | remuestreos | tipo de resultado por intento | latencia/intento (s) | fugas bloqueadas |
|---|---|---|---|---|---|---|---|---|
| Ronda 1 (plantilla) | 2/6 | 2/6 | 16 | 9 | 0 | correcto 2, ejecución 10, validación 10 | 18.78 | 0 |
| **A** anti-repetición | 2/6 | **2/6** | 16 | **3** | 15 | correcto 2, ejecución 11, resultado incorrecto 2, validación 7 | 31.45 | 0 |
| **B** A + reparación + pistas v2 | 2/6 | **2/6** | 16 | 4 | 17 | correcto 2, **ejecución 4**, **resultado incorrecto 7**, validación 9 | 35.54 | 0 |
| C | — | — | — | — | — | no corrida (tiempo); medida después, ver R2.6 | — | — |

"Con SQL repetido" usa la misma métrica normalizada en las tres filas (en la ronda 1 coincide con la comparación exacta: 9).

## R2.3 Qué pasó caso por caso
- **Ningún caso se rescató.** c01 y n05 aciertan en el intento 1, igual que en la ronda 1. **n02, n04, n06 y n08 siguen en 0** con todas las configuraciones probadas en las dos rondas (barrido, ciclo con plantilla y LLM, A, B). Es, con probabilidad, **un límite del modelo de 7B** con estas preguntas de varios pasos, no algo que se arregle con más pistas.
- **La anti-repetición funciona como mecanismo:** los reintentos con SQL repetido bajan de 9/16 a 3/16. Pero no cambia el acierto y casi duplica la latencia (18.8 → 31.5 s por intento). En n06 (B), 3 remuestreos a T=0.5 con semillas distintas devolvieron el mismo SQL normalizado: el modelo está muy seguro de una respuesta incorrecta.
- **La reparación cambia el tipo de fallo:** de "no corre" a "corre pero da otra cifra" (ejecución 11 → 4; resultado incorrecto 2 → 7).
  - **n06:** el intento 1 unía `products` con `order_payments` por un `order_id` que no existe. La reparación dio la ruta `products → order_items (por product_id) → order_payments (por order_id)` y el intento 2 la usó tal cual y ejecutó. Devolvió la categoría correcta con otro porcentaje (91.16 % frente al esperado). Cayó en el abanico artículos × pagos. La pista siguiente nombra la causa ("las cuotas del pedido son el máximo entre sus pagos; hay que agregar order_payments por pedido"), pero el modelo repitió el SQL.
  - **n02:** tras recibir las columnas reales de `vw_retraso_por_rango`, el intento 2 ejecutó, con una lógica de rangos equivocada.
  - **n04:** el modelo insistió 4 intentos seguidos en `vw_ingresos_por_vendedor.order_id`, aunque la pista listaba las columnas reales de la vista.
  - **n08:** pasó de `product_category_name_english` (sin tabla) a `t3.categoria_ingles` sobre `order_items`. Cambió de error, pero no lo resolvió.
- **Fugas:** 0 bloqueos. Las pruebas comprueban que la reparación no revela nada en ningún caso (`test_la_reparacion_nunca_revela_la_respuesta`).
- **Arreglo 5a medido:** la síntesis de n05 (correcta, 3/3 cifras clave) sale "no confiable" con el chequeo actual y "confiable" con umbrales, en A y en B. El chequeo solo mira que los números estén respaldados por las filas, no que la respuesta sea correcta: la síntesis de n06 (incorrecta) sale "confiable".

## R2.4 Recomendación para el chat (NO activado)
- **Activar primero el cambio 2 (reparación con esquema real).** No usa el oráculo, no hace llamadas extra al modelo (solo alarga la pista; el prompt máximo pasó de 4,550 a 5,470 tokens, lejos del límite de 7,373) y ataca el error más frecuente del chat: columnas que no existen en la vista. Encaja en el reintento que el chat ya tiene (N=2). Lo que se gana es que la consulta corra, no necesariamente que acierte. Medido primero junto con pistas v2; en R2.6 se midió sola y el efecto es el mismo, así que es de la reparación.
- **No activar todavía el cambio 1 (anti-repetición).** Reduce la repetición, pero no subió ningún acierto y suma 13-17 s por intento. Si se quiere algo barato: detectar el SQL repetido y remuestrear una sola vez, sin cambiar la temperatura del primer intento.
- **Arreglo 5a:** conviene pasarlo al chat. Hoy oculta síntesis correctas que citan el umbral de la pregunta. Es un cambio de una línea en el llamador; no se hizo, porque cambia el comportamiento por defecto.

## R2.5 Modo evaluación con juez en la app (Fase 6)
Interruptor "🧪 Modo evaluación con juez" en la barra lateral de `app.py`, apagado por defecto.
- **Al activarlo:** las preguntas de ejemplo se reemplazan por los 6 casos del catálogo. Se elige el número de intentos (1-5) y se activan o no la anti-repetición y la reparación.
- **Durante la corrida:** cada intento aparece en vivo en un bloque de estado, con el SQL, el error o hasta 5 filas, y la pista que recibió el modelo. Al terminar se muestra el veredicto, la síntesis si acertó y la respuesta de referencia del dashboard en un desplegable.
- **Verificado en el navegador:**
  - c01: "✅ Respuesta correcta en el intento 1 de 5" (99,441 pedidos).
  - n06 con 2 intentos: "❌ El modelo no acertó en 2 intento(s)", con el desplegable "Intento 1 — ❌ incorrecto" y su SQL.
  - Sin errores en la consola.

## R2.6 Mediciones pendientes: C (modo edición) y reparación sin pistas v2
Fecha: 2026-10-17 · Decisión D-39 en [DECISIONES.md](DECISIONES.md). Mismo modelo, casos, semilla (42) y código que A y B (commit e4b146a, árbol limpio).
- **C** = B + modo edición (`--reintento-temp --reparar-esquema --pistas-v2 --modo-edicion`, etiqueta `r2_C`): 747.9 s.
- **B sin pv2** = A + reparación, sin pistas v2 (`--reintento-temp --reparar-esquema`, etiqueta `r2_B_sin_pv2`): 757.2 s.

Salida exacta de `python -m eval.tabla_juez --ronda2 eval/baselines/juez/ciclo_qwen2_5-coder_plantilla eval/baselines/juez/r2_A eval/baselines/juez/r2_B eval/baselines/juez/r2_C eval/baselines/juez/r2_B_sin_pv2`:

| configuración | acierto@1 | acierto@N | reintentos | con SQL repetido | remuestreos | tipo de resultado por intento | latencia/intento (s) | fugas bloqueadas |
|---|---|---|---|---|---|---|---|---|
| plantilla | 2/6 | 2/6 | 16 | 9 | 0 | correcto 2, ejecucion 10, validacion 10 | 18.78 | 0 |
| plantilla-rt0.5 | 2/6 | 2/6 | 16 | 3 | 15 | correcto 2, ejecucion 11, resultado_incorrecto 2, validacion 7 | 31.45 | 0 |
| plantilla-rt0.5-rep-pv2 | 2/6 | 2/6 | 16 | 4 | 17 | correcto 2, ejecucion 4, resultado_incorrecto 7, validacion 9 | 35.54 | 0 |
| plantilla-rt0.5-rep-edi-pv2 | 2/6 | 2/6 | 16 | 6 | 18 | correcto 2, ejecucion 7, resultado_incorrecto 7, validacion 6 | 31.28 | 0 |
| plantilla-rt0.5-rep | 2/6 | 2/6 | 16 | 3 | 13 | correcto 2, ejecucion 5, resultado_incorrecto 8, validacion 7 | 31.26 | 0 |

(Filas: Ronda 1, A, B, C y B sin pv2, en ese orden.) Prompt máximo: C 5,134 tokens; B sin pv2 5,185.

**Ni C ni la reparación sola rescatan ningún caso.** acierto@N = acierto@1 = 2/6 en las cinco configuraciones: c01 y n05 aciertan en el intento 1, y n02, n04, n06 y n08 siguen en 0.

- **La reparación sola explica el cambio de tipo de fallo que se vio en B.** Sin pistas v2, los errores de ejecución bajan de 11 (A) a 5 y "resultado incorrecto" sube de 2 a 8, casi igual que B (4 y 7). Las pistas v2 no aportan nada medible encima de la reparación. El costo tampoco cambia: 31.26 s por intento, como A (31.45). Los 35.54 s de B parecen ruido de esa corrida, porque C, que hace lo mismo que B y además añade el modo edición, tarda 31.28 s.
- **El modo edición ancla el SQL anterior.** C tiene más reintentos con SQL repetido (6/16, frente a 4 en B y 3 en B sin pv2), aun con 18 remuestreos. En n02 y n06, C repite el SQL del intento 2 hasta el final. En n06 el resultado es el mismo `computers 91.16` de B. En n04, C pasa del error de columna de la vista a `ambiguous column name: seller_id` y se queda ahí 3 intentos. En n08 sigue pidiendo `t3.product_category_name_english` sobre `order_items` en los intentos 3 a 5.
- **Caso por caso, B sin pv2:**
  - **n06:** prueba tres variantes de SQL que ejecutan, con alias distintos, y las tres devuelven `computers 91.16`. Sigue cayendo en el abanico artículos × pagos.
  - **n02:** ejecuta con `pct_1_2_estrellas >= 2` en lugar de `<= 2`, con una lógica de rangos equivocada.
  - **n04:** pasa de la vista sin `order_id` a `ambiguous column name` y después a `t2.seller_id` sobre `vw_entregas_retrasos`.
  - **n08:** pasa de `product_category_name_english` a `product_category_name` sobre `order_items`.
  - En todos los casos cambia de error, pero no lo resuelve.
- **Fugas:** 0 bloqueos en C y en B sin pv2.

**Consecuencia para R2.4:** la recomendación de activar primero la reparación se mantiene. Ahora se puede activar sin pistas v2, porque el efecto (que la consulta corra, no que acierte) ya no depende de ellas. El modo edición no se recomienda: no rescata nada y aumenta la repetición. Nada de esto se activó en el chat.
