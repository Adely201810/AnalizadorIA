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
