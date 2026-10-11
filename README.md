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

## Inicio rápido

**Versión de Python verificada: 3.14.3** (Windows 11). Las versiones exactas
instaladas y probadas están en `requirements.lock.txt`; detalles del entorno en
[docs/ENTORNO.md](docs/ENTORNO.md).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock.txt          # versiones fijadas (o requirements.txt para rangos)

python db/olist_init_db.py --export-ddl      # crea el esquema + vistas
python seeder/load_olist_csv.py               # carga los 9 CSV de data/olist/
ollama pull llama3.1:8b-instruct-q4_K_M       # modelo LLM local (una vez)

python -m llm.cli "¿Cuántos pedidos hay en total?"
python eval/run_eval.py                       # evaluación de precisión (10 preguntas)
streamlit run app.py                          # interfaz gráfica de chat
```

Ver **[docs/DEPLOY.md](docs/DEPLOY.md)** para instrucciones detalladas de
instalación y despliegue, y **[docs/esquema_olist.md](docs/esquema_olist.md)**
para el diccionario de datos completo.

## Estructura

| Carpeta | Contenido |
|---|---|
| `db/` | Esquema Olist (SQLAlchemy ORM), conexión de solo lectura, vistas analíticas |
| `seeder/` | `load_olist_csv.py` (loader de los CSV reales de Olist) |
| `llm/` | Cliente de Ollama, contexto de esquema (con few-shot), guardas de seguridad SQL, pipeline Text-to-SQL, CLI |
| `eval/` | Oráculo de las 10 necesidades (`ground_truth_olist.json`), árbitro determinista, runner de evaluación, benchmark de modelos y líneas base (`eval/baselines/`) |
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
