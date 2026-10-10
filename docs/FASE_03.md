# Fase 3 (endurecer) — Árbitro determinista contra el resultado de la referencia

Fecha: 2026-10-10 · Estado: **COMPLETA** · Pruebas: `tests.test_comparador` (19/19 OK), `tests.test_limite_ejecucion` (2/2 OK)

## Qué se implementó

| Pieza | Archivo | Qué hace |
|---|---|---|
| Árbitro | `eval/comparador.py` | Compara las **filas** del modelo contra las del SQL de referencia ejecutado: mismo nº de filas, cada columna requerida debe coincidir con alguna columna del modelo (cualquier posición, se permiten extras), en orden si `orden_importa`. |
| Tolerancias por tipo | `eval/comparador.py` | conteo exacto · dinero ≤ 0.01 o ≤ 0.1 % · porcentaje ≤ 0.05 puntos (acepta escala fracción) · decimal ≤ 0.01 · texto igual sin mayúsculas. Ya no hay tolerancias por pregunta. |
| Metadatos del oráculo | `eval/ground_truth_olist.json` | `tipos_columnas` (tipo por columna de la referencia; `null` = no se compara) y `orden_importa`. |
| Evaluador | `eval/run_eval.py` (reescrito) | Ejecuta la referencia y compara con el árbitro; registra `origen`, `intentos`, `latencia_s`, `motivo`, filas del modelo y de la referencia, y `texto_respaldado` (métrica secundaria que ya no cuenta los mensajes fijos de error). Guarda el JSON tras cada pregunta y admite `--reanudar`. Al final registra `ollama ps` (VRAM). |
| Sin plantillas | `llm/text_to_sql.py` | `answer_question(..., usar_plantillas=False)` y `run_eval.py --sin-plantillas` desactivan las plantillas por reglas **y** el fallback sobre vistas. |
| P4 | `db/olist_database.py`, `eval/compute_ground_truth.py` | `verificar_bd_existe()` compartida; `compute_ground_truth.py` ya no crea una BD vacía. |
| Límite de ejecución | `llm/text_to_sql.py` | El SQL del modelo se corta a los 60 s (D-08). Se descubrió durante esta fase (ver abajo). |
| Recalificar | `eval/recalificar.py` | Reejecuta en solo lectura el SQL de una corrida guardada y la recalifica con el árbitro actual. |

## Pruebas

### Árbitro (`python -m unittest tests.test_comparador -v`)
```
test_q4_orden_importa ... ok
test_q5_columnas_iguales_en_ambas_es_falso ... ok
test_sin_filas_del_modelo ... ok
test_sin_orden_compara_como_conjunto ... ok
test_cada_referencia_se_acepta_a_si_misma ... ok
test_categoria_equivocada ... ok
test_columnas_en_otro_orden_y_extra ... ok
test_mas_filas_que_la_referencia ... ok
test_referencia_es_la_vigente ... ok
test_sin_redondear_se_acepta ... ok
test_valor_viejo_se_rechaza ... ok
test_valor_vigente_se_acepta ... ok
test_conteo_exacto ... ok
test_decimal ... ok
test_dinero ... ok
test_porcentaje ... ok
test_texto ... ok
test_q10_viejo ... ok
test_q6_viejo_y_baseline00 ... ok

----------------------------------------------------------------------
Ran 19 tests in 39.185s

OK
```
`test_valor_viejo_se_rechaza` demuestra que **el valor viejo de q2 (1,258,681.34) ahora se rechaza**; antes, la tolerancia del 2 % (±≈25,000 R$) lo aceptaba igual que al vigente (1,255,695.13). También se rechazan los valores viejos de q6 (163.94) y q10 (160.58), y el 162.70 de q6 que baseline_00 dio por bueno.

Un caso de prueba estaba mal planteado por mí: esperaba que 160.40 frente a 160.24 se rechazara, pero es un 0.0998 % y la regla del 0.1 % lo acepta, como corresponde. Se corrigió el caso (160.50 = 0.162 % se rechaza); la regla no se tocó.

