# Fase 6 — N intentos reales por pregunta y juez-LLM como componente separado

Fecha: 2026-10-10 · Estado: **COMPLETA** · Código: commit `a6b75fb` · Pruebas: `tests.test_cadena` (8/8), suite completa 45/45

## Qué se implementó
- **`n_intentos` reemplaza a `max_retries`** (`llm/text_to_sql.py`). Antes, la bandera `ya_reintento_por_problema` limitaba a **un** reintento sin importar `max_retries` (`max_retries=2` daba como máximo 2 intentos). Ahora `n_intentos` = intentos **totales**: cada problema consume uno y un rechazo de seguridad corta siempre. Por defecto 2 (`TEXT2SQL_N_INTENTOS`), que reproduce el comportamiento efectivo anterior en el chat (D-13).
- **README y docs/DEPLOY.md** corregidos: describen los reintentos tal como funcionan.
- **Juez-LLM** en `llm/juez.py`, separado del generador. Tiene `opinar` (Fase 8), `diagnosticar` (Fase 7) y `evaluar_sensatez` (Fase 10), usa `temperature=0`, **nunca recibe valores de la referencia** y nunca decide el veredicto.
- `eval/run_eval.py --intentos N` (sustituye a `--max-retries`).

## Prueba de que N controla de verdad los intentos
`tests/test_cadena.py::TestNIntentos` (cliente guionado con un SQL roto en cada intento): para N = 1, 2, 3 y 5 se registran exactamente N intentos de tipo `ejecucion`. Suite completa tras el cambio:
```
Ran 45 tests in 112.482s

OK
```

## Corrida con N=3 (`eval/baselines/fase6_n3_cadena_generico.json`)
`python eval/run_eval.py --sin-plantillas --intentos 3 --cadena --feedback generico` (oráculo v2, llama3.1 8B, `temperature=0.1`). Inicio 19:26:29, fin 19:34:34.
```
=== RESULTADO FINAL: correctas 1/10 (10.0%) | texto respaldado 5/10 | latencia media 44.24 s | origen {'llm': 7, 'sin_origen': 3} | recursos {'size_bytes': 5804392447, 'size_vram_bytes': 5804392447, 'pct_gpu': 100.0, 'context_length': 8192} ===
=== CLASIFICACIÓN FINAL (por pregunta): {'ok': 1, 'ejecucion': 2, 'semantico': 7, 'seguridad': 0, 'infra': 0} ===
```
Intentos por pregunta (`tipo_evaluado`, `verificado`):
```
n01_pct_clientes_recurrentes | correcto False | intentos 3 | [('ejecucion', None), ('ejecucion', None), ('ejecucion', None)]
n02_calificacion_retraso_vs_a_tiempo | correcto False | intentos 2 | [('semantico', None), ('semantico', None)]
n03_pct_ingresos_top5_categorias | correcto False | intentos 3 | [('semantico', False), ('semantico', False), ('semantico', False)]
n04_vendedores_mala_calificacion | correcto False | intentos 3 | [('ejecucion', None), ('ejecucion', None), ('ejecucion', None)]
n05_estado_mayor_peso_flete | correcto False | intentos 3 | [('ejecucion', None), ('semantico', None), ('semantico', None)]
n06_metodo_pago_mas_usado | correcto False | intentos 3 | [('semantico', False), ('semantico', False), ('semantico', False)]
n07_mes_mayores_ingresos | correcto True | intentos 1 | [('ok', True)]
n08_categoria_mas_resenas_1_estrella | correcto False | intentos 3 | [('semantico', False), ('semantico', False), ('semantico', False)]
n09_categorias_mas_compra_unica | correcto False | intentos 3 | [('ejecucion', None), ('semantico', False), ('semantico', False)]
n10_estado_mas_clientes_por_vendedor | correcto False | intentos 4 | [('semantico', None), ('ejecucion', None), ('ejecucion', None), ('ejecucion', None)]
```
- N=3 se respeta: ninguna pregunta simple pasa de 3 intentos. n10 suma 4 porque el clasificador la **descompuso** en 2 sub-preguntas, cada una con sus intentos. Las preguntas descompuestas (n02, n05, n10) no pasan por el verificador (`verificado=None`).
- El único acierto (n07) llegó en el **primer** intento. En el benchmark (N=2, sin cadena) esa misma pregunta falló: es variación del modelo, no efecto de N.

## Lectura
Subir N a 3 **no recuperó ninguna pregunta** (detalle en FASE_07.md). Con este modelo, más intentos solo suman latencia: 44.2 s por pregunta frente a 36.5 s del benchmark. Por eso el valor por defecto del chat queda en 2.

## Decisiones propias
D-13 (n_intentos y su valor por defecto) y D-14 (juez separado; opina solo si se pide).
