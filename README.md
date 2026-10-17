# Olist Analytics — Analítica de datos con LLM local

Proyecto de analítica de datos sobre el dataset público de Olist (e-commerce
brasileño), con un motor Text-to-SQL en español impulsado por un LLM local
(Ollama), pensado para correr en hardware de consumo (AMD Ryzen 5 7000-series,
16 GB RAM). Incluye una interfaz de chat (Streamlit) además del CLI.

Incluye: esquema relacional completo cargado desde los 9 CSV reales de Olist,
integración segura con Ollama (solo consultas `SELECT`), y una suite de
evaluación con respuestas de referencia para medir objetivamente la precisión
del modelo.

> El proyecto también conserva un dataset anterior de un gimnasio ficticio
> ("FitZone") como artefacto histórico en `legacy/gimnasio/` (modelos, seeder,
> ground truth de 20 preguntas y resultados viejos). Ya no es el target del
> pipeline LLM; ver `legacy/gimnasio/README.md`.

## Resultados (léelos con sus limitaciones)

**Etapa 3** (configuración congelada en `740066a`: autoconsistencia k=5, temperatura de evaluación 0.3, Ollama 0.40.3).
Oráculo v4: DESARROLLO 30 / PRUEBA_2 20 (nuevo, evaluado una sola vez).

| Modelo | DESARROLLO (de 30) | PRUEBA_2 (de 20) | Latencia por pregunta (DESARROLLO / PRUEBA_2) |
|---|---|---|---|
| llama3.1 8B | 17, 15, 14 (media 15.33) | 14, 13, 12 (media 13.0) | 38 s / 34 s |
| **qwen2.5-coder 7B** (nuevo por defecto, D-31) | 20, 16, 19 (media 18.33) | 11, 14, 13 (media 12.67) | 50 s / 39 s |

Los dos conjuntos **no son comparables** (las 10 necesidades difíciles del dashboard están solo en DESARROLLO), y el
intervalo de PRUEBA_2 calculado sobre sus 20 preguntas es ancho (43–82 % con llama3.1). Detalle y limitaciones en
[docs/INFORME_FINAL_3.md](docs/INFORME_FINAL_3.md); etapa 2 en [docs/RESUMEN_PARA_ENTREGA.md](docs/RESUMEN_PARA_ENTREGA.md).

**Etapa 4 — juez con retroalimentación iterativa** (Ollama 0.40.5). Resumen de una página en
[docs/INFORME_FINAL_4.md](docs/INFORME_FINAL_4.md); detalle en [docs/INFORME_JUEZ.md](docs/INFORME_JUEZ.md).
- **El juez** decide sin LLM, comparando el resultado con la referencia del dashboard, y nunca deja ver la referencia al modelo. **No rescató ningún caso** en 11 configuraciones.
- **Al chat pasaron dos mejoras que no usan la respuesta correcta.** Cumplieron D-23 en DESARROLLO (sin autoconsistencia, chat actual):

| Chat (qwen2.5-coder 7B, T=0.3 de evaluación) | DESARROLLO (de 30) |
|---|---|
| Antes | 15, 13, 14 (media 14.00) |
| Con reparación con esquema + texto con umbrales (por defecto) | 14, 15, 17 (media 15.33) |

## Modo evaluación con juez (demo)
En la barra lateral del chat (`streamlit run app.py`), activa **"🧪 Modo evaluación con juez"** (apagado por defecto).
- Las preguntas de ejemplo se reemplazan por los 6 casos del juez (`eval/casos_juez.json`).
- Puedes elegir de 1 a 5 intentos y activar o no la anti-repetición y la reparación con esquema.
- Cada intento se muestra en vivo con su SQL, su error o sus filas, y la pista que recibió el modelo. Al final aparece la respuesta de referencia del dashboard.
- Desde la terminal, lo mismo: `python -m eval.run_juez --max-iter 5 --reintento-temp --reparar-esquema --etiqueta demo`.

## Reproducir desde cero

### Versiones fijadas (las usadas para las cifras de arriba)

