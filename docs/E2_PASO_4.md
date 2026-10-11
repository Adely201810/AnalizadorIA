# Etapa 2 · Paso 4 — Dashboard q01, mensaje de rechazo, métrica de fechas y bitácora

Fecha: 2026-10-11 · Estado: **COMPLETO** · Pruebas: **64/64** (57 + 5 de `test_mensaje_rechazo` + 2 de `test_bitacora`).
Ninguno de estos cambios altera lo que mide la evaluación: la evaluación no usa bitácora, el mensaje de rechazo solo cambia textos y q01 y la fecha son del dashboard.

## 1. q01 (Retención) sin recalcular CTEs
**Causa:** 4 consultas, y cada una volvía a calcular `resumen_cliente` (con `ROW_NUMBER()` sobre 98k pedidos); 3 de ellas calculaban además `ventas_validas` (112k artículos).
**Cambio:** 2 consultas, cada CTE se calcula **una vez**: `resumen_cliente`, con una fila por cliente, y ventas agrupadas por (categoría, cliente, estado). Las 4 tablas se derivan en pandas. El campo `sql` muestra las 2 consultas y cómo se deriva cada tabla.

| | Corrida 1 | Corrida 2 | Corrida 3 |
|---|---|---|---|
| Antes | 31.27 s | 31.59 s | 31.43 s |
| **Después** | **10.44 s** | **10.39 s** | **10.45 s** |

(Ollama descargado durante la medición, para que no compitiera por CPU ni disco.)

**Igualdad con el resultado anterior:** `respuesta_clave` es idéntica. 3 de las 4 tablas son iguales en valores **y** orden. En `tasa_recompra_por_categoria` las 44 filas y sus valores son iguales; solo cambió el orden de **4 pares empatados** (p. ej. furniture_decor y air_conditioning, ambos con 7.23 %), porque el `ORDER BY` anterior no desempataba. Ahora se desempata por nombre de categoría, de forma determinista.

**Contra pandas desde los CSV** (`verificar_q01_tablas`, nuevo en `dashboard/verify_pandas.py`): las 4 tablas, recalculadas desde los CSV sin pasar por olist.db, coinciden:
```
min 200
  [OK] q01 comparacion_recurrentes_vs_no: 2 filas iguales a pandas
  [OK] q01 top_10_categorias_recurrentes: 10 filas iguales a pandas
  [OK] q01 top_10_estados_recurrentes: 10 filas iguales a pandas
  [OK] q01 tasa_recompra_por_categoria: 44 filas iguales a pandas
min 50
  [OK] q01 comparacion_recurrentes_vs_no: 2 filas iguales a pandas
  [OK] q01 top_10_categorias_recurrentes: 10 filas iguales a pandas
  [OK] q01 top_10_estados_recurrentes: 10 filas iguales a pandas
  [OK] q01 tasa_recompra_por_categoria: 59 filas iguales a pandas
```
Prueba negativa: alterando a propósito una celda y quitando una fila, la verificación devuelve `[DIFF]` en ambas tablas. El resto de `verify_pandas` sigue en OK (oráculo 30/30).

## 2. Mensaje de rechazo: seguridad ≠ negativa del modelo
**Causa:** cuando el modelo contestaba con texto (p. ej. "No puedo ayudarte a generar una consulta SQL que actualice datos…"), `validate_select_only` lanzaba `SQLValidationError(motivo="no_es_sql")`. La clasificación por intento ya lo contaba como `ejecucion`, pero la cadena lo guardaba en `error_seguridad` y el chat decía "La consulta generada no es una lectura segura y fue rechazada".
**Cambio:**
- `_ResolucionSQL.rechazo_modelo` separado de `error_seguridad`.
- Nuevo `Text2SQLResult.tipo_error` ∈ {`seguridad`, `negativa_modelo`, `infra`}.
- Textos distintos en el chat (`MENSAJES_ERROR_CHAT`).
- El flujo **no cambió**: igual que antes, corta sin reintentar.

**Verificado con el modelo real en el chat** ("Actualiza el estatus de todos los pedidos cancelados a delivered."):
> El modelo no generó una consulta SQL para esta pregunta (respondió con texto). No se ejecutó nada. ¿Puedes reformularla, por ejemplo nombrando la métrica que buscas?

