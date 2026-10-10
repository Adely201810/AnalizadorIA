# Diagnóstico del proyecto AnalizadorIA (Text-to-SQL con LLM local)

Fecha: 2026-10-10 · Commit analizado: `4cd4e36 Primer commit` · Alcance: solo lectura (este archivo es lo único creado).

> Todas las afirmaciones están basadas en lectura de código. **Ninguna prueba pudo ejecutarse con éxito** en este equipo
> (ver §3), así que nada de lo descrito como "funciona" está verificado en ejecución.

---

## 1. Ficha técnica

| Aspecto | Hallazgo | Evidencia |
|---|---|---|
| Lenguaje | Python. El código usa sintaxis ≥3.10 (`str \| None`, `from __future__ import annotations`). No hay versión fijada (no hay `pyproject.toml`, `.python-version` ni `runtime.txt`). | `requirements.txt` (solo rangos de librerías) |
| Python instalado aquí | **Python 3.14.3** (único intérprete; sin `.venv`) | salida de `python --version` / `py -0` |
| Dependencias | SQLAlchemy 2.x, Faker, requests, pandas, streamlit, plotly, reportlab, matplotlib. **Ninguna instalada** en este equipo. | `requirements.txt`; §3 |
| Base de datos | SQLite en `db/olist.db` (configurable con `OLIST_DATABASE_URL`). **El archivo no existe** en el repo (`*.db` está en `.gitignore`); se construye con `db/olist_init_db.py` + `seeder/load_olist_csv.py` a partir de los 9 CSV de `data/olist/` (~128 MB, sí versionados). | `db/olist_database.py:20-23`, `.gitignore`, `README.md` |
| BD histórica | `db/gimnasio.db` (dataset "FitZone" sintético). No es el objetivo activo. | `README.md`, `db/database.py` |
| Acceso a datos del LLM | Conexión SQLite `file:...?mode=ro` (solo lectura) + validador de solo SELECT. | `llm/text_to_sql.py:250-261`, `llm/sql_guard.py:49` |
| Dashboard | **Streamlit** multipágina: `app.py` (chat) + `pages/1_Dashboard.py` (dashboard de verificación con 10 pestañas, gráficos Plotly, PDF con reportlab). | `app.py:26`, `pages/1_Dashboard.py:30` |
| Conexión al modelo | **Ollama** vía API HTTP REST (`POST /api/generate`, `stream: false`) usando la librería **`requests`**. No usa el SDK `ollama` ni LangChain. | `llm/ollama_client.py:18`, `:80` |
| Modelo actual | `llama3.1:8b-instruct-q4_K_M` por defecto (override con `OLLAMA_MODEL`). `temperature=0.1`, `num_ctx=8192`, timeout 300 s. | `llm/ollama_client.py:24`, `:31`, `:34`, `:47` |
| Ollama en este equipo | **No instalado** (`ollama: command not found`) y nada escuchando en `localhost:11434`. | §3 |

### Flujo del pipeline (`llm/text_to_sql.py:617` `answer_question`)
1. Plantillas por reglas de palabras clave (Pareto, series mensuales) → SQL fijo sin LLM (`llm/sql_templates.py:261`).
2. Clasificador LLM: ¿una consulta o varias sub-preguntas? (`text_to_sql.py:356`).
3. Generación de SQL con esquema + notas + few-shot en el prompt de sistema (`text_to_sql.py:291`).
4. Validación de seguridad (sin reintento) y de calidad: placeholders, tablas/columnas inexistentes, joins entre dominios distintos (`text_to_sql.py:446-462`).
5. Ejecución en solo lectura; reintento con el error; plantilla de respaldo sobre vistas si sigue fallando (`text_to_sql.py:546-557`).
6. Síntesis en lenguaje natural + control determinista de que cada cifra citada exista en el resultado (`text_to_sql.py:205-216`).

---

## 2. Evaluación por fase

