# Etapa 3 · Paso 2 — Conjunto de evaluación limpio y nueva base

Fecha: 2026-10-11 · Estado: **COMPLETO** · Commit de la base: `9100a04` · Pruebas: **66/66**

## Oráculo v4 (`eval/construir_oraculo_v4.py`, idempotente)
- **DESARROLLO = 30:** las 20 de DESARROLLO v3 más las 10 de PRUEBA v3, que ya se vio en la etapa 2. Campo `conjunto_v3` con el origen.
- **PRUEBA_2 = 20 preguntas nuevas**, escritas y congeladas en este paso, que **no se vuelven a ejecutar hasta la evaluación final**. Por tipo: simple 4, porcentaje 5, pedido_valido 4, ranking 3, varios_pasos 4 (campo `tipo`). Las preguntas están en `eval/ground_truth_olist.json` (`conjunto: "prueba_2"`); aquí solo van sus ids, para no repetirlas en la documentación.
  - **simple:** p2_01-p2_04
  - **porcentaje:** p2_05-p2_09
  - **pedido_valido:** p2_10-p2_13
  - **ranking:** p2_14-p2_16
  - **varios_pasos:** p2_17-p2_20
- **Verificación:** cada referencia se ejecutó en SQL (solo lectura) y se recalculó con pandas desde los CSV, de forma independiente (`python -m dashboard.verify_pandas`): **50/50 `[OK]`**. Ahora la verificación también falla si una pregunta del oráculo no tiene recálculo.
- **Empates:** en los rankings, el 1.º no empata con el 2.º. El caso más justo es p2_19: 4.821 frente a 4.809, una diferencia de 0.012, apenas mayor que la tolerancia de 0.01 para decimales.
- **Reconstrucción:** dos ejecuciones dan el mismo archivo (sha1 idéntico).

## Protección contra fugas
- `tests/test_heldout.py`: PRUEBA_2 protegida igual que antes PRUEBA (few-shot, clasificador, resultados en el prompt, bitácora, `eval.ab` la rechaza y `run_eval` usa DESARROLLO por defecto).
- **Principio de la etapa 3** (nueva prueba `TestContextoNoDerivaDelOraculo`): ningún fragmento de **4 palabras** de ninguna de las 50 preguntas puede aparecer en el prompt.
  - Con 5 o 6 palabras no se detectaba la nota que calcaba n05.
  - Con 4 sí; además atrapó una frase mía que coincidía con n08 ("de reseñas de 1"), que reescribí.
- **Disyunción con los few-shot:** una pregunta inicial de PRUEBA_2 (cuotas máximas con tarjeta) chocaba con un ejemplo del contexto (texto 0.364, SQL 0.500). **Se reemplazó antes de congelar.**
- **Falsos positivos corregidos en la prueba de valores:** el ayudante `formas_de_valor` genera variantes ×100 y ÷100, pensadas para porcentajes. Un conteo de 1529 producía "15" (choca con "15+") y el día 1 producía "100.0" (choca con `100.0 *`). Para conteos ahora solo cuenta la forma entera exacta; se comprobó que "1529" y "1,529" siguen detectándose.
- **Similitud con DESARROLLO:** hay preguntas "hermanas" (misma estructura, otra condición; p. ej. p2_05 frente a x02, SQL 0.833). No es una fuga, porque DESARROLLO no entra al contexto, pero hace que PRUEBA_2 se parezca a DESARROLLO más que una muestra independiente.

## D-27: notas que calcaban el oráculo
Antes de medir la base se reescribieron las 2 notas detectadas en el Paso 1: la de n05 ("peso del flete sobre el precio") y la de q5 v1 ("umbral de retraso"). Ver D-27.

## Nueva base (DESARROLLO 30, 3 repeticiones)

| Configuración | Aciertos r1, r2, r3 | Media | % | Wilson sobre 90 respuestas | Wilson sobre 30 preguntas (mayoría de 3) | Latencia | Prompt |
|---|---|---|---|---|---|---|---|
| **Base etapa 3, T=0.3** | 13, 14, 13 | **13.33** | 44.4 | 34.6–54.7 | 14/30 → **30.2–63.9** | 13.08 s | 13,148 caracteres |
| Control, mismo commit, T=0.1 | 16, 16, 17 | 16.33 | 54.4 | 44.2–64.3 | 16/30 → 36.1–69.8 | 13.36 s | 13,148 caracteres |

Salida exacta en `logs/e3_base.log` y `logs/e3_control_t01.log`; corridas en `eval/baselines/etapa3/{base,control_t01}_r{1,2,3}.json`.

### Lectura (con evidencia)
1. **D-27 tenía efecto real: n05 pasa de 3/3 (etapa 2) a 0/3, tanto a T=0.3 como a 0.1.** Antes, el modelo copiaba la fórmula de la nota que calcaba la pregunta (`SUM(freight_value)/SUM(price)` por `customer_state`); sin ella agrupa por `seller_state` y no une `order_items`. **Parte de la cifra de la etapa 2 venía de una nota contaminada.** Es la corrección esperada, no una regresión.
2. **La temperatura 0.3 cuesta unos 3 aciertos** frente a 0.1 con el mismo código (13.33 frente a 16.33). Y **no aporta mucha variabilidad útil**: cambia el SQL final en 24 de 30 preguntas (16 de 30 a 0.1), pero el resultado (acierto o fallo) es mixto solo en 2 de 30 preguntas (1 de 30 a 0.1). Casi todas las preguntas aciertan o fallan siempre.
3. **Decisión:** se mantiene **0.3** para todas las corridas de la etapa 3, como se pidió. Los A/B comparan siempre a la misma temperatura, así que las conclusiones relativas valen igual. Pero las cifras absolutas a 0.3 **subestiman** lo que hace el chat, que usa 0.1. Queda para tu revisión (D-28).

### Causas de fallo de la base (`eval/causas.py`, 3 corridas, 50 fallos)
d_vista_agregada 18 · otro 16 · c_denominador 9 · d_multiplicidad 6 · b_sin_filtro_valido 1. (Recordatorio de la etapa 2: `d_vista_agregada` está inflada, porque cuenta cualquier "no such column" con una vista en el SQL.)
