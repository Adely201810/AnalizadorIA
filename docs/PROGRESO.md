# Progreso del plan (B → J)

Última actualización: 2026-10-10. Decisiones en [DECISIONES.md](DECISIONES.md).

| Paso | Estado | Commit | Cifras reales | Doc |
|---|---|---|---|---|
| A — Entorno | ✅ | `7d09a5e` | Ollama 0.40.2, llama3.1 8B al 100 % en GPU (5.8 GB VRAM) | [ENTORNO.md](ENTORNO.md) |
| Oráculo consistente (D-01..D-04) | ✅ | `5dd3215` | q2 1,255,695.13 · q4 top 5 sin empates · q6 163.32 · q10 160.24; los 4 cruzados con pandas al centavo | [DECISIONES.md](DECISIONES.md) |
| B — Línea base 00 | ✅ | `0982d27` | SQL correcto **6/10 (60 %)**; texto confiable 10/10. Al menos 3 de los 6 aciertos son falsos positivos (q5, q6, q7) | [BASELINE.md](BASELINE.md) |
| C — Fase 1 | ✅ | `276fc4f` | Tipos en todas las columnas (antes faltaba INTEGER y se usaba STRING); 4 few-shot + 2 del clasificador reemplazados; prueba de disyunción 6/6 | [FASE_01.md](FASE_01.md) |
| C — Fase 3 | ✅ | (este commit) | **baseline_01: 2/10 (20 %)** sin plantillas. baseline_00 recalificado con el árbitro nuevo: 3/10. Límite de 60 s para el SQL del modelo (una consulta quedó colgada >10 min) | [FASE_03.md](FASE_03.md) |
| D — Fase 2 | pendiente | | | |
| E — Fase 5 | pendiente | | | |
| F — Fase 4 | pendiente | | | |
| G — Fases 6, 9, 7, 8 | pendiente | | | |
| H — Fase 10 | pendiente | | | |
| I — Fase 11 | pendiente | | | |
| J — Limpieza | pendiente | | | |

## Pendientes / avisos
- Una evaluación completa de 10 preguntas tarda entre 3.5 y 8 min (depende de reintentos y de consultas lentas).
- La cifra honesta actual es **2/10**; las cifras anteriores estaban infladas (ver FASE_03.md).