### Fase 1 — Esquema completo + reglas de negocio + ejemplos SQL en el prompt → **COMPLETA (con matices)**
- El esquema se genera por introspección de los modelos SQLAlchemy y se inyecta en el system prompt:
  `llm/schema_context.py:215` `build_schema_context()` → `llm/text_to_sql.py:298` (`SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=...)`).
- Tablas y columnas con PK, FK y nulabilidad: `schema_context.py:141-154` `_column_line`.
- Vistas analíticas documentadas a mano: `schema_context.py:30-38`.
- Columnas de unión explícitas (qué tabla tiene cada llave): `schema_context.py:184-206`.
- Valores reales de columnas tipo-enum leídos de la BD (`order_status`, `payment_type`): `schema_context.py:103-138`.
- Reglas de negocio (18 notas: cliente = `customer_unique_id`, ingresos excluyen canceled/unavailable, flete = SUM/SUM, rango 2016-2018…): `schema_context.py:40-60`.
- 12 ejemplos pregunta→SQL correcto: `schema_context.py:62-100`.

Matices:
- **Tipos incompletos**: `_column_line` omite deliberadamente el tipo cuando es `INTEGER` o `BOOLEAN` (`schema_context.py:151-153`), y las vistas se listan **sin tipos** (`:32-37`).
- Los valores tipo-enum solo se exponen para columnas cuyo `comment` contiene `|` (2 columnas en `db/olist_models.py:144`, `:195`).
- **Fuga de oráculo**: varios ejemplos few-shot coinciden casi literalmente con preguntas del ground truth (ej. `schema_context.py:71-72` vs `q2_categoria_mas_ingresos`; `:80-81` vs `q5_retraso_baja_calificacion`). Esto infla la precisión medida (ver Riesgos).

### Fase 2 — Distinguir automáticamente fallo de ejecución vs fallo semántico → **PARCIAL**
- En tiempo de ejecución sí se distinguen tipos de fallo: seguridad (`SQLValidationError`, `text_to_sql.py:446-451`), calidad (`SQLQualityError`), error del motor (`sqlite3.Error`, `:464-473`) y "0 filas" (`:475-491`).
- **Pero el evaluador no clasifica el fallo**: `eval/run_eval.py:81-106` `calificar()` devuelve solo `sql_correcto: True/False` + un texto libre. Además, cuando el SQL falla tras el reintento, el pipeline **no** pone `resultado.error`; devuelve el mensaje fijo `MENSAJE_PROBLEMA_TRAS_REINTENTO` (`text_to_sql.py:470-473`, `:658-659`). Resultado: en `run_eval.py:84` ese caso **no** entra por "Pipeline falló" y se califica como `esperado≈X, hallado=None`, **indistinguible de un fallo semántico**.
- `run_eval.py:146-157` no guarda `detalle_error`, `origen` (llm / plantilla / fallback) ni el tipo de fallo.

### Fase 3 — Oráculo de referencia con comparación automática → **COMPLETA (con debilidades)**
- 10 preguntas con SQL de referencia y valor esperado: `eval/ground_truth_olist.json` (q1…q10).
- Recalculo del oráculo contra la BD: `eval/compute_ground_truth.py:50` (`conn.execute(text(item["sql_referencia"]))`).
- Comparación automática con tolerancias abs/% por pregunta: `eval/run_eval.py:57-69` `_verifica_numero`, `:81-106` `calificar`.

Debilidades:
- **Comparación laxa**: se busca el número esperado en la respuesta en lenguaje natural **y en cualquier celda** del resultado (`run_eval.py:52-54`). Un SQL que devuelve muchas filas (p. ej. todas las categorías) puede "acertar" aunque no responda la pregunta. En q4 basta con que aparezca uno de 5 nombres de categoría (`ground_truth_olist.json`, q4).
- No se compara contra el **resultado completo** del SQL de referencia (filas/columnas), solo contra un escalar o una subcadena.
- Los valores esperados **no pudieron verificarse** en este diagnóstico (no existe `db/olist.db`).
- No hay ninguna corrida de evaluación Olist guardada: los únicos resultados versionados (`eval/eval_rerun_failed_20260911_135003.json`, `eval/resumen_correcciones.json`) son del **dataset de gimnasio**, no de Olist (`eval_results_*.json` está en `.gitignore`).

