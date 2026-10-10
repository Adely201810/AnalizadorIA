# Progreso del plan (B → J)

Última actualización: 2026-10-10. Decisiones en [DECISIONES.md](DECISIONES.md).

| Paso | Estado | Commit | Cifras reales | Doc |
|---|---|---|---|---|
| A — Entorno | ✅ | `7d09a5e` | Ollama 0.40.2, llama3.1 8B al 100 % en GPU (5.8 GB VRAM) | [ENTORNO.md](ENTORNO.md) |
| Oráculo consistente (D-01..D-04) | ✅ | `5dd3215` | q2 1,255,695.13 · q4 top 5 sin empates · q6 163.32 · q10 160.24; los 4 cruzados con pandas al centavo | [DECISIONES.md](DECISIONES.md) |
| B — Línea base 00 | ✅ | (este commit) | SQL correcto **6/10 (60 %)**; texto confiable 10/10. Al menos 3 de los 6 aciertos son falsos positivos (q5, q6, q7) | [BASELINE.md](BASELINE.md) |
| C — Fase 1 | ⏳ en curso | | | |
| C — Fase 3 | pendiente | | | |
| D — Fase 2 | pendiente | | | |
| E — Fase 5 | pendiente | | | |
| F — Fase 4 | pendiente | | | |
| G — Fases 6, 9, 7, 8 | pendiente | | | |
| H — Fase 10 | pendiente | | | |
| I — Fase 11 | pendiente | | | |
| J — Limpieza | pendiente | | | |

## Pendientes / avisos
- Una evaluación completa de 10 preguntas con el modelo ya cargado tarda ≈3.5 min.
