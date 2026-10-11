# Progreso

Última actualización: 2026-10-11 — **Etapa 2 terminada**; configuración congelada en `02f3dba`. Resumen: [INFORME_FINAL_2.md](INFORME_FINAL_2.md). Decisiones: [DECISIONES.md](DECISIONES.md).

| Paso | Estado | Commit | Cifras reales | Doc |
|---|---|---|---|---|
| A — Entorno | ✅ | `7d09a5e` | Ollama 0.40.2, llama3.1 8B al 100 % en GPU (5.8 GB VRAM) | [ENTORNO.md](ENTORNO.md) |
| Oráculo consistente (D-01..D-04) | ✅ | `5dd3215` | q2 1,255,695.13 · q4 top 5 sin empates · q6 163.32 · q10 160.24; los 4 cruzados con pandas al centavo | [DECISIONES.md](DECISIONES.md) |
| B — Línea base 00 | ✅ | `0982d27` | SQL correcto **6/10 (60 %)**; texto confiable 10/10. Al menos 3 de los 6 aciertos son falsos positivos (q5, q6, q7) | [BASELINE.md](BASELINE.md) |
| C — Fase 1 | ✅ | `276fc4f` | Tipos en todas las columnas (antes faltaba INTEGER y se usaba STRING); 4 few-shot + 2 del clasificador reemplazados; prueba de disyunción 6/6 | [FASE_01.md](FASE_01.md) |
| C — Fase 3 | ✅ | `d5f096a` | **baseline_01: 2/10 (20 %)** sin plantillas. baseline_00 recalificado con el árbitro nuevo: 3/10. Límite de 60 s para el SQL del modelo (una consulta quedó colgada >10 min) | [FASE_03.md](FASE_03.md) |
| D — Fase 2 | ✅ | `f23c019` | Clasificación por intento y final. Corrida real: ok 2 · ejecución 2 · **semántico 6** · seguridad 0 · infra 0. Seguridad (`DELETE` real) e infra (Ollama detenido) verificados con el modelo; 9/9 pruebas | [FASE_02.md](FASE_02.md) |
| E — Fase 5 | ✅ | `cb20411` | Oráculo v2 = 10 necesidades del dashboard, 1 consulta cada una; **SQL 10/10 y pandas 10/10**; el dashboard muestra la respuesta de referencia en cada pestaña; few-shot sin métricas del oráculo | [FASE_05.md](FASE_05.md) |
| F — Fase 4 | ✅ | `646a6a5` | Oráculo v2, sin plantillas: **llama3.1 8B 0/10 · qwen2.5-coder 7B 1/10 · llama3.2 3B 0/10**. Muestra demasiado chica para concluir (difieren en 1 pregunta). VRAM 5.80 / 5.12 / 3.09 GB. Causa de la latencia medida: 1.ª evaluación del esquema y generación de tokens (no la caché) | [FASE_04.md](FASE_04.md) |
| G — Fase 6 | ✅ | `a6b75fb` (código) · `226a928` | N intentos reales (antes máx. 2 fijos); juez-LLM separado. N=3: 1/10 | [FASE_06.md](FASE_06.md) |
| G — Fase 9 | ✅ | `9a0b0ad` | Corte en el primer acierto (demostrado). ⚠ El caso real "falla→acierta" fue un **falso acierto por tolerancia** (3.01 vs 3.04, D-17) | [FASE_09.md](FASE_09.md) |
| G — Fase 7 | ✅ | `266439f` | Pistas sin cifras + guarda; **0 fugas en 94 pistas reales**. Con/sin pista: 1/10 vs 0/10, **0 recuperaciones** tras rechazo en todas las configuraciones | [FASE_07.md](FASE_07.md) |
| G — Fase 8 | ✅ | `8d85a08` | Veredicto = árbitro. Juez vs árbitro: 9/10 coinciden, **1 falso acierto**, 0 falsos rechazos (10 intentos) | [FASE_08.md](FASE_08.md) |
| H — Fase 10 | ✅ | `3223ace` | Juez de sensatez en el chat (texto: "no comprueba la cifra"); bitácora JSON propia con límites. Real: registra e inyecta; el efecto de evitar el error solo está probado con el cliente guionado | [FASE_10.md](FASE_10.md) |
| I — Fase 11 | ✅ | `d0fb8f4` | Carga del dashboard en frío **≈193-221 s → ≈25-30 s**; PDF bajo demanda; HTML escapado; títulos H1/H3; detalle técnico visible con Ollama caído (revisado en el navegador). Los índices empeoran q01, así que no se aplicaron | [FASE_11.md](FASE_11.md) |
| J — Limpieza | ✅ | `fc870c4` | P2 resuelto (script y módulo); 10 archivos del gimnasio → `legacy/gimnasio/` con `git mv`; 49/49 pruebas y ambas páginas cargan sin excepciones | [FASE_J_LIMPIEZA.md](FASE_J_LIMPIEZA.md) |