| Componente | Versión |
|---|---|
| Python | **3.14.3** (Windows 11; `py` launcher) |
| Paquetes de Python | `requirements.lock.txt` (versiones exactas) |
| Ollama | **0.40.3**. Se actualizó **solo** de 0.40.2 a 0.40.3 a mitad del A/B de la etapa 2; las corridas afectadas se repitieron en 0.40.3 y las de 0.40.2 están archivadas en `eval/baselines/etapa2/ollama_0402/`. Instalador: <https://github.com/ollama/ollama/releases/tag/v0.40.3>. Desactiva las actualizaciones automáticas para no cambiar de versión a mitad de una medición |
| Modelo (por defecto desde la etapa 3) | `qwen2.5-coder:7b-instruct-q4_K_M`, ID `dae161e27b0e` (4.7 GB) |
| Modelos comparados | `llama3.1:8b-instruct-q4_K_M` ID `46e0c10c039e` (4.9 GB; por defecto hasta la etapa 2) · `llama3.2:3b-instruct-q4_K_M` ID `a80c4f17acd5` (2.0 GB) |
| Datos | los 9 CSV de Olist, incluidos en el repo (`data/olist/`, 122 MB) |

### Comandos (Git Bash en Windows; en Linux/macOS cambia `py -3.14` por `python3.14` y `Scripts` por `bin`)

```bash
# 0) Código. El venv va FUERA de la carpeta del repo: si el repo está en OneDrive, la sincronización rompe el venv
git clone https://github.com/Adely201810/AnalizadorIA.git && cd AnalizadorIA
py -3.14 -m venv ~/.venvs/analizadoria && source ~/.venvs/analizadoria/Scripts/activate
export PYTHONUTF8=1                                # Windows: sin esto, run_eval falla al redirigir la salida (UnicodeEncodeError, cp1252)
python --version                                   # Python 3.14.3
python -m pip install -r requirements.lock.txt     # versiones exactas

# 1) Base de datos: esquema + 9 CSV + 10 vistas -> db/olist.db (no se versiona; ~1 min)
python seeder/load_olist_csv.py

# 2) Oráculo: reconstruirlo debe dar EXACTAMENTE los archivos versionados, y pandas debe coincidir.
#    Se parte del oráculo v2 (commit cb20411) y se convierte en v3 (etapa 2) y luego en v4 (etapa 3: DESARROLLO 30 + PRUEBA_2 20)
git show cb20411:eval/ground_truth_olist.json > eval/ground_truth_olist.json
python -m eval.construir_oraculo_v3
python -m eval.construir_oraculo_v4
git diff --exit-code eval/ground_truth_olist.json eval/split_oraculo.json && echo "oráculo idéntico"
python -m dashboard.verify_pandas                  # todas las líneas deben decir [OK]

# 3) Pruebas automáticas (no necesitan Ollama)
python -m unittest discover -s tests -t .          # Ran 110 tests ... OK

# 4) Ollama 0.40.3 y el modelo (instálalo antes desde el enlace de la tabla)
ollama --version                                   # ollama version is 0.40.3
ollama pull qwen2.5-coder:7b-instruct-q4_K_M       # ~4.7 GB (modelo por defecto)
ollama pull llama3.1:8b-instruct-q4_K_M            # ~4.9 GB (opcional: comparación / revertir D-31)
ollama list                                        # IDs: dae161e27b0e (qwen2.5-coder), 46e0c10c039e (llama3.1)

# 5) Evaluación en DESARROLLO con la configuración final de la etapa 3 (autoconsistencia k=5; temperatura 0.3 por defecto en la evaluación; ~25 min por repetición)
for k in 1 2 3; do TEXT2SQL_AUTOCONSISTENCIA=5 python eval/run_eval.py --sin-plantillas --conjunto desarrollo --output eval/eval_results_desarrollo_r$k.json; done

# 6) Interfaz: chat en http://localhost:8501 y dashboard en la página "Dashboard"
streamlit run app.py
```

Notas:
- **PRUEBA_2 no se vuelve a evaluar para ajustar nada** (ya se usó una vez; ver docs/INFORME_FINAL_3.md). El PRUEBA de la etapa 2 ya forma parte de DESARROLLO.
- **Variación esperable:** en la etapa 2, la misma configuración dio en DESARROLLO (20 preguntas) 8, 9, 8; luego 10, 7, 9; y 6, 8, 7 desde un clon limpio. Una repetición sola no basta para comparar.
- **Variables del pipeline (valor por defecto entre paréntesis).** Ver también [docs/ENTORNO.md](docs/ENTORNO.md).

