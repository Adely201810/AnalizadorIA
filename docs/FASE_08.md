# Fase 8 — El veredicto es del árbitro determinista; el juez-LLM solo explica

Fecha: 2026-10-10 · Estado: **COMPLETA** · Corrida: `eval/baselines/fase8_n3_cadena_juez.json`

## Qué se implementó
- **El veredicto (correcto/incorrecto) lo decide solo el árbitro** (`eval/comparador.py`, Fase 3). El juez no interviene: con `--cadena`, el verificador llama primero al árbitro, y su resultado es el que corta o continúa la cadena y el que se guarda en `correcto`.
- **El juez solo explica**: `diagnosticar()` dice qué parte del enfoque parece mal (se usa como pista con `--feedback juez` y queda en `diagnosticos_juez`).
- **Medición**: con `--juez`, en cada intento verificado el juez da además su **opinión** (`opinar()`: ¿responde la pregunta?), que se registra junto al veredicto del árbitro **sin influir en él**. El resumen cuenta coincidencias, **falsos aciertos** (el juez lo da por bueno, el árbitro no) y **falsos rechazos** (el juez lo rechaza, el árbitro lo acepta).

## Corrida
`python eval/run_eval.py --sin-plantillas --intentos 3 --cadena --feedback juez --juez` (oráculo v2, llama3.1 8B como generador **y** como juez, `temperature=0` para el juez). Inicio 19:43:17, fin 19:51:54.
```
=== RESULTADO FINAL: correctas 1/10 (10.0%) | texto respaldado 5/10 | latencia media 48.46 s | origen {'llm': 7, 'sin_origen': 3} | recursos {'size_bytes': 5804392447, 'size_vram_bytes': 5804392447, 'pct_gpu': 100.0, 'context_length': 8192} ===
=== JUEZ vs ÁRBITRO (por intento verificado): {'acierto_coinciden': 1, 'fallo_coinciden': 8, 'falso_acierto': 1, 'falso_rechazo': 0, 'sin_opinion': 0} ===
```

### Tabla juez frente a árbitro (10 intentos verificados)
| | Árbitro: correcto | Árbitro: incorrecto |
|---|---|---|
| **Juez: correcto** | 1 (coinciden) | **1 falso acierto** |
| **Juez: incorrecto** | **0 falsos rechazos** | 8 (coinciden) |

Concordancia: 9/10. Si el juez decidiera el veredicto, habría dado por buena 1 respuesta incorrecta de 2 que consideró buenas.

### Detalle (opiniones y diagnósticos del juez, del JSON)
```
== n03_pct_ingresos_top5_categorias | correcto False | intentos [('semantico', False), ('ejecucion', None), ('semantico', False)]
   juez=False árbitro=False | La consulta está calculando el porcentaje de pedidos, no de ingresos
   juez=False árbitro=False | La consulta está calculando el porcentaje de pedidos, no de ingresos
== n06_metodo_pago_mas_usado | correcto False | intentos [('semantico', False), ('semantico', False), ('semantico', False)]
   juez=False árbitro=False | La consulta devuelve el método de pago con más pedidos, pero no especifica que se refiere a pedidos válidos, solo que no están cancelados o no disponi
   juez=True árbitro=False | La consulta responde exactamente la pregunta solicitada, ya que muestra el método de pago más utilizado en pedidos válidos y el número de pedidos para
   juez=False árbitro=False | La consulta devuelve el método de pago con más pedidos, pero no especifica que se refiere a pedidos válidos, solo que no están cancelados o no disponi
== n07_mes_mayores_ingresos | correcto True | intentos [('ok', True)]
   juez=True árbitro=True | La consulta responde exactamente la pregunta solicitada, ya que selecciona el mes con mayores ingresos y los calcula correctamente.
== n08_categoria_mas_resenas_1_estrella | correcto False | intentos [('ejecucion', None), ('semantico', False), ('semantico', False)]
   juez=False árbitro=False | La consulta no considera solo pedidos válidos, solo filtra por categorías con al menos 100 reseñas
   juez=False árbitro=False | La consulta está calculando el porcentaje de reseñas de 1 estrella en cada categoría, pero la pregunta pide el porcentaje de reseñas de 1 estrella en 
== n09_categorias_mas_compra_unica | correcto False | intentos [('ejecucion', None), ('semantico', False), ('semantico', False)]
   juez=False árbitro=False | La consulta calcula la proporción de clientes que compraron una sola vez, pero la pregunta pide las categorías con mayor proporción de clientes que le
   juez=False árbitro=False | La consulta no calcula la proporción de clientes que compraron una sola vez, sino la proporción de clientes que compraron en cada categoría en relació
```
El falso acierto es n06: el juez aceptó una consulta que **no excluye pedidos cancelados** (cuenta 75,905 en vez de 75,618), el error más repetido de todo el benchmark.

## Lectura
- La concordancia es alta (9/10), pero el único caso discrepante es justamente el error más común del modelo, y en sentido peligroso (falso acierto). **Por eso el juez no debe decidir**: en el chat, su revisión se presenta como "revisión de sensatez", nunca como "respuesta verificada" (Fase 10).
- Muestra muy chica: solo 10 intentos llegaron al verificador, porque el resto falló antes (ejecución, descomposición). No alcanza para estimar las tasas de error del juez con precisión.
- El generador y el juez son el mismo modelo, así que sus errores pueden estar correlacionados. Con otro modelo como juez (por ejemplo qwen2.5-coder) se podría medir si baja el número de falsos aciertos.