Detalle técnico: `El modelo no generó una consulta SQL; respondió con texto: «No puedo ayudarte a generar una consulta SQL que actualice datos en la base de datos. ¿Hay algo más en lo que pueda ayudarte?»`.
El rechazo de seguridad real (un `DELETE`) y la caída de Ollama están cubiertos con cliente guionado en `tests/test_mensaje_rechazo.py`.

## 3. Métrica "Rango de fechas" truncada
**Causa (medida en el navegador a 1366 px):** el valor `2016-09-04 → 2018-10-17` no cabe en 1/5 del ancho y `st.metric` lo cortaba como `2016-09-…`. Incluso `2016 – 2018` medía 175 px en una caja de 166 px.
**Cambio:**
- La métrica muestra `2016–2018`, en una columna un 30 % más ancha.
- Las fechas exactas van en el `help` de la métrica y en una línea debajo: "Pedidos registrados del 2016-09-04 al 2018-10-17 (fecha de compra)".

Medido después: a 1366 px, caja 207 px y texto 207 px (completo). A 1024 px, con la barra lateral abierta, se truncan **todas** las métricas, también `99,441`. Es un límite general del layout de 5 columnas y no se tocó; la línea con las fechas exactas se lee completa.

## 4. Bitácora: SELECT sin FROM
**Causa:** caso real repetido. En n01, llama3.1 escribe `SELECT ROUND(100.0 * COUNT(DISTINCT customer_unique_id) / (SELECT … FROM …), 2)`: el SELECT principal no tiene FROM. SQLite responde `no such column: customer_unique_id` y la bitácora registraba "la columna 'customer_unique_id' está en: customers, …", un diagnóstico falso porque la columna sí existe.
**Cambio:** `diagnostico_select_sin_from` (en `llm/bitacora.py`) mira el SQL **fuera de paréntesis y literales**. Si el SELECT principal no tiene FROM, registra una de dos entradas:
- `select_sin_from`, si SQLite dijo "no such column";
- `from_entre_parentesis`, si dijo 'near "FROM"' (p. ej. `ROUND(AVG(x) FROM t)`).

Cada una lleva un mensaje con la corrección y un ejemplo genérico (`t1`, `t2`). La pista del reintento dentro de la misma pregunta no cambió.

**Repetición sobre todos los errores de SQLite reales guardados** (426 intentos): 40 se diagnostican como `select_sin_from` (los 39 de n01 más uno con alias `c.`), 5 como `from_entre_parentesis` y los otros 381 mantienen su diagnóstico anterior. No hay falsos positivos.

**Demostración con el modelo real** (`eval/demo_bitacora_sin_from.py`; n01 de DESARROLLO; 6 corridas por condición; cada corrida con una bitácora temporal nueva):

| Configuración | Condición | Corridas con SELECT sin FROM | Intentos con SELECT sin FROM | Aciertos |
|---|---|---|---|---|
| sin `vw_pedidos_validos` (antes de b) | A: sin bitácora | **6/6** | **12/12** | 0/6 |
| sin `vw_pedidos_validos` (antes de b) | B: con la entrada en la bitácora | **0/6** | **0/6** | 0/6 |
| final (con `vw_pedidos_validos`) | A: sin bitácora | 1/6 | 1/7 | 1/6 |
| final (con `vw_pedidos_validos`) | B: con la entrada en la bitácora | 0/6 | 0/6 | 1/6 |

**Conclusión honesta:**
- **Demostrado:** con el modelo real, la entrada de la bitácora evita que se repita el error (12/12 → 0/6 intentos).
- **No demostrado:** que mejore la respuesta. En ambos casos queda 0/6, porque el modelo pasa a otro error de cálculo.
- Con la configuración final el error ya es raro (1 de 6 corridas), así que ahí la diferencia (1 frente a 0) es ruido.

Resultados: `eval/baselines/etapa2/p4_demo_bitacora_sin_from.json` (final) y `p4_demo_bitacora_sin_from_sin_vista_validos.json`.

## Decisiones propias
- D-26, en `docs/DECISIONES.md`.
- `.claude/launch.json` (arranque local de Streamlit para revisar en el navegador) no se versiona, porque lleva la ruta del venv de esta máquina.
