# Etapa 2 · Paso 3 — Mejoras una a una, A/B con repeticiones (solo DESARROLLO)

Fecha: 2026-10-11 · Estado: **COMPLETO** · Conjunto: **DESARROLLO (20 preguntas)**; PRUEBA no se usó.
Ollama 0.40.3 (se actualizó solo durante el paso; las corridas en 0.40.2 quedaron archivadas en `eval/baselines/etapa2/ollama_0402/` y no se mezclan).

## Método
- `eval/ab.py`: corre `run_eval.py --sin-plantillas --conjunto desarrollo` K=3 veces con una configuración (variables de entorno) y resume aciertos, media, mínimo, máximo, intervalo de Wilson al 95 % sobre las 60 respuestas y aciertos por pregunta. Rechaza `prueba`.
- `eval/ab_acumulativo.py`: prueba las mejoras **acumulativamente**, cada una sobre la última conservada, con la regla **D-23**: se conserva si `media(nueva) ≥ media(actual) + 1` **y** `mínimo(nueva) ≥ media(actual)`.
- `eval/causas.py`: asigna a cada fallo UNA causa (orden a > d_vista > b > d_multiplicidad > c > otro). Es una heurística sobre el SQL y los errores, no una revisión manual.
- Cada mejora está detrás de un interruptor de entorno **apagado por defecto**. Con todos apagados, el prompt es **idéntico byte a byte** al anterior (verificado). Las pruebas pasan 57/57 por defecto y 57/57 con todos los interruptores encendidos.

## Causas medidas antes de mejorar (3 corridas × 20 preguntas)

| Causa | base (con clasificador) | a: sin clasificador |
|---|---|---|
| a_descompuesta | 15 | 0 |
| d_vista_agregada | 14 | 16 |
| d_multiplicidad | 9 | 9 |
| b_sin_filtro_valido | 4 | 5 |
| c_denominador | 2 | 2 |
| otro | 7 | 13 |
| **fallos totales** | **51** | **45** |

**(d) causa 25 de los 45 fallos** de la configuración sin clasificador (16 por vista agregada y 9 por multiplicidad). Ejemplo típico de vista agregada (x05, x17): `SELECT seller_id, SUM(price) FROM vw_ingresos_por_vendedor WHERE order_status NOT IN (...)`. Esa vista no tiene `price` ni `order_status`.

## Resultados del A/B (llama3.1 8B, 3 repeticiones cada uno)

| Configuración | Aciertos r1, r2, r3 | Media | Mín.–máx. | % | Wilson 95 % | Latencia media | Decisión |
|---|---|---|---|---|---|---|---|
| base (clasificador encendido) | 3, 3, 3 | 3 | 3–3 | 15.0 | 8.1–26.1 | — | — |
| **a** sin clasificador | 5, 5, 5 | 5 | 5–5 | 25.0 | 15.8–37.2 | 14.33 s | **CONSERVADA** (+2; mín. 5 ≥ 3) |
| **b** + `vw_pedidos_validos` | 8, 9, 8 | 8.33 | 8–9 | 41.7 | 30.1–54.3 | 15.38 s | **CONSERVADA** (+3.33; mín. 8 ≥ 5) |
| c + regla de denominador (sobre b) | 6, 3, 6 | 5 | 3–6 | 25.0 | 15.8–37.2 | 14.9 s | REVERTIDA |
| d1 + documentación de vistas (sobre b) | 4, 5, 6 | 5 | 4–6 | 25.0 | 15.8–37.2 | 15.93 s | REVERTIDA |
| d2 + ocultar 3 vistas agregadas (sobre b) | 8, 6, 7 | 7 | 6–8 | 35.0 | 24.2–47.6 | 16.63 s | REVERTIDA |
| d3 + regla contra multiplicidad (sobre b) | 5, 5, 4 | 4.67 | 4–5 | 23.3 | 14.4–35.4 | 18.35 s | REVERTIDA |

Archivos: `eval/baselines/etapa2/{nombre}_r{1,2,3}.json`, `{nombre}_resumen.json` y el registro de decisiones `acumulativo.json`.

**Configuración final del Paso 3:** `TEXT2SQL_CLASIFICADOR=0`, `TEXT2SQL_VISTA_VALIDOS=1`.

### Lectura
- **(a)** El clasificador descomponía 5 preguntas de una sola consulta en cada corrida y ninguna se recuperaba. Al quitarlo desaparecen esas 15 respuestas descompuestas y aparecen 2 aciertos estables (n05, x02).
- **(b)** Es la mayor ganancia. Con `vw_pedidos_validos` el modelo parte de una fila por pedido ya filtrada (la usa en 49 de los 60 SQL finales). n09 pasa de 0/3 a 3/3 y x05 de 0/3 a 2/3.
- **(c), (d1) y (d3)** son texto extra en el prompt y **empeoran**: bajan a 4.67–5 de media. La hipótesis, no demostrada, es que un modelo de 8B se dispersa con más reglas. Con (c), los fallos `c_denominador` suben de 3 a 8.
- **(d2)** gana n01 (3/3) pero pierde otras preguntas. La media de 7 queda por debajo de 8.33, así que se revierte. Es la única de las (d) que reduce los fallos por vista (17 → 12).

