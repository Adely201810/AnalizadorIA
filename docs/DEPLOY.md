# Despliegue — Olist Analytics (LLM local)

Guía para levantar el proyecto de punta a punta en una máquina con:

- CPU: AMD Ryzen 5 (serie 7000) o equivalente
- RAM: 16 GB totales (~14 GB utilizables)
- SO: Linux (probado), debería funcionar igual en macOS/Windows con Ollama nativo
- Motor LLM local: [Ollama](https://ollama.com) en `http://localhost:11434`

Con este hardware, el modelo recomendado es **Llama 3.1 8B cuantizado en 4 bits**
(`llama3.1:8b-instruct-q4_K_M`, ~4.9 GB en disco / RAM), que deja margen para el
sistema operativo y la base de datos SQLite en memoria compartida.

---

## 1. Instalar Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Verifica que el servicio esté corriendo (por defecto en :11434)
ollama serve &
curl http://localhost:11434/api/tags
```

En instalaciones vía paquete del sistema, `ollama serve` puede ya estar
gestionado como servicio (`systemctl status ollama`); en ese caso no hace
falta lanzarlo a mano.

## 2. Descargar el modelo

Modelo objetivo (recomendado, balance calidad/RAM en 16 GB):

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
```

Alternativas si el hardware es más justo o se quiere comparar calidad/velocidad:

```bash
ollama pull mistral:7b-instruct-q4_K_M         # más ligero, algo menos preciso en SQL complejo
ollama pull qwen2.5:7b-instruct-q4_K_M         # buen balance, fuerte en tareas estructuradas
ollama pull qwen2.5:14b-instruct-q4_K_M        # solo si hay holgura real de RAM (>20 GB libres)
```

Para usar un modelo distinto al default sin tocar código, exporta la variable
de entorno antes de correr el CLI o la evaluación:

```bash
export OLLAMA_MODEL="mistral:7b-instruct-q4_K_M"
```

> **Nota sobre RAM compartida:** el módulo `llm/ollama_client.py` fija
> `num_ctx=4096` y limita `num_predict` (350 tokens para SQL, 250 para la
> síntesis en lenguaje natural) para no inflar el KV-cache del modelo. El
> esquema inyectado como contexto (`llm/schema_context.py`) es una versión
> compacta (~1,000 tokens) del diccionario de datos completo — deliberado,
> para dejar margen de RAM en equipos de 16 GB. Ajusta `OLLAMA_NUM_CTX` y
> `OLLAMA_TIMEOUT` (default 300s: las preguntas abiertas hacen varias llamadas) por variable de entorno si tu hardware da para más (o menos).

## 3. Preparar el entorno Python

Requiere Python 3.10+ (probado con 3.14).

```bash
cd AnalizadorIA
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Levantar la base de datos

Por defecto usa SQLite en `db/olist.db`. No requiere instalar ningún motor de
base de datos aparte.

```bash
python db/olist_init_db.py --export-ddl
```

Esto crea las 9 tablas, las 3 vistas analíticas (`db/olist_views.sql`) y
exporta el DDL resultante a `db/olist_schema.sql` (referencia legible,
generada desde `db/olist_models.py`).

### Migrar a PostgreSQL (opcional)

El esquema está escrito en SQLAlchemy con tipos genéricos, por lo que no hay
que tocar `db/olist_models.py`. Basta con:

```bash
pip install psycopg2-binary
export OLIST_DATABASE_URL="postgresql+psycopg2://usuario:password@localhost:5432/olist"
python db/olist_init_db.py
```

Nota: `db/olist_views.sql` usa `julianday()` (específico de SQLite). Para
Postgres, adapta esas 3 vistas usando diferencias de `timestamp`/`EXTRACT(EPOCH
FROM ...)` como se indica en los comentarios del propio archivo. El ejecutor
de solo-lectura del módulo LLM (`llm/text_to_sql.py::execute_readonly`)
también está escrito para SQLite; para Postgres, reemplázalo por una conexión
con `SET TRANSACTION READ ONLY` (ver comentario en ese archivo).

## 5. Cargar los datos de Olist

```bash
python seeder/load_olist_csv.py
```

Carga los 9 CSV públicos de `data/olist/` (customers, geolocation, sellers,
products, product_category_translation, orders, order_items, order_payments,
order_reviews). Al final imprime un resumen que compara el conteo de filas en
la base de datos contra el conteo real de cada CSV (leído con pandas) para
confirmar que no se perdió ni duplicó ninguna fila.

El script es **idempotente**: por defecto limpia y recrea todas las tablas
antes de insertar (usa `--no-reset` para agregar sin limpiar, no recomendado).

```bash
python seeder/load_olist_csv.py --data-dir otra/ruta/con/los/csv   # otra ubicación de los CSV
```

> Si recargas los CSV desde otra versión del dataset, los valores de
> referencia en `eval/ground_truth_olist.json` dejan de ser válidos.
> Regenéralos con `python eval/compute_ground_truth.py` y actualiza el JSON a
> mano.

## 6. Probar el módulo Text-to-SQL

Con Ollama corriendo y el modelo descargado, por CLI:

```bash
python -m llm.cli
# o una sola pregunta desde línea de comandos:
python -m llm.cli "¿Cuántos pedidos hay en total?"
```

O con la interfaz de chat (Streamlit), que usa exactamente el mismo pipeline:

```bash
streamlit run app.py
```

El flujo internamente: pregunta en español → prompt con el esquema compacto
(tablas, vistas, notas y ejemplos few-shot) → Ollama genera SQL →
`llm/sql_guard.py` valida que sea un único `SELECT` de solo lectura (rechaza
`INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/ATTACH`, y cualquier intento de colar
una segunda sentencia) → se ejecuta contra SQLite en una conexión abierta en
**modo solo-lectura** (`file:...?mode=ro`) → si algo falla (o la consulta
devuelve 0 filas de forma sospechosa), se reintenta reenviando el error/aviso
al modelo para que se autocorrija, hasta completar `n_intentos` intentos en
total (por defecto 2; variable `TEXT2SQL_N_INTENTOS`) → el resultado se sintetiza
en una respuesta en español con tono de analista de negocio.

### Capa de validación/plantillas (patrones donde el LLM de 8B falla)

Antes y después de la generación libre del modelo hay reglas deterministas
(`llm/sql_templates.py`, `llm/sql_guard.py`):

- **Plantillas por reglas** (no se consulta al modelo): concentración/Pareto
  ("concentran el 80%", "top 10%") con ventana acumulativa, y series mensuales
  ("mes a mes", "meses incompletos" = primer y último mes del rango de datos,
  "crecimiento de 2017 a 2018" comparando solo meses completos comunes).
- **Sanitización de alias**: alias que son palabras reservadas de SQLite
  (`order_reviews or`) se renombran (`orv`) antes de ejecutar.
- **Validación contra el esquema real**: `alias.columna` inexistente
  (`orders.seller_id`) y joins entre llaves de dominios distintos
  (`order_id = seller_id`) se rechazan con un mensaje específico que se le
  devuelve al modelo en el reintento.
- **Fallback a vistas**: si tras el reintento el SQL de una pregunta sobre
  vendedores sigue roto, se usa `vw_ingresos_por_vendedor` (o la plantilla de
  vendedores a revisar). El JSON exportado indica `origen` (`llm`,
  `plantilla:<nombre>` o `fallback_vista:<nombre>`) y `rechazo_llm`.

## 7. Correr la suite de evaluación

```bash
python eval/run_eval.py
```

Corre las 10 preguntas de `eval/ground_truth_olist.json` contra el pipeline
real, compara la respuesta del modelo (tanto el texto sintetizado como las
celdas crudas del resultado SQL) contra los valores esperados con una
tolerancia definida por pregunta, e imprime precisión objetiva (`X/10
correctas`). Guarda el detalle en `eval/eval_results_<timestamp>.json`.

```bash
python eval/run_eval.py --model qwen2.5:7b-instruct   # comparar otro modelo
python eval/run_eval.py --limit 5                        # prueba rápida
```

### Comparar varios modelos

El modelo es configurable por variable de entorno (`OLLAMA_MODEL`, ver
`llm/ollama_client.py`) o por el flag `--model` de `eval/run_eval.py` -- ambos
caminos ya están soportados, no hace falta tocar código para comparar:

```bash
ollama pull qwen2.5:7b-instruct
ollama pull qwen2.5-coder:7b

for modelo in llama3.1:8b-instruct-q4_K_M qwen2.5:7b-instruct qwen2.5-coder:7b; do
  echo "=== $modelo ==="
  python eval/run_eval.py --model "$modelo" --output "eval/eval_results_${modelo//[:\/]/_}.json"
done
```

`app.py` (la interfaz Streamlit) muestra en el sidebar el modelo activo
(`OllamaClient().model`, que respeta `OLLAMA_MODEL`), así que para probar un
modelo distinto en la UI basta con exportar la variable antes de
`streamlit run app.py`.

---

## Resumen de comandos (de cero a funcionando)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b-instruct-q4_K_M

cd AnalizadorIA
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python db/olist_init_db.py --export-ddl
python seeder/load_olist_csv.py
python -m llm.cli "¿Cuántos pedidos hay en total?"
python eval/run_eval.py
streamlit run app.py
```

## Estructura del proyecto

```
AnalizadorIA/
├── app.py                    # Interfaz de chat (Streamlit), mismo pipeline que llm/cli.py
├── db/
│   ├── olist_models.py       # Esquema ORM de Olist (SQLAlchemy, portable SQLite/PostgreSQL)
│   ├── olist_database.py     # Conexión (respeta OLIST_DATABASE_URL)
│   ├── olist_views.sql       # Vistas analíticas (ventas por pedido, clientes recurrentes, retrasos)
│   ├── olist_init_db.py      # Crea tablas + vistas; exporta DDL
│   └── olist_schema.sql      # DDL exportado (generado, para lectura humana)
├── seeder/
│   └── load_olist_csv.py     # Loader de los 9 CSV de Olist (idempotente)
├── llm/
│   ├── ollama_client.py      # Cliente HTTP de la API de Ollama (modelo configurable por OLLAMA_MODEL)
│   ├── schema_context.py     # Esquema compacto + notas + ejemplos few-shot para el prompt
│   ├── sql_guard.py           # Validación de seguridad (solo SELECT) + calidad (alias reservados, columnas inexistentes, joins entre dominios distintos)
│   ├── sql_templates.py       # Plantillas SQL fijas por reglas (Pareto, series mensuales) y fallbacks sobre vistas (vendedores)
│   ├── text_to_sql.py         # Pipeline completo pregunta -> SQL -> respuesta (reintento si SQL falla o resultado viene vacío)
│   └── cli.py                  # CLI interactivo
├── eval/
│   ├── ground_truth_olist.json # 10 necesidades de negocio (fuente única del oráculo y del dashboard)
│   ├── compute_ground_truth.py
│   └── run_eval.py             # Corre y califica la evaluación
├── data/olist/                # 9 CSV públicos de Olist (fuente de datos)
├── docs/
│   ├── esquema_olist.md      # Diccionario de datos de Olist (lectura humana)
│   └── DEPLOY.md              # Este documento
├── legacy/gimnasio/           # Dataset histórico del gimnasio (modelos, seeder, ground truth, docs)
└── requirements.txt
```