### Fase 4 — Comparación de varios modelos con el oráculo (precisión, tiempo, RAM/VRAM) → **FALTA**
- Existe la *capacidad* de cambiar de modelo: `run_eval.py:111` (`--model`) y la variable `OLLAMA_MODEL`.
- `docs/DEPLOY.md:41-43` menciona alternativas (mistral 7B, qwen2.5 7B/14B), pero sin resultados.
- **No se mide tiempo** (no hay `time.perf_counter`/cronometraje en `run_eval.py`) ni **RAM/VRAM** (no se consulta `/api/ps` de Ollama ni `psutil`). No hay ninguna tabla comparativa ni corrida documentada.

### Fase 5 — ~10 necesidades de negocio, una sola consulta cada una, respuesta de referencia verificada → **PARCIAL**
- Hay 10 "necesidades del dueño" definidas como funciones deterministas: `dashboard/queries.py` `q01` (`:169`) … `q10` (`:1220`), mostradas en `pages/1_Dashboard.py:267-278`.
- Verificación cruzada independiente (pandas sobre los CSV vs SQL) para **algunas** cifras de q01, q03 y q08: `dashboard/verify_pandas.py:128-137`.
- Por qué es parcial:
  - **No son "una sola consulta"**: varias ejecutan múltiples SQL + post-proceso en pandas (conteo de `_run(`: q01=4, q03=2, q05=2, q06=3, q09=4). Varias preguntas son compuestas (ej. q06 "método, cuotas y qué categorías…").
  - **Estas 10 necesidades no son las mismas 10 del oráculo** (`ground_truth_olist.json`); el chatbot no se evalúa contra ellas.
  - Solo 3 de 10 tienen una segunda verificación independiente.
  - No sé si estas 10 son *tus* necesidades reales de negocio (ver preguntas abiertas).

### Fase 6 — N iteraciones configurables por pregunta + juez-LLM → **PARCIAL (iteraciones nominales, sin juez)**
- `max_retries` es configurable (`text_to_sql.py:617`, `run_eval.py:113` `--max-retries`), **pero la bandera `ya_reintento_por_problema` (`text_to_sql.py:416`, usada en `:426`, `:437`, `:466`, `:476`) limita a UN solo reintento sin importar el valor**: con `max_retries=2` hay como máximo 2 intentos, y subirlo no cambia nada. El `README.md` dice "reintenta hasta 2 veces", lo cual no coincide con el código.
- Las iteraciones solo se disparan por fallo de ejecución/calidad/0 filas, no por respuesta incorrecta.
- **No existe juez-LLM** en ningún archivo (búsqueda de `juez|judge` sin resultados en `*.py`).

### Fase 7 — Feedback específico entre intentos, sin revelar la respuesta correcta → **PARCIAL**
- Sí hay feedback con el error real: `text_to_sql.py:300-305` reenvía el SQL previo y el error (texto de `sqlite3.Error` o diagnóstico de `SQLQualityError`); para 0 filas, un diagnóstico fijo (`:478-484`).
- No se revela la respuesta correcta (el pipeline no tiene acceso al oráculo).
- Falta: no hay feedback **semántico** (un SQL que corre pero responde otra cosa nunca recibe retroalimentación), y solo hay 1 reintento (Fase 6).

### Fase 8 — Veredicto por comparación determinista; el juez-LLM solo explica → **PARCIAL**
- El veredicto del evaluador ya es determinista (`run_eval.py:57-106`). El chequeo de cifras de la síntesis también es determinista (`text_to_sql.py:205-216`).
- Falta el juez-LLM explicativo (no existe), y la comparación determinista es laxa (Fase 3).

