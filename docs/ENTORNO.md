# Entorno de ejecución (Prerrequisito A)

Fecha: 2026-10-10 · Estado: **PARCIAL**. Pasos 1-4 y 7 (dashboard) hechos y verificados. Pasos 5-6 (Ollama + modelo) **bloqueados por espacio en disco**. La prueba de `llm.cli` con Ollama sigue pendiente.

## Hardware

| Componente | Valor | Cómo se obtuvo |
|---|---|---|
| CPU | AMD Ryzen 5 PRO 4650G with Radeon Graphics (6 núcleos / 12 hilos) | `Win32_Processor` |
| RAM | 15.8 GB total; **3.06 GB libres** al momento de medir | `Win32_ComputerSystem`, `Win32_OperatingSystem` |
| GPU | AMD Radeon RX 6600. WMI reporta `AdapterRAM` = 4095 MB, pero ese campo de 32 bits satura en 4 GB; la RX 6600 tiene 8 GB de especificación. **VRAM real no verificada** (pendiente de confirmar con Ollama). | `Win32_VideoController` |
| SO | Windows 11 Pro 10.0.26200 | `Win32_OperatingSystem` |
| Disco | C: **5.13 GB libres** (6.2 GB antes de crear el venv y la BD); D: 3.13 GB libres | `Get-PSDrive` |

## Software

| Componente | Versión |
|---|---|
| Python | 3.14.3 (tags/v3.14.3:323c59a, MSC v.1944 64 bit) |
| SQLite (módulo `sqlite3`) | 3.50.4 |
| Paquetes | ver `requirements.lock.txt` (47 paquetes). Principales: SQLAlchemy 2.1.4, pandas 3.0.6, streamlit 1.65.0, plotly 7.1.0, matplotlib 3.11.2, reportlab 5.0.1, requests 2.34.2, Faker 40.43.0 |
| Ollama | **no instalado** (última versión en winget: 0.40.2) |

## Comandos reproducibles (Windows, PowerShell)

```powershell
# 1. Entorno virtual FUERA de OneDrive (ver decisión D1)
py -3.14 -m venv $env:USERPROFILE\.venvs\analizadoria
& $env:USERPROFILE\.venvs\analizadoria\Scripts\python.exe -m pip install --upgrade pip
& $env:USERPROFILE\.venvs\analizadoria\Scripts\python.exe -m pip install -r requirements.lock.txt

# 2. Base de datos (lee data/olist/*.csv, crea db/olist.db con esquema + vistas)
& $env:USERPROFILE\.venvs\analizadoria\Scripts\python.exe seeder\load_olist_csv.py

# 3. Oráculo sin LLM
& $env:USERPROFILE\.venvs\analizadoria\Scripts\python.exe eval\compute_ground_truth.py
& $env:USERPROFILE\.venvs\analizadoria\Scripts\python.exe -m dashboard.verify_pandas

# 4. Contexto de esquema (como módulo, NO como script: ver problema P2)
& $env:USERPROFILE\.venvs\analizadoria\Scripts\python.exe -m llm.schema_context

# 5. App
& $env:USERPROFILE\.venvs\analizadoria\Scripts\python.exe -m streamlit run app.py
```

Para los comandos de diagnóstico se usó `PYTHONDONTWRITEBYTECODE=1` (no escribir `__pycache__`) y `PYTHONIOENCODING=utf-8` (ver problema P1).

## Resultados

### Paso 1 — Dependencias
`pip install -r requirements.txt` sobre Python 3.14.3 terminó con `exit code 0`. Todas las librerías tienen wheels `cp314`, así que **no hizo falta otra versión de Python**. El lockfile se generó con `pip freeze > requirements.lock.txt`.

### Paso 2 — Base de datos
Los 9 CSV estaban presentes. `seeder/load_olist_csv.py` tardó 34.4 s, generó un `db/olist.db` de 198,574,080 bytes y su verificación interna dio:

```
  sellers                          csv=   3,095  db=   3,095  OK
  customers                        csv=  99,441  db=  99,441  OK
  products                         csv=  32,951  db=  32,951  OK
  product_category_translation     csv=      71  db=      71  OK
  geolocation                      csv=1,000,163  db=1,000,163  OK
  orders                           csv=  99,441  db=  99,441  OK
  order_items                      csv= 112,650  db= 112,650  OK
  order_payments                   csv= 103,886  db= 103,886  OK
  order_reviews                    csv=  99,224  db=  99,224  OK
```

