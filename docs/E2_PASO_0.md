# Etapa 2 · Paso 0 — Entorno tras el reinicio

Fecha: 2026-10-11 · Estado: **COMPLETO**

## Ollama sin `ollama serve` manual
Tras reiniciar Windows (arranque 09:41:20), la app de bandeja levantó su servidor sola: `ollama app` arrancó a las 09:43:01 y `ollama` (servidor) a las 09:43:02. `GET /api/version` → `{"version":"0.40.2"}`. **Resuelto** el problema abierto de la etapa 1 (la app no levantaba el servidor desde las ~17:46 del día anterior).

## Velocidad por modelo (`python -m eval.medir_velocidad`, benchmark fijo)
Mismo prompt (párrafo de ~120 palabras sobre bases de datos), `temperature=0`, `seed=42`, `num_predict=160`, 3 repeticiones tras la carga; antes de cada modelo se descargan los demás de la VRAM.
```
| Modelo | num_ctx | Carga | Generación tok/s (3 rep.) | Media | ollama ps |
|---|---|---|---|---|---|
| llama3.1:8b-instruct-q4_K_M | 4096 | 19.6 s | [37.05, 37.17, 37.2] | 37.14 | 5.26 GB, VRAM 5.26 GB (100.0 % GPU) |
| llama3.1:8b-instruct-q4_K_M | 8192 | 25.8 s | [37.4, 39.1, 39.06] | 38.52 | 5.8 GB, VRAM 5.8 GB (100.0 % GPU) |
| qwen2.5-coder:7b-instruct-q4_K_M | 4096 | 19.16 s | [18.48, 18.05, 18.49] | 18.34 | 4.74 GB, VRAM 4.74 GB (100.0 % GPU) |
| qwen2.5-coder:7b-instruct-q4_K_M | 8192 | 20.14 s | [19.14, 18.68, 19.13] | 18.98 | 5.12 GB, VRAM 5.12 GB (100.0 % GPU) |
| llama3.2:3b-instruct-q4_K_M | 4096 | 7.86 s | [77.61, 77.58, 77.54] | 77.58 | 2.55 GB, VRAM 2.55 GB (100.0 % GPU) |
| llama3.2:3b-instruct-q4_K_M | 8192 | 8.11 s | [73.58, 73.53, 73.33] | 73.48 | 3.09 GB, VRAM 3.09 GB (100.0 % GPU) |
```
Salida completa en `logs/paso0_velocidad.log`.

## Comparación con lo reportado
| | Etapa 1, 16:49 (app de bandeja) | Etapa 1, ≥ 17:50 (servidor manual) | Hoy (tras reinicio) |
|---|---|---|---|
| llama3.1 8B, generación | 36.32 tok/s | 3.6-4.8 tok/s | **37.1 (ctx 4096) / 38.5 (ctx 8192) tok/s** |

Los tres modelos corren **100 % en GPU**. **Diagnóstico:** la lentitud era un estado transitorio del sistema que el reinicio eliminó. Los dos intentos de la etapa 1 (DLL de Git Bash, competencia de recursos) ya lo habían descartado como causa del entorno de proceso; no se pudo identificar una causa más precisa y ya no es reproducible.

## Corrección a la etapa 1
En la Fase 4 se concluyó que qwen2.5-coder era "más rápido" que llama3.1. **Era un artefacto del estado lento.** Con medición limpia, **llama3.1 genera ~2× más rápido que qwen2.5-coder** (38.5 frente a 19.0 tok/s con contexto 8192). Las latencias de llama3.1 de las Fases 2, 4 y 6-11 de la etapa 1 no son válidas.
