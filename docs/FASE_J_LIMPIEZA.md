# J — Limpieza: P2 y restos del dataset del gimnasio a `legacy/`

Fecha: 2026-10-10 · Estado: **COMPLETA** · Nada se borró: solo `git mv`

## P2: `llm/schema_context.py` como script y como módulo
Antes, `python llm/schema_context.py` fallaba con `ModuleNotFoundError: No module named 'db'`, porque Python pone `llm/` en `sys.path`. Ahora, si se ejecuta como script (`__package__` vacío), agrega la raíz del repositorio a `sys.path` antes de importar.
```
===== $ python llm/schema_context.py
--- ~1349 palabras, 11531 caracteres ---
[exit code: 0]
===== $ python -m llm.schema_context
--- ~1349 palabras, 11531 caracteres ---
[exit code: 0]
```

## Restos del gimnasio → `legacy/gimnasio/` (con `git mv`, se conserva el historial)
| Antes | Ahora |
|---|---|
| `db/models.py`, `db/database.py`, `db/init_db.py`, `db/schema.sql`, `db/views.sql` | `legacy/gimnasio/db/` |
| `seeder/seed.py` | `legacy/gimnasio/seeder/seed.py` |
| `eval/ground_truth.json`, `eval/eval_rerun_failed_20260911_135003.json`, `eval/resumen_correcciones.json` | `legacy/gimnasio/eval/` |
| `docs/diccionario_datos.md` | `legacy/gimnasio/docs/` |

Además: `legacy/gimnasio/README.md` (qué es y cómo usarlo).

**Qué los referenciaba y cómo se actualizó:**
- `legacy/gimnasio/db/init_db.py` y `legacy/gimnasio/seeder/seed.py`: importaciones `db.*` → `legacy.gimnasio.db.*` y `sys.path` a la raíz del repositorio (`parents[3]`).
- `legacy/gimnasio/db/database.py`: base por defecto `legacy/gimnasio/db/gimnasio.db` (sigue respetando `DATABASE_URL`).
- `eval/compute_ground_truth.py --dataset gimnasio`: nueva ruta del ground truth y del engine.
- `.gitignore` (`legacy/gimnasio/db/gimnasio.db`), `README.md`, `docs/DEPLOY.md`, `docs/esquema_olist.md` y el docstring de `db/olist_models.py`.
- `DIAGNOSTICO.md` y los docs de fases anteriores **no se tocaron**: son registros de lo que había en su momento.

## Verificación tras el movimiento
```
===== suite completa
Ran 49 tests in 107.327s
OK
===== $ python eval/compute_ground_truth.py (olist)
[OK] n08_categoria_mas_resenas_1_estrella   -> [('fashion_male_clothing', 22.73, 110)]
[OK] n09_categorias_mas_compra_unica        -> [('consoles_games', 1054, 1050, 99.62), ('electronics', 2543, 2533, 99.61), ('cool_stuff', 3616, 3600, 99.56), ('small_appliances', 622, 619, 99.52), ('construction_tools_construction', 746, 742, 99.46)]
[OK] n10_estado_mas_clientes_por_vendedor   -> [('BA', 170.74, 3244, 19)]
[exit code: 0]
===== legacy: DATABASE_URL=sqlite:///…/scratchpad/gimnasio_prueba.db python legacy/gimnasio/seeder/seed.py
  descuentos                         15
  encuestas_satisfaccion          4,869
  tickets_soporte                   300
  calendario_eventos                 13

Seed completado con éxito.
[exit code: 0]
===== legacy: python eval/compute_ground_truth.py --dataset gimnasio
q1_altas_enero                         -> [(325,)]
q2_mes_max_luz                         -> [('07', 5562.12)]
q3_retencion_q2                        -> [(0.7694,)]
q4_churn_q4                            -> [(0.274,)]
q5_membresias_anual                    -> [(297,)]
[exit code: 0]
```
(La base del gimnasio de prueba se creó en el scratchpad, no en el proyecto.)

Páginas de Streamlit ejecutadas sin navegador (`streamlit.testing.v1.AppTest`):
```
app.py: excepciones=0 | errores=[] | títulos=['📊 Asistente de datos — Olist'] | 1.7 s
pages/1_Dashboard.py: excepciones=0 | errores=[] | títulos=['📈 Dashboard de verificación — Olist'] | 26.6 s
```

## Decisión propia
D-19: estructura `legacy/gimnasio/{db,seeder,eval,docs}` y no editar los documentos históricos.