### P4 (`compute_ground_truth.py` sin BD)
```
===== P4: compute_ground_truth con OLIST_DATABASE_URL=sqlite:///C:/Users/alexp/AppData/Local/Temp/no_existe_olist.db
FileNotFoundError: No existe la base de datos C:\Users\alexp\AppData\Local\Temp\no_existe_olist.db. Créala con: python seeder/load_olist_csv.py
[exit code: 1]
===== ¿Se creó el archivo?
ls: cannot access 'C:/Users/alexp/AppData/Local/Temp/no_existe_olist.db': No such file or directory
```

### Bandera sin plantillas (pregunta que activa la plantilla Pareto)
```
usar_plantillas=True: origen=plantilla:concentracion_pareto intentos=0 filas=[('vendedores', 80, 540, 3053, 17.69, 80.02)]
usar_plantillas=False: origen=llm intentos=1 filas=[(540,)]
```

## Problema real encontrado: SQL sin límite de tiempo
La primera corrida de baseline_01 se quedó colgada en q4. Diagnóstico (`logs/baseline_01_intento1_colgado.log`):
- Última llamada a Ollama: `[GIN] 2026/10/10 - 17:20:29 | 200 | 6.7350602s | POST "/api/generate"`.
- `ollama ps` sin ningún modelo cargado y el proceso de Python acumulando CPU (`CPU acumulada 179.0 s` → `179.5 s` en 3 s): SQLite estaba ejecutando una consulta generada por el modelo, sin límite.

Arreglo (D-08): límite de 60 s con `set_progress_handler`. Prueba:
```
test_consulta_normal_no_se_afecta ... ok
test_producto_cartesiano_se_corta ... ok
Ran 2 tests in 2.010s
OK
  cartesiano cortado en 2.00 s: la consulta superó el límite de 2 s de ejecución (revisa si hay un JOIN sin condición o un producto cartesiano)
```
En la corrida válida de baseline_01, q4 volvió a topar el límite y esta vez se cortó: `detalle_error = "Error de SQLite al ejecutar la consulta: la consulta superó el límite de 60 s de ejecución…"`, con 145.6 s en total para 2 intentos.

## Resultado: baseline_01 (`eval/baselines/baseline_01_endurecido.json`)

Configuración: `llama3.1:8b-instruct-q4_K_M`, `temperature=0.1`, `num_ctx=8192`, `max_retries=2`, **plantillas y fallback desactivados**, oráculo con `tipos_columnas`. Inicio 17:32:23, fin 17:40:04.

```
=== RESULTADO FINAL: correctas 2/10 (20.0%) | texto respaldado 6/10 | latencia media 36.88 s | origen {'llm': 8, 'sin_origen': 2} | recursos {'size_bytes': 5804392447, 'size_vram_bytes': 5804392447, 'pct_gpu': 100.0, 'context_length': 8192} ===
```
La salida completa por pregunta está en `logs/baseline_01.log` (fuera de git) y en el JSON (versionado).

### Separar el efecto del evaluador: baseline_00 recalificado (`python -m eval.recalificar eval/baselines/baseline_00_actual.json`)
```
q1_pedidos_totales                     antes=✅  ahora=✅  coincide (columna referencia -> columna modelo: {0: 0})
q2_categoria_mas_ingresos              antes=✅  ahora=✅  coincide (columna referencia -> columna modelo: {0: 0, 1: 1})
q3_pct_clientes_recurrentes            antes=❌  ahora=❌  valores: ninguna asignación de columnas del modelo coincide con la referencia dentro de tolerancia
q4_categorias_mas_compra_unica         antes=❌  ahora=❌  valores: ninguna asignación de columnas del modelo coincide con la referencia dentro de tolerancia
q5_retraso_baja_calificacion           antes=✅  ahora=❌  valores: ninguna asignación de columnas del modelo coincide con la referencia dentro de tolerancia
q6_metodo_pago_mayor_venta_promedio    antes=✅  ahora=❌  valores: ninguna asignación de columnas del modelo coincide con la referencia dentro de tolerancia
q7_estado_mas_pedidos_entregados       antes=✅  ahora=❌  el SQL no ejecuta: no such column: customer_state
q8_tiempo_promedio_entrega             antes=❌  ahora=❌  valores: ninguna asignación de columnas del modelo coincide con la referencia dentro de tolerancia
q9_pedidos_sin_entrega                 antes=✅  ahora=✅  coincide (columna referencia -> columna modelo: {0: 0})
q10_ticket_promedio_pedido             antes=❌  ahora=❌  valores: ninguna asignación de columnas del modelo coincide con la referencia dentro de tolerancia
TOTAL antes 6/10  ahora 3/10
```

