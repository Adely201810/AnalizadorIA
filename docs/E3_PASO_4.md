# Etapa 3 · Paso 4 — Evaluación única de PRUEBA_2

Fecha: 2026-10-12 · Estado: **COMPLETO** · Configuración congelada: **commit `740066a`** + `TEXT2SQL_AUTOCONSISTENCIA=5`, T = 0.3, N=2, sin plantillas (D-30) · Ollama 0.40.3.
PRUEBA_2 se evaluó **una sola vez** (00:38–01:53), 3 repeticiones con cada modelo. Después **no se ajustó nada**: el único cambio posterior es el modelo por defecto, que aplica una regla fijada antes de ver los resultados (D-30, D-31).

## Salida exacta (`logs/e3_prueba2.log`)
```
commit 740066a inicio 00:38
[llama31 r1] exit 0 | === RESULTADO FINAL: correctas 14/20 (70.0%) | texto respaldado 16/20 | latencia media 36.85 s | origen {'llm'
[llama31 r2] exit 0 | === RESULTADO FINAL: correctas 13/20 (65.0%) | texto respaldado 15/20 | latencia media 32.59 s | origen {'llm'
[llama31 r3] exit 0 | === RESULTADO FINAL: correctas 12/20 (60.0%) | texto respaldado 16/20 | latencia media 32.66 s | origen {'llm'
[qwen25-coder r1] exit 0 | === RESULTADO FINAL: correctas 11/20 (55.0%) | texto respaldado 13/20 | latencia media 39.73 s | origen {'llm'
[qwen25-coder r2] exit 0 | === RESULTADO FINAL: correctas 14/20 (70.0%) | texto respaldado 16/20 | latencia media 37.35 s | origen {'llm'
[qwen25-coder r3] exit 0 | === RESULTADO FINAL: correctas 13/20 (65.0%) | texto respaldado 15/20 | latencia media 41.3 s | origen {'llm':
fin 01:53
```

## Resumen

| Modelo | Aciertos r1, r2, r3 | Media | Mín.–máx. | % | **Wilson sobre las 20 PREGUNTAS** (acierta ≥ 2 de 3) | Wilson sobre 60 respuestas (subestima la incertidumbre) | Latencia |
|---|---|---|---|---|---|---|---|
| llama3.1 8B | 14, 13, 12 | 13.00 | 12–14 | 65.0 | 13/20 → **43.3–81.9 %** | 52.4–75.8 % | 34.0 s |
| qwen2.5-coder 7B | 11, 14, 13 | 12.67 | 11–14 | 63.3 | 12/20 → **38.7–78.1 %** | 50.7–74.4 % | 39.5 s |

## Por tipo de pregunta
| Tipo | Preguntas | llama3.1 respuestas | llama3.1 preguntas (≥2/3) | qwen respuestas | qwen preguntas (≥2/3) |
|---|---|---|---|---|---|
| simple | 4 | 12/12 | 4/4 | 9/12 | 3/4 |
| porcentaje | 5 | 7/15 | 2/5 | 10/15 | 3/5 |
| pedido_valido | 4 | 8/12 | 3/4 | 6/12 | 2/4 |
| ranking | 3 | 9/9 | 3/3 | 7/9 | 2/3 |
| varios_pasos | 4 | 3/12 | 1/4 | 6/12 | 2/4 |