| Variable | Por defecto | Qué hace | Decisión |
|---|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5-coder:7b-instruct-q4_K_M` | Modelo del chat y de la evaluación | D-31 |
| `OLLAMA_HOST` / `OLLAMA_NUM_CTX` | `http://localhost:11434` / 8192 | Servidor y contexto | — |
| `TEXT2SQL_VISTA_VALIDOS` | **1** | Vista `vw_pedidos_validos` en el prompt | D-25 |
| `TEXT2SQL_REPARAR_ESQUEMA` | **1** | El reintento recibe columnas reales y ruta por tablas base | D-40 |
| `TEXT2SQL_TEXTO_UMBRALES` | **1** | "Texto confiable" acepta los números de la pregunta | D-40 |
| `TEXT2SQL_N_INTENTOS` | 2 | Intentos totales por pregunta | Fase 6 |
| `TEXT2SQL_CLASIFICADOR` | 0 | Partir preguntas en sub-consultas | D-25 |
| `TEXT2SQL_AUTOCONSISTENCIA` | 1 (apagada) | k SQL por pregunta con votación; 5 en la configuración evaluada de la etapa 3 | D-30 |
| `TEXT2SQL_ESQUEMA` | `compacto` | `completo` = esquema largo (no ayudó) | D-33 |
| `TEXT2SQL_JUEZ_CHAT` | 1 | Revisión de sensatez del SQL en el chat (no verifica cifras) | Fase 10 |

  Los experimentos revertidos siguen apagados detrás de su flag:
  - etapa 2: `TEXT2SQL_REGLA_DENOMINADOR`, `TEXT2SQL_VISTAS_DOC`, `TEXT2SQL_VISTAS_OCULTAS`, `TEXT2SQL_REGLA_MULTIPLICIDAD`;
  - etapa 3: `TEXT2SQL_GLOSARIO`, `TEXT2SQL_ESQUEMA_POR_PREGUNTA`, `TEXT2SQL_DESC_COLUMNAS`, `TEXT2SQL_VISTAS_NEGOCIO`, `TEXT2SQL_FEWSHOT_DINAMICO`, `TEXT2SQL_PLAN`.

  Las opciones del juez (`--reintento-temp`, `--reparar-esquema`, `--modo-edicion`, `--pistas-v2`) son solo de `eval/run_juez.py`.
- Detalles de instalación y despliegue: [docs/DEPLOY.md](docs/DEPLOY.md). Diccionario de datos: [docs/esquema_olist.md](docs/esquema_olist.md).

## Estructura

| Carpeta | Contenido |
|---|---|
| `db/` | Esquema Olist (SQLAlchemy ORM), conexión de solo lectura, vistas analíticas |
| `seeder/` | `load_olist_csv.py` (loader de los CSV reales de Olist) |
| `llm/` | Cliente de Ollama, contexto de esquema (con few-shot), guardas de seguridad SQL, pipeline Text-to-SQL, CLI |
| `eval/` | Oráculo v4 de 50 preguntas (`ground_truth_olist.json`, DESARROLLO 30 / PRUEBA_2 20), árbitro determinista (`comparador.py`), runner de evaluación, A/B con repeticiones (`ab.py`, `ab_acumulativo_e3.py`), juez iterativo (`casos_juez.json`, `run_juez.py`, `tabla_juez.py`; lógica en `llm/juez.py`) y corridas guardadas (`eval/baselines/`) |
| `docs/` | Diccionario de datos de Olist, guía de despliegue y documentación por fase (`PROGRESO.md`, `DECISIONES.md`, `FASE_XX.md`) |
| `tests/` | Pruebas automáticas (`python -m unittest discover -s tests -t .`) |
| `legacy/gimnasio/` | Dataset histórico del gimnasio ficticio (no se usa en el pipeline) |
| `app.py` | Interfaz de chat (Streamlit) sobre el mismo pipeline que usa `llm/cli.py` |

## Seguridad del pipeline Text-to-SQL

- Solo se ejecutan sentencias `SELECT`/`WITH` de una sola sentencia
  (`llm/sql_guard.py` rechaza `INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/ATTACH/...`
  y cualquier intento de inyectar una segunda sentencia vía `;`).
- La ejecución contra SQLite se hace en una conexión abierta explícitamente en
  **modo solo-lectura** (`file:...?mode=ro`) como defensa adicional.
- Si el SQL generado falla (sintaxis inválida, columna inexistente, más de
  60 s de ejecución) o no devuelve filas, el pipeline reintenta reenviando el
  error al modelo para que se autocorrija. `n_intentos` es el número **total**
  de intentos por pregunta (por defecto 2, es decir, un reintento; se cambia
  con la variable `TEXT2SQL_N_INTENTOS` o con `answer_question(n_intentos=N)`).
  Un rechazo de seguridad nunca se reintenta. En la evaluación,
  `eval/run_eval.py --intentos N --cadena` verifica cada intento contra la
  referencia y corta en el primer acierto (ver docs/FASE_06_09_07_08.md).
