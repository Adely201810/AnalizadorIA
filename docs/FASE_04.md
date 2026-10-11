# Fase 4 — Benchmark de modelos locales sobre el oráculo unificado (v2)

Fecha: 2026-10-10 · Estado: **COMPLETA (con una salvedad de velocidad, ver abajo)** · Resultados: `eval/baselines/fase4_*.json`

## Modelos (decisión 4 del usuario: ≤ 2 adicionales, ≤ 10 GB, caben en 8 GB de VRAM, distintos en familia o tamaño)

Existencia y tamaño verificados en el registro de Ollama antes de descargar:
```
qwen2.5-coder:7b-instruct-q4_K_M -> EXISTE | total 4.683 GB (4683087074 bytes)
llama3.2:3b-instruct-q4_K_M -> EXISTE | total 2.019 GB (2019392628 bytes)
qwen2.5-coder:3b-instruct-q4_K_M -> EXISTE | total 1.930 GB (1929912139 bytes)
qwen2.5:7b-instruct-q4_K_M -> EXISTE | total 4.683 GB (4683086845 bytes)
```
Elegidos: **qwen2.5-coder:7b** (código, otra familia) y **llama3.2:3b** (misma familia que el actual pero más chico, para aislar el efecto del tamaño). Total **6.70 GB**. Descargas: qwen 18:19:33 → 18:47:23; llama3.2 18:47:24 → ≈18:59. El modelo actual (`llama3.1:8b-instruct-q4_K_M`) entra en la comparación. **No se cambió el modelo por defecto.**

Antes de descargar, el espacio libre en C: había bajado de 22.67 a 14.47 GB porque `pagefile.sys` (Windows) creció a 17.7 GB, probablemente por la presión de memoria de las corridas. Tras las descargas quedaron 8.49 GB.

## Protocolo (`eval/benchmark_modelos.py`)
Igual para los 3 modelos: oráculo v2, sin plantillas, `temperature=0.1`, `num_ctx=8192`, `max_retries=2` (código del commit `4562e4e`, anterior a la Fase 6). Por modelo:
1. Se descarga de la VRAM el modelo anterior (`keep_alive=0`).
2. Precalentamiento (la carga no cuenta en la latencia por pregunta).
3. Desglose de latencia de la llamada que genera SQL (`eval/medir_latencia.py`).
4. Evaluación completa, con un muestreo cada 5 s de `ollama ps` (VRAM) y de la RAM de `llama-server.exe`.

Se ejecutó desde un **git worktree aislado** (`git worktree add --detach … 4562e4e`), para que los cambios de código de la Fase 6, hechos en paralelo, no afectaran a la corrida. Inicio 19:01:26, fin 19:21:39.

**1 repetición por modelo** (D-16): con la velocidad anómala de llama3.1 (ver abajo) se estimaban ~25 min por corrida; al final fueron 4-7 min.