## Etapa 2 — Mejorar la precisión sin inflar las cifras (2026-10-11)

| Paso | Estado | Commit | Cifras reales | Doc |
|---|---|---|---|---|
| 0 — Entorno tras reinicio | ✅ | `eee86bb` | Ollama arranca solo; llama3.1 **38.5 tok/s**, qwen 19.0, llama3.2 73.5 (ctx 8192), los 3 al 100 % en GPU | [E2_PASO_0.md](E2_PASO_0.md) |
| 1 — Tolerancia 0.006 + recalificación offline | ✅ | `d21de4b` | 13 corridas recalificadas: solo cambian los dos `3.01` de la Fase 9 (dirigida r1 1/3→0/3; r3 2/3→1/3) | [E2_PASO_1.md](E2_PASO_1.md) |
| 2 — Oráculo v3: 30 preguntas, DESARROLLO 20 / PRUEBA 10 | ✅ | `b2e99ec` | SQL **30/30**, pandas **30/30**; n04 con criterio completo (13); split por sorteo (semilla 20261011); blindaje de PRUEBA con 8 pruebas; suite 57/57 | [E2_PASO_2.md](E2_PASO_2.md) |
| 3 — Mejoras una a una (A/B ×3, solo DESARROLLO) | ✅ | `1a1c39f` | llama3.1: base **3/3/3** → sin clasificador **5/5/5** → + `vw_pedidos_validos` **8/9/8** (Wilson 30.1–54.3 %). c, d1, d2 y d3 revertidas (5, 5, 7, 4.67). (d) causaba 25/45 fallos. qwen 8/8/9 (empate), llama3.2 3/2/3 → modelo sin cambio | [E2_PASO_3.md](E2_PASO_3.md) |
| 4 — Dashboard y mensajes | ✅ | `02f3dba` | q01 **31.4 → 10.4 s**, 4 tablas = pandas desde los CSV; negativa del modelo ≠ rechazo de seguridad (verificado en el chat real); fecha sin truncar a 1366 px; bitácora diagnostica SELECT sin FROM: con el modelo real evita repetirlo (12/12 → 0/6 intentos) pero no lo vuelve correcto (0/6 y 0/6); 64/64 pruebas | [E2_PASO_4.md](E2_PASO_4.md) |
| 5 — PRUEBA una sola vez (config. congelada `02f3dba`) | ✅ | `d24511d` | DESARROLLO **10/7/9** (media 8.67, 43.3 %, Wilson 31.6–55.9) · PRUEBA **8/8/8** (80.0 %, Wilson 62.7–90.5). Sin señal de sobreajuste; porcentajes en PRUEBA 3/9 (x06 y x20, denominador) = problema abierto. Modelo sin cambio | [E2_PASO_5.md](E2_PASO_5.md) · [INFORME_FINAL_2.md](INFORME_FINAL_2.md) |
| Cierre | ✅ | (este commit) | Limitaciones en INFORME_FINAL_2 §6 (PRUEBA sobre 10 preguntas: Wilson 49.0–94.3 %); RESUMEN_PARA_ENTREGA; README reproducible verificado en un clon limpio: 2 fallos del README corregidos (oráculo, UTF-8), DESARROLLO reproducido 6/8/7; 64/64 | [CIERRE_REPRODUCIBILIDAD.md](CIERRE_REPRODUCIBILIDAD.md) |

## Pendientes / avisos
- ~~Velocidad de llama3.1 y app de bandeja de Ollama~~: resueltos tras reiniciar (Paso 0 de la etapa 2).
- Una evaluación completa de 10 preguntas tarda entre 3.5 y 8 min (depende de reintentos y de consultas lentas).
- Cifra honesta actual (oráculo v3, llama3.1, `02f3dba`): DESARROLLO media 8.67/20 (7–10), PRUEBA 8/10 (8–8). Las cifras de la etapa 1 (2/10) eran sobre otro oráculo.

## Etapa 3 — Mejorar el contexto del modelo (2026-10-11)

| Paso | Estado | Commit | Cifras reales | Doc |
|---|---|---|---|---|
| 1 — Auditoría del contexto (sin cambios) | ✅ | (este commit) | System prompt **13,084 caracteres / 3,340 tokens**, idéntico para toda pregunta; notas 38 % de los tokens. Tablas base sin descripción; sin glosario (porcentaje, retraso, ticket, top N); 18 de 54 columnas ambiguas (14 sin explicación); ~26 % describe objetos que el modelo casi no usa; 2 notas derivadas del oráculo (n05, q5 v1) | [CONTEXTO_ACTUAL.md](CONTEXTO_ACTUAL.md) |