### Causas tras b (3 corridas)

| Causa | b | c | d1 | d2 | d3 |
|---|---|---|---|---|---|
| d_vista_agregada | 17 | 17 | 19 | 12 | 19 |
| d_multiplicidad | 10 | 9 | 5 | 9 | 8 |
| c_denominador | 3 | 8 | 5 | 5 | 6 |
| b_sin_filtro_valido | 0 | 0 | 1 | 0 | 1 |
| otro | 5 | 11 | 15 | 13 | 12 |

**Límite de la medición:** después de b, el modelo usa `vw_pedidos_validos` en casi todos los SQL. La regla "no such column + vw_ en el SQL" atribuye entonces a `d_vista_agregada` errores de columna que no tienen que ver con vistas agregadas. Los errores explícitos de "la tabla/vista 'vw_…' no tiene la columna" sí cambian de vista (en b: vw_ingresos_por_categoria 9, vw_pedidos_validos 4, vw_retraso_por_rango 2), pero la categoría está inflada.

## Comparación de modelos (configuración final, DESARROLLO, 3 repeticiones)

Configuración: `TEXT2SQL_CLASIFICADOR=0`, `TEXT2SQL_VISTA_VALIDOS=1`, N=2, sin plantillas. Ollama 0.40.3.

| Modelo | Aciertos r1, r2, r3 | Media | Mín.–máx. | % | Wilson 95 % | Latencia media |
|---|---|---|---|---|---|---|
| **llama3.1 8B** (por defecto) | 8, 9, 8 | 8.33 | 8–9 | 41.7 | 30.1–54.3 | 15.38 s |
| qwen2.5-coder 7B | 8, 8, 9 | 8.33 | 8–9 | 41.7 | 30.1–54.3 | 18.74 s |
| llama3.2 3B | 3, 2, 3 | 2.67 | 2–3 | 13.3 | 6.9–24.2 | 15.59 s |

Aciertos por pregunta (de 3; solo las que algún modelo acertó):

| Pregunta | llama3.1 | qwen | llama3.2 |
|---|---|---|---|
| n01_pct_clientes_recurrentes | 0 | 3 | 0 |
| n03_pct_ingresos_top5_categorias | 0 | 3 | 0 |
| n05_estado_mayor_peso_flete | 3 | 0 | 3 |
| n07_mes_mayores_ingresos | 3 | 3 | 0 |
| n09_categorias_mas_compra_unica | 3 | 0 | 0 |
| x02_pct_entregas_con_retraso | 3 | 3 | 1 |
| x03_flete_promedio_por_articulo | 0 | 3 | 0 |
| x04_pct_resenas_5_estrellas | 3 | 3 | 0 |
| x05_vendedor_mas_ingresos | 2 | 1 | 0 |
| x10_categoria_precio_promedio_mas_alto | 2 | 0 | 1 |
| x17_top2_ciudades_vendedores | 0 | 3 | 3 |
| x18_peso_promedio_furniture_decor | 3 | 0 | 0 |
| x19_anio_mas_ingresos | 3 | 3 | 0 |

**Lectura:** llama3.1 y qwen **empatan exactamente** en media e intervalo, pero aciertan preguntas distintas: solo coinciden en 5 de las 13. La diferencia entre modelos es de "qué preguntas", no de "cuántas". llama3.2 3B es claramente peor. Según la regla del Paso 5 (cambiar solo si el candidato es **mejor** en DESARROLLO), el modelo por defecto **no cambia** (D-25).

## Configuración final que queda por defecto (D-25)
- `llm/text_to_sql.py`: clasificador **apagado** por defecto (`TEXT2SQL_CLASIFICADOR=1` lo enciende).
- `llm/schema_context.py`: `vw_pedidos_validos` y su regla **en el prompt** por defecto (`TEXT2SQL_VISTA_VALIDOS=0` lo quita).
- c, d1, d2 y d3 siguen en el código, apagadas, para poder repetir el experimento.
- 3 archivos de prueba (`test_bitacora`, `test_cadena`, `test_clasificacion`) usan guiones cuya 1.ª respuesta es la del clasificador. Al cambiar el valor por defecto fallaron 14 pruebas y 1 dio error (los guiones se desplazaron una posición). Ahora encienden el clasificador en `setUpModule` y lo restauran en `tearDownModule`. Suite: **57/57**.

## Decisiones propias
- D-23 (regla de conservación) y D-24 (vista nueva y retoques de c y d2), en `docs/DECISIONES.md`.
- La base se volvió a medir en Ollama 0.40.3 porque la actualización automática ocurrió a mitad del A/B. Con 0.40.2 la base también daba 3/3/3.
- Los primeros ejemplos de (c) fallaron la prueba de disyunción (uno frente a x16, de PRUEBA) y se reemplazaron antes de cualquier corrida.
