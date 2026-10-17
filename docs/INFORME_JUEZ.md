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