## Resultados (salida exacta de `python -m eval.benchmark_modelos`)
```
  repetición 1: exit 0 en 403.1 s | === RESULTADO FINAL: correctas 0/10 (0.0%) | texto respaldado 5/10 | latencia media 36.45 s | origen {'llm': 7, 'sin_origen': 3} | recursos {'size_bytes': 5804392447, 'size_vram_bytes': 5804392447, 'pct_gpu': 100.0, 'context_length': 8192} === | === CLASIFICACIÓN FINAL (por pregunta): {'ok': 0, 'ejecucion': 2, 'semantico': 8, 'seguridad': 0, 'infra': 0} === | === CLASIFICACIÓN POR INTENTO: {'ok': 0, 'ejecucion': 8, 'semantico': 10, 'seguridad': 0, 'infra': 0} ===
  repetición 1: exit 0 en 265.3 s | === RESULTADO FINAL: correctas 1/10 (10.0%) | texto respaldado 4/10 | latencia media 23.11 s | origen {'llm': 8, 'sin_origen': 2} | recursos {'size_bytes': 5119263374, 'size_vram_bytes': 5119263374, 'pct_gpu': 100.0, 'context_length': 8192} === | === CLASIFICACIÓN FINAL (por pregunta): {'ok': 1, 'ejecucion': 3, 'semantico': 6, 'seguridad': 0, 'infra': 0} === | === CLASIFICACIÓN POR INTENTO: {'ok': 1, 'ejecucion': 7, 'semantico': 9, 'seguridad': 0, 'infra': 0} ===
  repetición 1: exit 0 en 258.1 s | === RESULTADO FINAL: correctas 0/10 (0.0%) | texto respaldado 3/10 | latencia media 22.54 s | origen {'sin_origen': 8, 'llm': 2} | recursos {'size_bytes': 3093687172, 'size_vram_bytes': 3093687172, 'pct_gpu': 100.0, 'context_length': 8192} === | === CLASIFICACIÓN FINAL (por pregunta): {'ok': 0, 'ejecucion': 1, 'semantico': 9, 'seguridad': 0, 'infra': 0} === | === CLASIFICACIÓN POR INTENTO: {'ok': 0, 'ejecucion': 11, 'semantico': 15, 'seguridad': 0, 'infra': 0} ===

| Modelo | Precisión por repetición | Media | ok / ejec / sem / seg / infra (suma) | Latencia media por pregunta | Gen. tok/s | VRAM pico | % GPU mín | RAM llama-server pico | Carga |
|---|---|---|---|---|---|---|---|---|---|
| llama3.1:8b-instruct-q4_K_M | 0/10 | 0 % | 0 / 2 / 8 / 0 / 0 | 36.5 s | 3.6 | 5.80 GB | 100 % | 5636 MB | 31.6 s |
| qwen2.5-coder:7b-instruct-q4_K_M | 1/10 | 10 % | 1 / 3 / 6 / 0 / 0 | 23.1 s | 18.5 | 5.12 GB | 100 % | 7296 MB | 22.4 s |
| llama3.2:3b-instruct-q4_K_M | 0/10 | 0 % | 0 / 1 / 9 / 0 / 0 | 22.5 s | 65.3 | 3.09 GB | 100 % | 3653 MB | 10.7 s |
```
(Las líneas `###` con el desglose de latencia están completas en `logs/fase4_benchmark.log` y en `eval/baselines/fase4_resumen.json`.) "RAM llama-server" es el *working set* del proceso y **incluye el archivo del modelo mapeado en memoria**: no es RAM adicional a la VRAM.

### Por pregunta
| Necesidad | llama3.1 8B | qwen2.5-coder 7B | llama3.2 3B |
|---|---|---|---|
| n01_pct_clientes_recurrentes | ❌ ejecucion | ❌ ejecucion | ❌ semantico (descompuesta) |
| n02_calificacion_retraso_vs_a_tiempo | ❌ semantico (descompuesta) | ❌ semantico (descompuesta) | ❌ semantico (descompuesta) |
| n03_pct_ingresos_top5_categorias | ❌ semantico | ✅ ok | ❌ semantico (descompuesta) |
| n04_vendedores_mala_calificacion | ❌ ejecucion | ❌ ejecucion | ❌ ejecucion |
| n05_estado_mayor_peso_flete | ❌ semantico (descompuesta) | ❌ semantico | ❌ semantico (descompuesta) |
| n06_metodo_pago_mas_usado | ❌ semantico | ❌ semantico | ❌ semantico (descompuesta) |
| n07_mes_mayores_ingresos | ❌ semantico | ❌ semantico | ❌ semantico (descompuesta) |
| n08_categoria_mas_resenas_1_estrella | ❌ semantico | ❌ semantico | ❌ semantico (descompuesta) |
| n09_categorias_mas_compra_unica | ❌ semantico | ❌ ejecucion | ❌ semantico |
| n10_estado_mas_clientes_por_vendedor | ❌ semantico (descompuesta) | ❌ semantico (descompuesta) | ❌ semantico (descompuesta) |

Fallos "casi correctos" (cifras del JSON), que muestran que **no son un problema de tolerancia sino de definición**:
- n06: credit_card **75,905** (llama3.1 y qwen) frente a 75,618: cuentan también pedidos cancelados o no disponibles.
- n07: mes correcto (2017-11), pero 987,765.37 (llama3.1) y 995,028.84 (qwen) frente a 1,003,862.14: filtran otros estatus.
- n08: categoría correcta, pero 25.38 % / 25.95 % frente a 22.73 %: otro denominador.
- n09 (llama3.1): incluye el grupo **sin categoría** (`None`) en 3.er lugar, aunque la pregunta pide "con nombre de categoría".
- n05 (qwen): `RR, 0.29`, la fracción redondeada a 2 decimales (= 29 %) frente a 28.55 %. Queda fuera de la tolerancia de porcentajes (0.05 puntos) por el redondeo del modelo. **Es el único caso límite**; no se relajó la tolerancia después de ver el dato.

