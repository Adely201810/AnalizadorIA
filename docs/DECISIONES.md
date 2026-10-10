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
