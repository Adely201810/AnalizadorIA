# Dataset histórico: gimnasio ficticio "FitZone"

Primer dataset del proyecto, **reemplazado por Olist**. Se conserva sin cambios de lógica; solo se
movió aquí (fase J de limpieza, ver `docs/DECISIONES.md` D-19) y se ajustaron sus importaciones.

| Archivo | Contenido |
|---|---|
| `db/models.py`, `db/database.py`, `db/init_db.py`, `db/schema.sql`, `db/views.sql` | Esquema ORM, conexión (`DATABASE_URL`, por defecto `legacy/gimnasio/db/gimnasio.db`), creación y vistas |
| `seeder/seed.py` | Generador de datos sintéticos (año 2025) |
| `eval/ground_truth.json` | 20 preguntas con referencia (oráculo viejo del gimnasio) |
| `eval/eval_rerun_failed_20260911_135003.json`, `eval/resumen_correcciones.json` | Resultados de evaluación de septiembre de 2026 |
| `docs/diccionario_datos.md` | Diccionario de datos |

Uso (desde la raíz del repositorio):

```bash
python legacy/gimnasio/seeder/seed.py                      # crea legacy/gimnasio/db/gimnasio.db
python eval/compute_ground_truth.py --dataset gimnasio     # recalcula su ground truth
```