## Por pregunta (aciertos de 3)
| Pregunta | Tipo | llama3.1 | qwen2.5-coder |
|---|---|---|---|
| p2_01_vendedores_rio | simple | 3/3 | 0/3 |
| p2_02_pagos_debito | simple | 3/3 | 3/3 |
| p2_03_productos_mas_10kg | simple | 3/3 | 3/3 |
| p2_04_resenas_con_mensaje | simple | 3/3 | 3/3 |
| p2_05_pct_entrega_7_dias | porcentaje | 3/3 | 3/3 |
| p2_06_pct_vendedores_sin_ventas | porcentaje | 0/3 | 1/3 |
| p2_07_pct_ingresos_vendedores_mg | porcentaje | 0/3 | 0/3 |
| p2_08_pct_resenas_titulo_bajas | porcentaje | 3/3 | 3/3 |
| p2_09_pct_articulos_flete_mayor_precio | porcentaje | 1/3 | 3/3 |
| p2_10_pedidos_validos_2017 | pedido_valido | 3/3 | 3/3 |
| p2_11_ticket_promedio | pedido_valido | 0/3 | 1/3 |
| p2_12_precio_promedio_nov_2017 | pedido_valido | 2/3 | 0/3 |
| p2_13_articulos_clientes_rs | pedido_valido | 3/3 | 2/3 |
| p2_14_categoria_mas_articulos | ranking | 3/3 | 1/3 |
| p2_15_top3_estados_vendedores | ranking | 3/3 | 3/3 |
| p2_16_dia_semana_mas_pedidos | ranking | 3/3 | 3/3 |
| p2_17_gasto_clientes_2_pedidos | varios_pasos | 3/3 | 3/3 |
| p2_18_dias_entrega_por_flete | varios_pasos | 0/3 | 0/3 |
| p2_19_vendedor_mejor_calificado | varios_pasos | 0/3 | 0/3 |
| p2_20_pct_pagado_varios_metodos | varios_pasos | 0/3 | 3/3 |

## DESARROLLO frente a PRUEBA_2 (¿sobreajuste?)

| Modelo | DESARROLLO total (30) | DESARROLLO solo preguntas nuevas (20, sin las 10 necesidades) | PRUEBA_2 (20) |
|---|---|---|---|
| llama3.1 + E7 | 15.33/30 = 51.1 % | 42/60 = **70.0 %** (por pregunta 14/20, 48.1–85.5 %) | 39/60 = **65.0 %** (13/20, 43.3–81.9 %) |
| qwen2.5-coder + E7 | 18.33/30 = 61.1 % | 44/60 = **73.3 %** (15/20, 53.1–88.8 %) | 38/60 = **63.3 %** (12/20, 38.7–78.1 %) |

- **llama3.1:** PRUEBA_2 queda 5 puntos por debajo de las preguntas comparables de DESARROLLO, con intervalos casi superpuestos. **No es una caída notable: no hay señal clara de sobreajuste.** Sí lo hay en un sentido acotado: las mejoras se eligieron en DESARROLLO, y en PRUEBA_2 no se midió la base sin E7, así que **no hay cifra de mejora en PRUEBA_2**, solo la absoluta.
- **qwen2.5-coder:** su ventaja de DESARROLLO (+3 frente a llama3.1) **no se replicó** en PRUEBA_2 (−0.33). Venía sobre todo de las 10 necesidades (11/30 frente a 4/30), que no existen en PRUEBA_2. En "varios pasos" de PRUEBA_2 sí gana (6/12 frente a 3/12), y pierde en simples, pedido válido y rankings. **Es la señal de selección/sobreajuste más clara de la etapa:** el modelo que ganó en DESARROLLO no ganó en PRUEBA_2.
- **Porcentajes**, de nuevo el punto débil para llama3.1: 7/15. p2_06 y p2_07 fallan 0/3 con los dos modelos.

## Modelo por defecto (D-31)
Regla establecida (etapa 2) y umbral fijado antes de ver PRUEBA_2 (D-30): **cambiar solo si el candidato es mejor en DESARROLLO (D-23) y no peor en PRUEBA_2 (media ≥ la del actual − 1)**.
- DESARROLLO: qwen 18.33 frente a 15.33 → mejor (D-23 cumplida).
- PRUEBA_2: qwen 12.67 frente a llama3.1 13.00 → no es peor (12.67 ≥ 12.00).
- **Por la regla, el modelo por defecto pasa a ser qwen2.5-coder** (`llm/ollama_client.py`). **Revertir:** `OLLAMA_MODEL=llama3.1:8b-instruct-q4_K_M`, o restaurar la línea desde `740066a`.
- **Para revisión del usuario:** la regla se cumple, pero la ventaja no se replicó en PRUEBA_2 y qwen es más lento (+16 % en PRUEBA_2, +33 % en DESARROLLO). Además, el chat no usa la autoconsistencia (D-30) y, sin ella, en la etapa 2 los dos modelos empataban.