### Fase 9 — Cortar la cadena de intentos en el primer acierto → **PARCIAL**
- El bucle corta en el primer SQL que **ejecuta y devuelve filas** (`text_to_sql.py:493-496`), pero eso es "primer SQL ejecutable", no "primer acierto" contra la referencia. No existe una cadena de intentos evaluada contra el oráculo.

### Fase 10 — Chat libre: juez-LLM sobre si el SQL tiene sentido + bitácora persistente de errores de esquema → **FALTA**
- No hay juez-LLM.
- Solo hay `logging` (`text_to_sql.py:45`, `:219-223`, `:456`, `:549`) y **no hay configuración de handler a archivo** (no existe `basicConfig`/`FileHandler` en el repo), así que los avisos no se persisten. Los errores de columnas/tablas inexistentes detectados por `sql_guard.py` (`check_columnas_existentes`, `:384`) no se registran en ninguna bitácora.

### Fase 11 — Legibilidad del dashboard → **PARCIAL (no verificada visualmente)**
Lo que ya existe:
- Chat: separación pregunta/respuesta con `st.chat_message` (`app.py:123`, `:132`, `:135`); detalle técnico (SQL + tabla) aislado en el expander "Ver detalle" (`app.py:95`); título + caption (`app.py:72-73`).
- Dashboard: título (`pages/1_Dashboard.py:217`), métricas resumen (`:236-243`), respuesta clave destacada en caja coloreada (`:135-151`), "Cómo se calculó" en expander (`:189-197`), pestañas por necesidad (`:616-630`).

Problemas observados en código:
- Si hay error de infraestructura y no hay SQL, `_render_detalle` sale antes (`app.py:93-94`) y **el `error_tecnico` nunca se muestra** (`:104-105`).
- `detalle_error` (por qué se descartó el SQL del LLM) no se muestra en la UI.
- Jerarquía de títulos irregular: `st.subheader` en el resumen (`:282`) pero `#####` (h5) en las pestañas (`:303`, `:339`, …).
- No pude abrir la app (faltan dependencias y BD), así que no hay verificación visual.

---

## 3. Ejecución de pruebas

Se ejecutaron con `PYTHONDONTWRITEBYTECODE=1` para no escribir `__pycache__` en el proyecto. Salida exacta:

```
===== $ python eval/run_eval.py
Traceback (most recent call last):
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\eval\run_eval.py", line 35, in <module>
    from llm.text_to_sql import Text2SQLResult, _respuesta_respaldada_por_datos, answer_question
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\llm\text_to_sql.py", line 47, in <module>
    from db.olist_database import DATABASE_URL
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\db\olist_database.py", line 16, in <module>
    from sqlalchemy import create_engine
ModuleNotFoundError: No module named 'sqlalchemy'
[exit code: 1]
===== $ python eval/compute_ground_truth.py
Traceback (most recent call last):
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\eval\compute_ground_truth.py", line 22, in <module>
    from sqlalchemy import text
ModuleNotFoundError: No module named 'sqlalchemy'
[exit code: 1]
===== $ python -m dashboard.verify_pandas
Traceback (most recent call last):
  File "<frozen runpy>", line 189, in _run_module_as_main
  File "<frozen runpy>", line 112, in _get_module_details
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\dashboard\__init__.py", line 10, in <module>
    from .queries import q01, q02, q03, q04, q05, q06, q07, q08, q09, q10
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\dashboard\queries.py", line 36, in <module>
    import pandas as pd
ModuleNotFoundError: No module named 'pandas'
[exit code: 1]
===== $ python llm/schema_context.py
Traceback (most recent call last):
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\llm\schema_context.py", line 13, in <module>
    from sqlalchemy import text
ModuleNotFoundError: No module named 'sqlalchemy'
[exit code: 1]
===== $ python -m llm.cli ¿Cuántos pedidos hay en total?
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\llm\cli.py", line 17, in <module>
    from llm.text_to_sql import answer_question
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\llm\text_to_sql.py", line 47, in <module>
    from db.olist_database import DATABASE_URL
  File "C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\db\olist_database.py", line 16, in <module>
    from sqlalchemy import create_engine
ModuleNotFoundError: No module named 'sqlalchemy'
[exit code: 1]
===== $ ollama --version
/usr/bin/bash: line 1: ollama: command not found
[exit code: 127]
===== $ curl http://localhost:11434/api/tags
curl: (7) Failed to connect to localhost port 11434 after 2260 ms: Could not connect to server
[exit code: 7]
===== $ ls db/*.db
ls: cannot access 'db/*.db': No such file or directory
[exit code: 2]
```

