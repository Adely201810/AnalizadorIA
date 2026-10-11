# Fase 11 — Legibilidad del dashboard y deuda técnica de la UI

Fecha: 2026-10-10 · Estado: **COMPLETA** · Revisado en el navegador (Streamlit en `localhost`)

## Qué se cambió

### Chat (`app.py`)
- **Separación visual** pregunta/respuesta: mensajes de chat de Streamlit (usuario sobre fondo gris, asistente aparte) y una **línea divisoria** después de cada intercambio.
- **Detalle técnico en una sección colapsable**: "Detalle técnico (SQL, datos y diagnóstico)", con el SQL, la tabla, la revisión del juez (Fase 10) y el error técnico (en un bloque de código, ya no como texto gris pequeño).
- **El detalle técnico se muestra cuando falla Ollama.** Antes (`app.py:93-94`), `_render_detalle` salía si no había SQL, y el error se perdía. Ahora la sección se muestra **siempre que haya un error, abierta**, con el error concreto (`GET http://localhost:11434/api/tags no respondió (modelo configurado: …)`).

### Dashboard (`pages/1_Dashboard.py`)
- **HTML escapado**: `bloque_respuesta_clave` aplica `html.escape()` al texto antes de insertarlo con `unsafe_allow_html`. Nunca se inserta texto sin escapar (hoy el texto es determinista, pero así queda protegido si algún día viene de un modelo).
- **Jerarquía de títulos uniforme**: H1 para la página y H3 para las secciones ("Respuesta de referencia (una consulta)" y "Análisis ampliado"), con las preguntas en negrita. Antes, cada pestaña usaba `#####` (H5) bajo un `st.subheader`.
- **P3, carga lenta**: el PDF se genera **solo al pulsar "Generar reporte PDF"**. Además, **solo se calcula la sección elegida**: `st.tabs` ejecuta el contenido de *todas* las pestañas en cada carga, así que generar el PDF bajo demanda no bastaba (seguían corriendo los 10 análisis). Se reemplazó por un selector de sección (`st.radio` horizontal). El Resumen muestra las 10 respuestas de referencia, una consulta cada una.

## Mediciones

### Carga del dashboard, en frío (servidor recién arrancado), medida en el navegador
Indicador: el botón "Stop" de Streamlit visible mientras el script corre; muestreo cada 5-10 s con `performance.now()`.
- **Antes** (commit `3223ace`, desde un worktree en el puerto 8502): última muestra "corriendo" a **193 s** y primera "terminado" a **221 s** → **≈ 193–221 s**.
- **Después**: última "corriendo" a **25 s** y primera "terminado" a **30 s** → **≈ 25–30 s**, unas **7 veces más rápido**.
- Abrir la sección 1 (Retención) por primera vez: **30–40 s** (es q01). Las demás secciones tardan lo que su consulta (1.5-14 s).

### Índices para q01 (sobre una COPIA de la base; `python -m dashboard.medir_indices`)
```
copia: C:\Users\alexp\AppData\Local\Temp\claude\…\scratchpad\olist_copia_indices.db (198,574,080 bytes)
SIN índices (rep 1): {'q01': 32.24, 'q02': 1.49, 'q03': 5.63, 'q04': 8.01, 'q05': 5.66, 'q06': 6.99, 'q07': 2.61, 'q08': 5.29, 'q09': 13.37, 'q10': 13.7}
SIN índices (rep 2): {'q01': 32.65, 'q02': 1.49, 'q03': 5.57, 'q04': 8.08, 'q05': 5.68, 'q06': 7.0, 'q07': 2.58, 'q08': 5.3, 'q09': 13.54, 'q10': 13.65}
índices creados en la COPIA en 0.4 s: ['ix_orders_customer_id', 'ix_order_items_product_id', 'ix_order_items_seller_id', 'ix_order_reviews_order_id', 'ix_customers_unique_id']
CON índices (rep 1): {'q01': 38.85, 'q02': 1.5, 'q03': 5.9, 'q04': 8.62, 'q05': 5.91, 'q06': 7.34, 'q07': 2.7, 'q08': 5.45, 'q09': 17.76, 'q10': 15.09}
CON índices (rep 2): {'q01': 41.22, 'q02': 1.53, 'q03': 5.8, 'q04': 8.47, 'q05': 5.86, 'q06': 7.21, 'q07': 2.68, 'q08': 5.35, 'q09': 16.59, 'q10': 14.13}
hash olist.db antes: b8f81adbc24aa451 | después: b8f81adbc24aa451
```
**Los índices empeoran q01 (32 → 39-41 s) y q09 (13.4 → 16.6-17.8 s).** **No se aplicaron**: no se tocó el loader ni se reconstruyó la base (el hash de `db/olist.db` no cambió). La lentitud de q01 no viene de búsquedas sin índice; lo más probable es que las CTE que se usan varias veces se recalculen (D-18). Queda pendiente optimizar su SQL.

## Lo que se vio en la app (revisión real en el navegador)
- **Dashboard, Resumen**: título, 5 métricas, botón "Generar reporte PDF" (ya no genera solo), selector de 11 secciones (ocupa dos líneas a este ancho) y la tabla "Las 10 necesidades del dueño — respuesta de referencia" (p. ej. `pct_recurrentes: 3.04`). La métrica "Rango de fechas" se corta (`2016-0…`); ya pasaba antes, no se tocó.
- **Dashboard, sección 1**: `H1: 📈 Dashboard de verificación — Olist`, `H3: Respuesta de referencia (una consulta)` (tabla con `3.04` y el SQL en un desplegable), `H3: Análisis ampliado` (pregunta en negrita, caja azul con la respuesta clave y el gráfico de gasto promedio de recurrentes frente a no recurrentes).
- **Chat con Ollama**: "¿Cuántos pedidos hay en total?" → "Hay 99,441 pedidos en total…", con "Detalle técnico" colapsado que contiene `SELECT COUNT(order_id) FROM orders`, la tabla `99441` y *"🔎 Revisión automática del SQL (un segundo modelo revisó si la consulta tiene sentido para la pregunta; no comprueba que la cifra sea correcta): parece coherente…"*. La respuesta tardó ~90-100 s (llama3.1 lento en este estado del equipo, más la llamada del juez).
- **Chat con Ollama detenido** (se detuvo `ollama serve` a propósito): "No logro conectarme al motor de IA local (Ollama)…", con el "Detalle técnico" **abierto** y el error `GET http://localhost:11434/api/tags no respondió (modelo configurado: l…`. Se ve la línea divisoria entre el primer intercambio y el segundo. Después se volvió a lanzar Ollama.

## Decisiones propias
D-18 (navegación por selector en vez de pestañas; no aplicar índices). Ver DECISIONES.md.