### Tabla comparativa 00 vs 01

| Pregunta | baseline_00 (evaluador viejo) | baseline_00 recalificado | baseline_01 | Qué pasó en 01 |
|---|---|---|---|---|
| q1 pedidos totales | ✅ | ✅ | ✅ | `SELECT COUNT(*) FROM orders` |
| q2 categoría + ingresos | ✅ | ✅ | ❌ | `bed_bath_table 1,495,699.31`: unió `order_payments` y `vw_ventas_pedido` → filas duplicadas |
| q3 % recurrentes | ❌ | ❌ | ❌ | 100.0: filtra `es_recurrente = 1` antes de dividir |
| q4 top 5 compra única | ❌ | ❌ | ❌ | 1er intento cortado a los 60 s; el 2.º devolvió 0 filas |
| q5 retraso vs calificación | ✅ | ❌ | ❌ | El clasificador la dividió en 2 sub-consultas `SELECT *` |
| q6 método de pago | ✅ | ❌ | ❌ | El clasificador la dividió en 2; la 2.ª sub-pregunta (sobre `review_score`) no tiene nada que ver |
| q7 estado | ✅ | ❌ | ❌ | `customer_state` no existe en `vw_entregas_retrasos` |
| q8 días de entrega | ❌ | ❌ | ❌ | −11.18: usa la fecha **estimada** en vez de la de compra (igual que en 00, aunque ya no hay ejemplo few-shot de "retraso") |
| q9 sin entrega | ✅ | ✅ | ✅ | |
| q10 ticket promedio | ❌ | ❌ | ❌ | 140.37: promedio por artículo, no por pedido |
| **Total** | **6/10 (60 %)** | **3/10 (30 %)** | **2/10 (20 %)** | |

Lectura (sin ir más allá de los datos):
- **El evaluador nuevo explica 3 de los 4 puntos de caída** (6 → 3): son exactamente los falsos positivos documentados en BASELINE.md.
- La diferencia 3 → 2 viene de los cambios del pipeline (few-shot de la Fase 1, sin plantillas, redacción de q2/q6). Es **una sola pregunta (q2)** en una sola corrida con `temperature=0.1`: no alcanza para atribuirla a ninguno de esos cambios.
- q6 se dividió en sub-consultas **después** de añadir "y de cuánto es ese promedio" (D-07): el clasificador interpretó la conjunción como dos temas. Es un efecto observado de mi cambio de redacción, y lo dejo anotado.
- La latencia de q1 (79.2 s) incluye recargar el modelo, que Ollama había descargado tras 5 min de inactividad. Para la Fase 4 hay que precalentar el modelo antes de medir.

**La cifra honesta del pipeline actual con este modelo es 2/10 (20 %).**

## Decisiones propias
D-06 (tolerancias), D-07 (estructura estricta y columnas requeridas; redacción de q2/q6) y D-08 (límite de 60 s). Ver DECISIONES.md.

## Reverificación del oráculo
Los 10 valores de referencia se recalcularon con `compute_ground_truth.py` y coinciden con el JSON (salidas en ENTORNO.md y en esta fase). Los cuatro que cambiaron por decisión (q2, q4, q6, q10) se cruzaron con pandas al centavo. Quedan **sin cruce independiente con pandas** q1, q3, q5, q7, q8 y q9; se cubren en la Fase 5 (verify_pandas 10/10).