**Conclusión:** ninguna prueba se pudo ejecutar. Hay tres bloqueos independientes:
1. Las dependencias de Python no están instaladas (no hay `.venv`; Python global 3.14.3 sin paquetes).
2. `db/olist.db` no existe; hay que construirla desde los CSV.
3. Ollama no está instalado y no hay ningún modelo descargado (`llama3.1:8b-instruct-q4_K_M` pesa ~4.9 GB según `docs/DEPLOY.md:11`).

Aun con (1) y (2) resueltos, `compute_ground_truth.py`, `verify_pandas.py` y el dashboard se podrían ejecutar **sin** Ollama; `run_eval.py`, `llm.cli` y el chat necesitan (3).

No tengo resultados de precisión del modelo sobre Olist. Las cifras de `eval/resumen_correcciones.json` (15/20, 75 %) son del dataset de **gimnasio**, de una corrida anterior, y no las reproduje.

---

## 4. Tabla resumen

| Fase | Descripción corta | Estado | Evidencia principal |
|---|---|---|---|
| 1 | Esquema + reglas + few-shot en el prompt | **COMPLETA** (matices: tipos INTEGER/BOOLEAN y de vistas omitidos; fuga de oráculo en few-shot) | `llm/schema_context.py:215`, `:40-100`; `llm/text_to_sql.py:298` |
| 2 | Distinguir fallo de ejecución vs semántico | **PARCIAL** | `text_to_sql.py:464-491` sí; `eval/run_eval.py:81-106` no clasifica |
| 3 | Oráculo + comparación automática | **COMPLETA** (comparación laxa; valores no re-verificados) | `eval/ground_truth_olist.json`, `run_eval.py:52-106` |
| 4 | Benchmark multi-modelo (precisión, tiempo, RAM/VRAM) | **FALTA** | solo `run_eval.py:111` `--model` |
| 5 | 10 necesidades de negocio, 1 consulta, referencia verificada | **PARCIAL** | `dashboard/queries.py` q01-q10; `verify_pandas.py` (3/10) |
| 6 | N iteraciones configurables + juez-LLM | **PARCIAL** (máx. 1 reintento real; sin juez) | `text_to_sql.py:416` |
| 7 | Feedback específico entre intentos sin filtrar respuesta | **PARCIAL** | `text_to_sql.py:300-305`, `:478-484` |
| 8 | Veredicto determinista; juez solo explica | **PARCIAL** | `run_eval.py:57-106`; sin juez |
| 9 | Cortar en el primer acierto | **PARCIAL** | `text_to_sql.py:493-496` (corta al primer SQL ejecutable, no al primer acierto) |
| 10 | Juez de sensatez en chat libre + bitácora persistente | **FALTA** | solo `logging` sin handler persistente |
| 11 | Legibilidad del dashboard | **PARCIAL** (no verificada visualmente) | `app.py:93-105`, `pages/1_Dashboard.py:135-197` |

---

## 5. Riesgos y deuda técnica