### Paso 3 — Riesgo de BD vacía (único cambio de código)
`llm/schema_context.py`: nueva función `_verificar_bd_existe()`, llamada en `get_esquema_real()` y `build_schema_context()` antes de cualquier `engine.connect()`. No se puso en `_valores_categoricos()` (línea ~113) porque ahí un `except Exception` se tragaría el error; `build_schema_context()` ya la llama antes de llegar ahí.

Prueba con una ruta inexistente (`OLIST_DATABASE_URL=sqlite:///C:/Users/alexp/AppData/Local/Temp/no_existe_olist.db`):

```
FileNotFoundError: No existe la base de datos C:\Users\alexp\AppData\Local\Temp\no_existe_olist.db. Créala con: python seeder/load_olist_csv.py
[exit code: 1]
ls: cannot access 'C:/Users/alexp/AppData/Local/Temp/no_existe_olist.db': No such file or directory
```

Con la BD real: `--- ~1404 palabras, 12235 caracteres ---`, `exit code 0`.

### Paso 4 — Oráculo y verificación con pandas

```
q1_pedidos_totales               -> [(99441,)]
q2_categoria_mas_ingresos        -> [('health_beauty', 1258681.34)]
q3_pct_clientes_recurrentes      -> [(3.04,)]
q4_categorias_mas_compra_unica   -> [('tablets_printing_image', 79, 100.0), ('small_appliances_home_oven_and_coffee', 75, 100.0), ('fixed_telephony', 214, 100.0), ('fashion_underwear_beach', 121, 100.0), ('costruction_tools_tools', 97, 100.0)]
q5_retraso_baja_calificacion     -> [(2.57, 4.29)]
q6_metodo_pago_mayor_venta_promedio -> [('credit_card', 163.94)]
q7_estado_mas_pedidos_entregados -> [('SP', 40501)]
q8_tiempo_promedio_entrega       -> [(12.56,)]
q9_pedidos_sin_entrega           -> [(2965,)]
q10_ticket_promedio_pedido       -> [(160.58,)]
```

Los 10 valores coinciden con los de `eval/ground_truth_olist.json`.

```
=== Verificación pandas (CSV) vs SQL (olist.db) ===
[OK] Clientes únicos con pedido válido: pandas=94,990.00 | sql=94,990.00 | diff=0.0000
[OK] % clientes recurrentes: pandas=3.04 | sql=3.04 | diff=0.0000
[OK] Ingresos categoría top (R$): pandas=1,255,695.13 | sql=1,255,695.13 | diff=0.0000
[OK] % ingresos top 5 categorías: pandas=39.82 | sql=39.82 | diff=0.0032
[OK] % pedidos tardíos (global): pandas=8.11 | sql=8.11 | diff=0.0000
```

**Por qué verify_pandas cubre "3 de 10":** el script recalcula 5 métricas que salen solo de `q01`, `q03` y `q08` (`dashboard/verify_pandas.py:93-119`). El código no explica por qué se eligieron esas, y el historial de git no ayuda (un único commit). Además, **verifica el dashboard, no el oráculo**: nunca lee `ground_truth_olist.json`.

**Diferencias oráculo vs pandas** (consultas de solo lectura):
- *Ingresos de la categoría top*: el oráculo q2 da 1,258,681.34 y pandas/dashboard dan 1,255,695.13 (diferencia de 2,986.21). La causa es la definición: el SQL de referencia de q2 **incluye** pedidos `canceled`/`unavailable`, mientras que el dashboard, pandas y la regla del prompt (`llm/schema_context.py`, nota "Ingresos = SUM(price) excluyendo…") los excluyen. Comprobado: `health_beauty` da 1258681.34 incluyendo y 1255695.13 excluyendo.
- *% clientes recurrentes*: coinciden (3.04 en el oráculo q3 y en pandas).
- *q4 del oráculo es inestable*: **9** categorías empatan en 100.0 % de compra única, y el `ORDER BY pct_compra_unica DESC LIMIT 5` elige 5 de ellas sin desempate, de forma arbitraria.
- La tolerancia por defecto de `_comparar` es 0.5 (en R$ o en puntos porcentuales), bastante amplia para porcentajes.

