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

Configuración final congelada en el commit `02f3dba` (llama3.1 8B, Ollama 0.40.3):
**DESARROLLO 10, 7, 9 de 20** (media 8.67) y **PRUEBA 8, 8, 8 de 10**, evaluada una sola vez.
Los dos conjuntos **no son comparables**, y las 10 necesidades del dashboard siguen en 9/30.
Resumen honesto en [docs/RESUMEN_PARA_ENTREGA.md](docs/RESUMEN_PARA_ENTREGA.md); detalle en
[docs/INFORME_FINAL_2.md](docs/INFORME_FINAL_2.md).

## Reproducir desde cero

### Versiones fijadas (las usadas para las cifras de arriba)

| Componente | Versión |
|---|---|
| Python | **3.14.3** (Windows 11; `py` launcher) |
| Paquetes de Python | `requirements.lock.txt` (versiones exactas) |
| Ollama | **0.40.3**. Se actualizó **solo** de 0.40.2 a 0.40.3 a mitad del A/B de la etapa 2; las corridas afectadas se repitieron en 0.40.3 y las de 0.40.2 están archivadas en `eval/baselines/etapa2/ollama_0402/`. Instalador: <https://github.com/ollama/ollama/releases/tag/v0.40.3>. Desactiva las actualizaciones automáticas para no cambiar de versión a mitad de una medición |
| Modelo (por defecto) | `llama3.1:8b-instruct-q4_K_M`, ID `46e0c10c039e` (4.9 GB) |
| Modelos comparados (opcionales) | `qwen2.5-coder:7b-instruct-q4_K_M` ID `dae161e27b0e` (4.7 GB) · `llama3.2:3b-instruct-q4_K_M` ID `a80c4f17acd5` (2.0 GB) |
| Datos | los 9 CSV de Olist, incluidos en el repo (`data/olist/`, 122 MB) |

### Comandos (Git Bash en Windows; en Linux/macOS cambia `py -3.14` por `python3.14` y `Scripts` por `bin`)

```bash
# 0) Código. El venv va FUERA de la carpeta del repo: si el repo está en OneDrive, la sincronización rompe el venv
git clone https://github.com/Adely201810/AnalizadorIA.git && cd AnalizadorIA
py -3.14 -m venv ~/.venvs/analizadoria && source ~/.venvs/analizadoria/Scripts/activate
export PYTHONUTF8=1                                # Windows: sin esto, run_eval falla al redirigir la salida (UnicodeEncodeError, cp1252)
python --version                                   # Python 3.14.3
python -m pip install -r requirements.lock.txt     # versiones exactas

# 1) Base de datos: esquema + 9 CSV + 7 vistas -> db/olist.db (no se versiona; ~1-2 min)
python seeder/load_olist_csv.py

# 2) Oráculo: reconstruirlo debe dar EXACTAMENTE los archivos versionados, y pandas debe coincidir.
#    El constructor parte del oráculo v2 (commit cb20411); se restaura desde git y el script lo convierte en v3
git show cb20411:eval/ground_truth_olist.json > eval/ground_truth_olist.json
python -m eval.construir_oraculo_v3
git diff --exit-code eval/ground_truth_olist.json eval/split_oraculo.json && echo "oráculo idéntico"
python -m dashboard.verify_pandas                  # todas las líneas deben decir [OK]

# 3) Pruebas automáticas (no necesitan Ollama)
python -m unittest discover -s tests -t .          # Ran 64 tests ... OK

# 4) Ollama 0.40.3 y el modelo (instálalo antes desde el enlace de la tabla)
ollama --version                                   # ollama version is 0.40.3
ollama pull llama3.1:8b-instruct-q4_K_M            # ~4.9 GB
ollama list                                        # el ID debe ser 46e0c10c039e

# 5) Evaluación en DESARROLLO (configuración final por defecto; ~5 min por repetición)
for k in 1 2 3; do python eval/run_eval.py --sin-plantillas --conjunto desarrollo --output eval/eval_results_desarrollo_r$k.json; done

# 6) Interfaz: chat en http://localhost:8501 y dashboard en la página "Dashboard"
streamlit run app.py
```

Notas:
- **PRUEBA no se vuelve a evaluar para ajustar nada** (ya se usó una vez; ver docs/INFORME_FINAL_2.md §6). El comando exacto que se usó está en [docs/E2_PASO_5.md](docs/E2_PASO_5.md).
- **Variación esperable:** con la misma configuración, DESARROLLO dio 8, 9, 8; luego 10, 7, 9; y 6, 8, 7 al reproducirlo desde un clon limpio (9 repeticiones: rango 6–10, media 8.0). Una repetición sola no basta para comparar.
- **Variables del pipeline:** `OLLAMA_MODEL`, `OLLAMA_HOST`, `TEXT2SQL_CLASIFICADOR` (0 por defecto), `TEXT2SQL_VISTA_VALIDOS` (1 por defecto) y `TEXT2SQL_N_INTENTOS` (2). Ver [docs/ENTORNO.md](docs/ENTORNO.md).
- Detalles de instalación y despliegue: [docs/DEPLOY.md](docs/DEPLOY.md). Diccionario de datos: [docs/esquema_olist.md](docs/esquema_olist.md).

## Estructura

| Carpeta | Contenido |
|---|---|
| `db/` | Esquema Olist (SQLAlchemy ORM), conexión de solo lectura, vistas analíticas |
| `seeder/` | `load_olist_csv.py` (loader de los CSV reales de Olist) |
| `llm/` | Cliente de Ollama, contexto de esquema (con few-shot), guardas de seguridad SQL, pipeline Text-to-SQL, CLI |
| `eval/` | Oráculo v3 de 30 preguntas (`ground_truth_olist.json`, split DESARROLLO 20 / PRUEBA 10), árbitro determinista (`comparador.py`), runner de evaluación, A/B con repeticiones (`ab.py`) y corridas guardadas (`eval/baselines/`) |
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