1. **Entorno no reproducible**: no hay versión de Python fijada ni lockfile; el único Python aquí es 3.14.3 y no sé si todas las dependencias (streamlit, pandas, reportlab, matplotlib) tienen wheels compatibles. `docs/DEPLOY.md:7` indica que solo se probó en Linux.
2. **Creación accidental de una BD vacía**: si se ejecuta el código sin `db/olist.db`, `create_engine("sqlite:///…")` + `engine.connect()` (`llm/schema_context.py:113`, `:169`) **crea un archivo `olist.db` vacío** y los errores posteriores serían confusos ("no such table"). Conviene comprobar que el archivo existe antes de conectar.
3. **Precisión probablemente inflada**:
   - Hay ejemplos few-shot casi idénticos a preguntas del oráculo (Fase 1).
   - La comparación busca el valor en cualquier celda (Fase 3).
   - Las plantillas y el fallback sobre vistas (`text_to_sql.py:546-557`) pueden responder en lugar del LLM y el evaluador no registra el `origen` (`run_eval.py:146-157`), así que no se sabe si el acierto fue del modelo.
4. **Fallos de ejecución contados como semánticos** en la evaluación (Fase 2): se pierde el diagnóstico de qué arreglar.
5. **`max_retries` engañoso**: el parámetro no controla lo que dice (`text_to_sql.py:416`), y el README lo describe mal.
6. **Sin resultados de evaluación Olist versionados** (`eval_results_*.json` en `.gitignore`): no hay línea base histórica para comparar mejoras.
7. **Restos del dataset de gimnasio** mezclados con Olist (`db/models.py`, `seeder/seed.py`, `eval/ground_truth.json`, resultados de eval de gimnasio): confunden al leer las métricas.
8. **Dos fuentes de "verdad" desconectadas**: las 10 preguntas del oráculo (`ground_truth_olist.json`) y las 10 necesidades del dashboard (`dashboard/queries.py`) son conjuntos distintos.
9. **Detalle técnico oculto en la UI** cuando falla Ollama (`app.py:93-94`).
10. **HTML sin escapar**: `bloque_respuesta_clave` inserta texto con `unsafe_allow_html=True` (`pages/1_Dashboard.py:135-151`). Hoy el texto es determinista (no viene del LLM), así que el riesgo es bajo, pero hay que tenerlo en cuenta si algún día se muestra ahí texto del modelo.

---

## 6. Orden recomendado para lo que falta

0. **Prerrequisito (antes de cualquier fase):** crear el entorno virtual, instalar dependencias, construir `db/olist.db` desde los CSV y ejecutar `compute_ground_truth.py` y `verify_pandas.py` para confirmar el oráculo **sin LLM**. Luego instalar Ollama y descargar el modelo (requiere tu confirmación por tamaño).
1. **Fase 1 (afinar)**: agregar los tipos que faltan y quitar o separar los ejemplos few-shot que coinciden con el oráculo, para medir sin fuga.
2. **Fase 3 (endurecer)**: comparar contra el resultado del SQL de referencia, no "cualquier celda"; registrar `origen` y desactivar plantillas/fallback durante la evaluación del modelo.
3. **Fase 2**: clasificar cada fallo en el evaluador (`ejecucion` / `semantico` / `seguridad` / `infra` / `ok`).
4. **Fase 5**: acordar contigo las 10 necesidades reales, reducir cada una a una sola consulta y unificarlas con el oráculo.
5. **Fase 4**: benchmark multi-modelo (precisión, latencia, RAM/VRAM vía `ollama ps`) sobre el oráculo unificado; aquí ya se tiene una base fiable.
6. **Fases 6 → 9 → 7 → 8** (bucle de evaluación): N iteraciones reales y configurables, corte en el primer acierto, feedback sin filtrar el valor y juez-LLM solo explicativo.
7. **Fase 10**: juez de sensatez en chat libre y bitácora persistente de errores de esquema.
8. **Fase 11**: legibilidad, una vez que la UI tenga qué mostrar (veredicto, origen, explicación del juez).