### Paso 5 — Ollama: **BLOQUEADO por espacio en disco**

| Descarga | Tamaño exacto | Fuente |
|---|---|---|
| Instalador `OllamaSetup.exe` v0.40.2 | 1,578,560,904 bytes (≈1.58 GB) | `Content-Length` de la descarga oficial; URL y SHA256 del manifiesto winget |
| `llama3.1:8b-instruct-q4_K_M` (capa del modelo) | 4,920,738,944 bytes (≈4.92 GB / 4.58 GiB) | manifiesto de `registry.ollama.ai` |

Solo la descarga suma ≈6.5 GB (más lo que ocupa Ollama una vez instalado), y en C: quedan 5.13 GB. En D: quedan 3.13 GB. **No se instaló nada.**

### Paso 7 — Dashboard y CLI (sin Ollama)
- `streamlit run app.py`: el servidor arranca (`/_stcore/health` → `ok`).
- Página **Dashboard**: carga métricas (Pedidos 99,441 · Clientes únicos 96,096 · Vendedores 3,095 · Productos 32,951 · 2016-09-04 → 2018-10-17), el botón del PDF, las 11 pestañas y la tabla "Las 10 preguntas del dueño". La consola del navegador muestra 2 errores `404` de recursos no identificados; el contenido carga igual.
- Página **chat** (`app.py`) sin Ollama, pulsando una pregunta de ejemplo: muestra `No logro conectarme al motor de IA local (Ollama). Verifica que esté corriendo (ollama serve) e intenta de nuevo.`
- `python -m llm.cli "¿Cuántos pedidos hay en total?"` sin Ollama:
  ```
  ⚠ No se pudo conectar a Ollama en http://localhost:11434. Ejecuta 'ollama serve' e intenta de nuevo.
  [exit code: 1]
  ```

## Decisiones tomadas por mi cuenta

- **D1. Venv en `%USERPROFILE%\.venvs\analizadoria`, no en `.venv` dentro del proyecto.** El repo está dentro de OneDrive y el venv tiene miles de archivos (492 MB); OneDrive los sincronizaría. El README conserva el `.venv` genérico para otros entornos.
- **D2. Se mantuvo Python 3.14.3**, porque todas las dependencias instalaron sin errores.
- **D3. Lockfile como `requirements.lock.txt`** (pip freeze) en lugar de uv/poetry, para no añadir herramientas.
- **D4. No se usó `--export-ddl`**, porque reescribiría `db/olist_schema.sql`, que está versionado.

## Problemas encontrados

- **P1.** La consola de Windows (cp1252) muestra mal los acentos de los scripts (`Vistas anal�ticas`). Se resuelve con `PYTHONIOENCODING=utf-8`. Es cosmético; los datos no se ven afectados.
- **P2.** `python llm/schema_context.py` falla con `ModuleNotFoundError: No module named 'db'`, porque mete `llm/` en el `sys.path` en vez de la raíz. Es previo a este cambio; hay que usar `python -m llm.schema_context`. No se corrigió (fuera del alcance permitido).
- **P3. El dashboard tarda ~2 min en la primera carga.** `cached_reporte_pdf()` ejecuta las 10 consultas antes de pintar las pestañas. Tiempos medidos uno por uno, en frío:
  ```
  Q01:    42.30 s OK
  q02:     1.98 s OK
  q03:     7.32 s OK
  q04:    10.59 s OK
  q05:     7.72 s OK
  q06:     6.24 s OK
  q07:     3.40 s OK
  q08:     7.05 s OK
  q09:    17.36 s OK
  q10:    13.32 s OK
  ```
  Total: 117.3 s. No se corrigió (fuera del alcance de este paso).
- **P4.** `eval/compute_ground_truth.py` usa `engine.connect()` directamente, así que sin BD todavía crearía un archivo vacío. El arreglo pedido se limitó a `llm/schema_context.py`.
- **P5. Espacio en disco** insuficiente para Ollama + modelo (paso 5).
- **P6. Definición de "ingresos" inconsistente** entre el oráculo q2 y el resto del proyecto (paso 4). Es una decisión de negocio que hay que tomar.
