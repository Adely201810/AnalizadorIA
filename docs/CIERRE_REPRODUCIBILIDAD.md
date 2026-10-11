# Cierre — verificación de reproducibilidad

Fecha: 2026-10-11. Se siguió la sección "Reproducir desde cero" del README al pie de la letra, en una carpeta temporal y con un clon nuevo.

## Desviaciones necesarias
- **Clon local, no de GitHub:** los commits de la etapa 2 y del cierre no están en GitHub (no se hizo push). `git clone https://github.com/Adely201810/AnalizadorIA.git` traería una versión vieja **hasta que se haga push**.
- **Venv con otro nombre** (`~/.venvs/analizadoria_repro`), para no pisar el venv de trabajo.
- **Ollama y modelos:** ya estaban instalados (0.40.3). `ollama pull` solo verificó el manifiesto y no descargó nada. No se probó una instalación de Ollama desde cero.

## Resultado por paso

| Paso del README | Resultado |
|---|---|
| 0) venv + `pip install -r requirements.lock.txt` | OK (Python 3.14.3) |
| 1) `python seeder/load_olist_csv.py` | OK en 32.7 s; las 9 tablas con csv = db |
| 2) oráculo | **FALLÓ la 1.ª vez** (ver abajo) → corregido en el README → idéntico (`git diff` vacío) |
| 2) `python -m dashboard.verify_pandas` | 39 líneas `[OK]`, 0 `[DIFF]` |
| 3) pruebas | **64/64 OK**; también 64/64 con `OLLAMA_HOST` apuntando a un puerto muerto (no necesitan Ollama) |
| 4) `ollama --version` / `ollama list` | 0.40.3 / ID `46e0c10c039e` (coincide) |
| 5) 3 repeticiones de DESARROLLO | **FALLÓ la 1.ª vez** (ver abajo) → corregido en el README → **6, 8, 7** de 20 |
| 6) `streamlit run app.py` | Chat y Dashboard cargan sin excepciones (revisado en el navegador, puerto 8502) |

## Fallos encontrados y corrección (solo en el README; el código no cambió)
1. **Oráculo:** `python -m eval.construir_oraculo_v3` → `AssertionError: se esperaba el oráculo v2 como punto de partida`. **Causa:** el script es una migración v2 → v3 que lee `eval/ground_truth_olist.json`, y ese archivo ya contiene la v3. **Corrección:** el README restaura antes la v2 desde git (`git show cb20411:eval/ground_truth_olist.json > eval/ground_truth_olist.json`). Con eso, el oráculo reconstruido es byte a byte igual al versionado.
2. **Evaluación en Windows:** `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'` en las 3 repeticiones. **Causa:** al redirigir la salida a un archivo, Python en Windows usa cp1252, que no tiene el emoji ✅ que imprime `run_eval.py`. En las corridas del proyecto siempre se usó `PYTHONIOENCODING=utf-8`, por eso no apareció antes. **Corrección:** `export PYTHONUTF8=1` en el paso 0 del README.
3. **`docs/DEPLOY.md` desactualizado** (habla de 10 preguntas y de otros modelos): se añadió un aviso que remite al README.

## Cifra reproducida
DESARROLLO en el clon: **6, 8, 7** (media 7). Con la misma configuración: 8, 9, 8 (Paso 3) y 10, 7, 9 (Paso 5). El 6 es el valor más bajo visto, y el conjunto de las 9 repeticiones va de 6 a 10, con media 8.0. **La cifra es reproducible solo como rango, no como valor exacto**, aunque el árbol de git, la BD, el oráculo, Ollama y el modelo sean idénticos: la generación del modelo no es determinista entre corridas.
