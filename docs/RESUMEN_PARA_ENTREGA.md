# AnalizadorIA — Resumen para entrega

## Objetivo
Responder en español preguntas de negocio sobre el marketplace Olist (99,441 pedidos, 2016–2018) con un LLM **local** (Ollama, GPU de consumo), y medir de forma honesta cuántas responde bien.

## Arquitectura
- **Datos:** 9 CSV públicos de Olist → SQLite (`db/olist.db`) + 7 vistas analíticas (`db/olist_views.sql`). Siempre se consulta en **solo lectura**.
- **Chat Text-to-SQL** (`llm/`):
  1. Se arma el prompt con el esquema real y ejemplos de entrenamiento.
  2. El LLM genera SQL.
  3. La guarda de seguridad (`sql_guard.py`) admite solo un `SELECT` o un `WITH`.
  4. Se validan las tablas y columnas, y se ejecuta con un límite de 60 s.
  5. Si falla, se reintenta (2 intentos en total).
  6. El LLM redacta la respuesta, que solo se muestra si sus cifras están respaldadas por las filas devueltas.
  - Interfaz: Streamlit (`app.py`).
- **Dashboard de verificación** (`pages/1_Dashboard.py`, `dashboard/`): las 10 necesidades del dueño, resueltas con SQL escrito a mano sobre las tablas base y verificadas con pandas desde los CSV. **Es la fuente fiable**; el chat no lo es (ver Limitaciones).
- **Modelo:** llama3.1 8B Q4_K_M sobre Ollama **0.40.3**.

## Metodología de evaluación
- **Oráculo** (`eval/ground_truth_olist.json`, v3): 30 preguntas. Cada una tiene un SQL de referencia, verificado contra un recálculo independiente en pandas (30/30), y su resultado esperado.
- **Árbitro determinista** (`eval/comparador.py`): compara el resultado del SQL del modelo con la referencia, sin LLM y con tolerancias por tipo:
  - conteos exactos;
  - dinero ±0.01 o ±0.1 %;
  - porcentajes ±0.006.
  - Un "juez LLM" se probó y se descartó como veredicto (daba falsos aciertos).
- **Split**: DESARROLLO 20 / PRUEBA 10, por sorteo con semilla fija. Las 10 necesidades van a DESARROLLO por decisión explícita.
  - Hay pruebas automáticas que impiden que el texto, el SQL o los resultados de PRUEBA se filtren al prompt.
  - Todas las mejoras se eligieron solo con DESARROLLO.
  - PRUEBA se evaluó **una sola vez**, con la configuración congelada (commit `02f3dba`).
- **A/B**: 3 repeticiones por configuración. Una mejora se conserva solo si la media sube ≥1 acierto y el mínimo nuevo es ≥ la media anterior.

## Evolución de las cifras

> ⚠ **No comparables entre filas con distinto oráculo.** El oráculo cambió de v1 (10 preguntas genéricas) a v2 (10 necesidades) y luego a v3 (30 preguntas, split). Además, DESARROLLO y PRUEBA tampoco son comparables entre sí (ver Limitaciones).

| Momento | Oráculo | Resultado |
|---|---|---|
| Línea base inicial, evaluador original | v1 (10) | 6/10, con 3 falsos positivos |
| Misma corrida con el árbitro determinista | v1 (10) | 3/10 |
| Sin plantillas, con árbitro | v1 (10) | 2/10 |
| Las 10 necesidades (llama3.1 / qwen2.5-coder / llama3.2) | v2 (10) | 0/10 · 1/10 · 0/10 |
| Inicio de la etapa 2 | v3 DESARROLLO (20) | 3, 3, 3 |
| + sin clasificador de preguntas | v3 DESARROLLO | 5, 5, 5 |
| + vista de pedidos válidos | v3 DESARROLLO | 8, 9, 8 |
| **Final** (`02f3dba`) | v3 DESARROLLO (20) | **10, 7, 9** (media 8.67; 43 %) |
| **Final, evaluación única** | v3 PRUEBA (10) | **8, 8, 8** (80 %; Wilson sobre 10 preguntas: 49–94 %) |

## Qué funcionó
- **Un árbitro determinista en vez de "parece correcto":** destapó que la cifra inicial (6/10) estaba inflada.
- **Quitar el clasificador** que partía preguntas simples en sub-consultas: 3 → 5 de media.
- **Vista `vw_pedidos_validos`:** el modelo parte de pedidos ya filtrados. 5 → 8.33 de media.
- **Dashboard:** q01 bajó de 31 s a 10 s con resultados idénticos (verificado con pandas); el chat distingue ya una negativa del modelo de un rechazo de seguridad.
- **Bitácora de errores:** evita, con el modelo real, que se repita el error "SELECT sin FROM" (12/12 → 0/6 intentos). No convierte esas respuestas en correctas.

## Qué se probó y se revirtió
Todas estas mejoras añadían reglas o texto al prompt y bajaron la media frente a 8.33:

| Mejora | Media |
|---|---|
| Regla y ejemplos de denominador para porcentajes | 5 |
| Documentar el uso y las columnas de cada vista | 5 |
| Ocultar las vistas agregadas que confundían | 7 |
| Regla contra JOINs que multiplican filas | 4.67 |

Cambiar de modelo no ayudó: qwen2.5-coder empató (8.33) y llama3.2 3B bajó (2.67).

## Limitaciones
1. **DESARROLLO y PRUEBA no son comparables:** las 10 necesidades difíciles están todas en DESARROLLO. El 80 % de PRUEBA refleja preguntas más fáciles, no un mejor rendimiento en datos nuevos.
2. **La muestra es chica y las repeticiones no son independientes.** PRUEBA dio idéntico resultado en las 3 repeticiones, así que la muestra efectiva es de 10 preguntas: el intervalo es 49–94 %, no el 63–91 % que sale de contar 30 respuestas.
3. **PRUEBA ya fue vista** (se sabe que fallan los porcentajes x06 y x20). Para medir mejoras futuras hace falta un conjunto de prueba nuevo.
4. **El objetivo original no se alcanzó con el chat.** Las 10 necesidades del dashboard están en 9/30 respuestas; solo 2 de 10 aciertan siempre. Para esas preguntas hay que usar el dashboard.
5. **Los porcentajes con denominador son el punto débil:** 3/9 en PRUEBA.
6. **Reproducibilidad del modelo:** Ollama se actualiza solo. Pasó de 0.40.2 a 0.40.3 durante el A/B, y las corridas afectadas se repitieron. Las cifras dependen de la versión de Ollama y del modelo (IDs en el README).

Documentación completa: [INFORME_FINAL_2.md](INFORME_FINAL_2.md) (etapa 2), [INFORME_FINAL.md](INFORME_FINAL.md) (etapa 1), [DECISIONES.md](DECISIONES.md), [PROGRESO.md](PROGRESO.md).