**El clasificador descompone preguntas de una sola consulta**: 3 de 10 en llama3.1, 2 en qwen y **8 en llama3.2**. Todas las necesidades v2 se resuelven con una consulta, así que cada descomposición es un fallo seguro. Es la mayor fuente de error que no depende del SQL.

## Latencia: causa medida (no solo el tamaño del esquema)
Desglose de la llamada que genera SQL (system prompt de 12,269 caracteres ≈ 3,170 tokens):

| Modelo | 1.ª llamada: evaluación del prompt | Siguientes (prefijo en caché) | Generación |
|---|---|---|---|
| llama3.1 8B | 65.07 s (48.7 tok/s) | 0.75 s / 0.73 s | 3.6 tok/s |
| qwen2.5-coder 7B | 21.68 s (146.2 tok/s) | 0.34 s | 17.3 tok/s |
| llama3.2 3B | 16.11 s (197.3 tok/s) | 0.27 s | 64.9 tok/s |

**Hipótesis comprobada y descartada:** que el clasificador y la síntesis, al usar otro system prompt, invalidaran la caché del esquema. Prueba con llama3.2:
```
1. SQL                             prompt_tokens= 3172 prompt_eval_s=  0.21
2. SQL otra vez (mismo system)     prompt_tokens= 3172 prompt_eval_s=  0.02
3. CLASIFICADOR (otro system)      prompt_tokens=  568 prompt_eval_s=  0.08
4. SQL tras el clasificador        prompt_tokens= 3172 prompt_eval_s=  0.02
```
**Conclusión:** el tamaño del esquema solo cuesta en la **primera** llamada tras cargar el modelo (y tras 5 min de inactividad, cuando Ollama lo descarga). El resto de la latencia es generación de tokens.

**Propuesta (no aplicada):** precalentar al arrancar la app una llamada con el system prompt del esquema y subir `OLLAMA_KEEP_ALIVE` (p. ej. a 30 min). **No** se propone recortar el esquema: ahorraría como mucho esa primera llamada y podría bajar la precisión.

## Salvedad de velocidad de llama3.1 (problema abierto)
A las 16:49, con la app de bandeja de Ollama, llama3.1 generaba a **36.32 tok/s**. Desde las ~17:50 (servidor relanzado a mano, ver FASE_02.md) va a **3.6-4.8 tok/s**, también con nada en paralelo:
```
load duration:        42.3419443s
prompt eval rate:     49.70 tokens/s
eval rate:            4.63 tokens/s
load duration:        15.8744ms
prompt eval rate:     4.55 tokens/s
eval rate:            4.83 tokens/s
NAME                           ID              SIZE      PROCESSOR    CONTEXT    RUNNER      UNTIL
llama3.1:8b-instruct-q4_K_M    46e0c10c039e    5.3 GB    100% GPU     4096       llamacpp    4 minutes from now
```
Hipótesis descartadas: (1) DLL de Git Bash/mingw en el proceso (no se cargó ninguna; sí se cargan capas Vulkan de Overwolf y RivaTuner, registradas en el sistema); (2) competencia por CPU, disco o RAM (repetido sin nada en paralelo: igual). qwen 7B, de tamaño similar, genera a 17-18 tok/s en el mismo estado, así que la anomalía afecta sobre todo a llama3.1. **Las latencias de llama3.1 de esta tabla no representan su velocidad normal**; repetir tras reiniciar Windows.

## Recomendación (basada en los datos, con su límite)
- **La muestra es demasiado chica para concluir sobre precisión:** 10 preguntas, 1 repetición, y la diferencia entre el mejor (1/10) y los otros (0/10) es **una sola pregunta**. Con estos números no se puede afirmar que un modelo sea más preciso que otro.
- Con esa salvedad, **qwen2.5-coder:7b** es el candidato a probar como modelo por defecto: misma o mejor precisión, **menos VRAM (5.12 frente a 5.80 GB)** y más rápido en el estado actual del equipo (de esto último no hay medición limpia de llama3.1). No lo cambié.
- **llama3.2:3b no es viable con el pipeline actual:** su clasificador descompone 8 de 10 preguntas.
- Lo que más subiría la precisión, por encima de cambiar de modelo, según el desglose: (1) no descomponer las preguntas de una consulta; (2) reforzar la definición de "pedido válido", que explica 3 de los casi-aciertos (n06, n07, n08). La Fase 6/9/7 mide si los reintentos con pistas recuperan estos casos.

## Decisiones propias
D-16 (protocolo: 1 repetición, worktree aislado, salvedad de velocidad). Ver DECISIONES.md.
