# Informe final — Plan B → J (AnalizadorIA, Text-to-SQL con LLM local)

Fecha: 2026-10-10 · Rama `main`, 20 commits sobre el inicial (`4cd4e36` → `fc870c4`) · Pruebas: **49/49 OK** (`python -m unittest discover -s tests -t .`)

Lectura rápida: [PROGRESO.md](PROGRESO.md) (estado por fase) · [DECISIONES.md](DECISIONES.md) (19 decisiones, cada una con cómo revertirla).

---

## 1. Las 11 fases: estado final y evidencia

| Fase | Estado final | Evidencia principal |
|---|---|---|
| 1. Esquema completo + reglas + few-shot | **COMPLETA** | Tipos en todas las columnas (antes faltaba INTEGER y se escribía `STRING`, que no es un tipo de SQLite); few-shot sin las métricas evaluadas; prueba de disyunción (`tests/test_fewshot_disjunto.py`). [FASE_01](FASE_01.md), [FASE_05](FASE_05.md) |
| 2. Distinguir fallo de ejecución vs semántico | **COMPLETA** | Cada intento clasificado como ok, ejecución, semántico, seguridad o infra; casos reales: `DELETE` generado por el modelo (seguridad) y Ollama detenido (infra). [FASE_02](FASE_02.md) |
| 3. Oráculo con comparación automática | **COMPLETA** | Árbitro determinista contra el resultado de la referencia, con tolerancias por tipo; el valor viejo de q2 ahora se rechaza (prueba). [FASE_03](FASE_03.md) |
| 4. Comparación de modelos | **COMPLETA, con salvedad** | 3 modelos, misma configuración, precisión, desglose de fallos, latencia y VRAM. Salvedad: llama3.1 genera ~8× más lento desde que se relanzó el servidor (ver §5). [FASE_04](FASE_04.md) |
| 5. 10 necesidades, 1 consulta, referencia verificada | **COMPLETA** | Oráculo v2 = fuente única del dashboard y de la evaluación; **SQL 10/10 y pandas 10/10**. [FASE_05](FASE_05.md) |
| 6. N iteraciones configurables + juez-LLM | **COMPLETA** | `n_intentos` real (antes `max_retries` permitía como máximo 2 intentos fijos); juez en `llm/juez.py`. [FASE_06](FASE_06.md) |
| 7. Feedback sin revelar la respuesta | **COMPLETA** | Pistas sin cifras + guarda; **0 fugas en 94 pistas reales**; prueba con un juez que filtra a propósito y es censurado. [FASE_07](FASE_07.md) |
| 8. Veredicto determinista; el juez solo explica | **COMPLETA** | El árbitro decide; juez vs árbitro: 9/10 coinciden, **1 falso acierto**, 0 falsos rechazos. [FASE_08](FASE_08.md) |
| 9. Cortar en el primer acierto | **COMPLETA, con hallazgo (resuelto en la etapa 2)** | Corte demostrado (determinista y con el modelo real). El caso real "falla → acierta" fue un **falso acierto por tolerancia** (3.01 vs 3.04). [FASE_09](FASE_09.md) |
| 10. Juez de sensatez en el chat + bitácora persistente | **COMPLETA, con límite** | La UI no lo presenta como verificación; bitácora JSON propia con límites. Con el modelo real: registra e inyecta; que **evite** el error solo está probado con el cliente guionado. [FASE_10](FASE_10.md) |
| 11. Legibilidad del dashboard | **COMPLETA** | Carga en frío **193-221 s → 25-30 s**; HTML escapado; títulos H1/H3; detalle técnico visible con Ollama caído. Revisado en el navegador. [FASE_11](FASE_11.md) |

Además: prerrequisito A ([ENTORNO](ENTORNO.md)), línea base B ([BASELINE](BASELINE.md)) y limpieza J ([FASE_J_LIMPIEZA](FASE_J_LIMPIEZA.md)).

---

## 2. Todas las cifras reales de precisión

### Oráculo v1 (10 preguntas sueltas; `eval/ground_truth_olist_v1.json`), llama3.1 8B
| Corrida | Evaluador | Configuración | Correctas |
|---|---|---|---|
| **baseline_00** | viejo (busca el valor en cualquier celda o texto, tolerancias por pregunta) | código original, plantillas activas | **6/10 (60 %)** |
| baseline_00 recalificado | árbitro nuevo, sobre el SQL que generó baseline_00 | — | **3/10** (los 3 que caen son falsos positivos: q5, q6, q7) |
| **baseline_01** | árbitro nuevo | sin plantillas, few-shot de la Fase 1 | **2/10 (20 %)** |
| fase2 | árbitro nuevo + clasificación | igual que baseline_01 | 2/10 (ok 2 · ejecución 2 · semántico 6) |

### Oráculo v2 (las 10 necesidades del dueño; fuente única), sin plantillas
| Corrida | Modelo | Configuración | Correctas | Clasificación final |
|---|---|---|---|---|
| benchmark | llama3.1 8B | N=2, sin cadena | **0/10** | ejecución 2 · semántico 8 |
| benchmark | **qwen2.5-coder 7B** | N=2, sin cadena | **1/10** | ok 1 · ejecución 3 · semántico 6 |
| benchmark | llama3.2 3B | N=2, sin cadena | **0/10** | ejecución 1 · semántico 9 |
| fase 7 (control) | llama3.1 8B | N=3, cadena, sin pista | 0/10 | ejecución 4 · semántico 6 |
| fase 6 | llama3.1 8B | N=3, cadena, pista genérica | 1/10 | ok 1 · ejecución 2 · semántico 7 |
| fase 8 | llama3.1 8B | N=3, cadena, pista del juez | 1/10 | ok 1 · ejecución 2 · semántico 7 |
| fase 9 | llama3.1 8B | N=3, cadena, genérica, temp 0.8 | 1/10 | ok 1 · ejecución 2 · semántico 7 |

**Recalificación con tolerancia de porcentajes 0.006 (etapa 2, D-17 resuelta; `logs/paso1_recalificacion.log`):** ninguna cifra de las tablas anteriores cambia, excepto las corridas dirigidas de la Fase 9: `fase9_dirigida_r1` pasa de 1/3 a **0/3** y `fase9_dirigida_r3` de 2/3 a **1/3**, porque los dos `3.01` (denominador equivocado) ahora se rechazan. Con la regla nueva, **en ninguna corrida real hay un acierto después de un rechazo**.

**Cómo leer la evolución:**
- **60 % → 30 %:** es el efecto de medir bien. Al recalificar el mismo SQL con el árbitro nuevo, la mitad de los "aciertos" de baseline_00 eran falsos positivos (p. ej. q7 contó como acierto el mensaje de error, porque "re**sp**onder" contiene "SP").
- **v1 → v2 no son comparables:** v2 cambia las preguntas por las 10 necesidades reales del dueño, que son más difíciles (porcentajes, umbrales, rankings), y quita los few-shot que se parecían a ellas.
- **La cifra honesta del sistema actual en las necesidades del negocio es 0-1 de 10.** Ninguna variante (N, pistas, juez, temperatura, modelo) recuperó una pregunta después de un rechazo; todos los aciertos llegaron al primer intento, y con 10 preguntas una diferencia de 1 es variación.
- **Dónde se pierde la precisión** (según el desglose): la mayoría de los fallos son **semánticos**. El SQL corre, pero (a) no aplica "pedido válido" (n06: 75,905 frente a 75,618), (b) usa otro denominador (n08, n01), o (c) el **clasificador descompone** preguntas de una sola consulta (3 de 10 con llama3.1, 8 de 10 con llama3.2).

---

## 3. Comparación de modelos (Fase 4)
| Modelo | Precisión v2 | Latencia media por pregunta | Generación | VRAM | Observación |
|---|---|---|---|---|---|
| llama3.1:8b-instruct-q4_K_M (actual) | 0/10 | 36.5 s* | 3.6 tok/s* | 5.80 GB | *velocidad anómala en esta sesión (36 tok/s a las 16:49) |
| qwen2.5-coder:7b-instruct-q4_K_M | 1/10 | 23.1 s | 18.5 tok/s | 5.12 GB | candidato; acertó n03 |
| llama3.2:3b-instruct-q4_K_M | 0/10 | 22.5 s | 65.3 tok/s | 3.09 GB | su clasificador descompone 8 de 10 preguntas |

**Recomendación:** probar **qwen2.5-coder:7b** como modelo por defecto (igual o mejor precisión, menos VRAM). **La muestra es demasiado chica para afirmar que sea más preciso** (1 pregunta de diferencia, 1 repetición). No se cambió el modelo por defecto.

---

## 4. Decisiones tomadas por mí (resumen de DECISIONES.md)
| # | Decisión | ¿Revisar? |
|---|---|---|
| D-03 | q4/n09 excluye explícitamente los productos sin categoría | baja |
| D-04 | Las preguntas dicen "sin contar pedidos cancelados o no disponibles" | baja |
| D-05 | Disyunción few-shot/oráculo medida con Jaccard (texto < 0.25, SQL < 0.5) | baja |
| D-06 | Tolerancias por tipo; "decimal" (días, calificaciones) ≤ 0.01 | media |
| D-07 | Estructura estricta (mismo nº de filas; transpuestos fallan); a q2/q6 se les añadió "y cuánto…" | media |
| D-08 | Límite de 60 s para el SQL del modelo (una consulta quedó colgada > 10 min) | baja |
| D-09 | Reglas de clasificación (0 filas = semántico; negativa del modelo = ejecución) | baja |
| D-10 | **Oráculo v2 = 10 necesidades del dashboard, reescritas a una consulta** (salen q1, q2, q6-q10 de v1) | **alta** |
| D-11 | **N4 simplificada (solo calificación < 3.5); N10 con ≥ 10 vendedores** | **alta** |
| D-12 | Few-shot sin las métricas del oráculo (se retiraron los de flete y Pareto) | media |
| D-13 | `n_intentos` = 2 por defecto en el chat | media |
| D-14 | Corte en el primer acierto solo donde hay árbitro (evaluación) | baja |
| D-15 | Guarda de pistas; los enteros < 10 no se protegen | baja |
| D-16 | Benchmark con 1 repetición, desde un worktree aislado | media |
| D-17 | Tolerancia de porcentajes → **0.006** (decidido por el usuario en la etapa 2) | resuelta |
| D-18 | Dashboard con selector de sección; no se aplicaron índices (empeoran q01) | media |
| D-19 | `legacy/gimnasio/`; documentos históricos sin editar | baja |

(D-01 y D-02 son tuyas: definición de pedido válido y umbral de q4.)

---

## 5. Problemas abiertos
1. **⚠ Ollama** (resuelto en la etapa 2 tras reiniciar: ver `docs/E2_PASO_0.md`). Tras detenerlo para la prueba de infra (Fase 2), la **app de bandeja ya no levanta su servidor** (`ollama server not ready after retries`). Desde entonces el servidor es un `ollama serve` lanzado por esta sesión: **al cerrarla, Ollama quedará detenido**. Probable solución: reiniciar Windows o abrir Ollama desde el menú Inicio (no verificado).
2. **⚠ Velocidad de llama3.1** (resuelto tras reiniciar: 38.5 tok/s; llama3.1 es ~2× más rápido que qwen, al revés de lo que parecía en la Fase 4): ~4 tok/s desde ~17:50, frente a 36 tok/s a las 16:49; qwen va a ~18 tok/s en el mismo estado. Descarté las DLL de Git Bash y la competencia por recursos. Las latencias de llama3.1 de las Fases 2, 4 y 6-11 **no son representativas**. Hay que volver a medir tras reiniciar.
3. ~~Tolerancia de porcentajes (D-17)~~: **resuelto** en la etapa 2 (0.006); los `3.01` se rechazan.
4. **Precisión baja en las necesidades reales (0-1/10).** Las palancas que señalan los datos: (a) no descomponer preguntas de una consulta (el clasificador causa 3-8 fallos seguros); (b) reforzar "pedido válido" (n06, n07, n08 son casi-aciertos por ese filtro); (c) probar otro modelo con más repeticiones.
5. **Muestras chicas:** 10 preguntas, 1 corrida por configuración, ningún intervalo de confianza. Para comparar modelos o configuraciones con seriedad hacen falta más preguntas (≥ 30) y ≥ 3 repeticiones.
6. **q01 del dashboard tarda ~32 s.** Los índices no ayudan; probablemente se recalculan CTE. Pendiente reescribir esa consulta.
7. **n09 (q4) discrimina poco** (todas las categorías ≈ 99.5 %): candidata a reemplazo (D-02).
8. **Bitácora:** la corrección de "columna inexistente" no diagnostica errores como un `SELECT` sin `FROM`. Su efecto de evitar errores no está demostrado con el modelo real.
9. **Juez:** mismo modelo que el generador (errores correlacionados); 1 falso acierto en 10. No debe decidir.
10. **Espacio en C:** quedan ~8.5 GB tras descargar 3 modelos; `pagefile.sys` llegó a 17.7 GB.
11. Menores: la métrica "Rango de fechas" se corta en el dashboard; ante una negativa del modelo, el usuario ve "no es una lectura segura y fue rechazada" (texto engañoso).

---

## 6. Qué haría falta para las fases futuras A, B y C (no se tocaron)
- **A — Agente.** Base reutilizable: `answer_question` ya expone N intentos, verificador, bitácora y juez como componentes. Faltaría: un bucle de herramientas (consultar esquema, ejecutar SQL de solo lectura, revisar resultados) con un presupuesto de pasos y tiempo; usar el límite de 60 s y el validador de seguridad como barreras; y **medirlo con el mismo oráculo v2 y el árbitro determinista**, para comparar contra 0-1/10. Antes conviene ampliar el oráculo (≥ 30 preguntas).
- **B — Túnel (acceso remoto).** Hoy Streamlit escucha en todas las interfaces (el log mostró `Network URL` y `External URL`). Faltaría: autenticación delante de la app, HTTPS, limitar la exposición (por ejemplo solo el chat, no el dashboard), límites de uso (cada pregunta ocupa la GPU 20-100 s) y decidir si la bitácora (`runtime/`) se comparte entre usuarios. La conexión de solo lectura y el validador ya protegen la base.
- **C — Respaldo local.** Qué respaldar: `db/olist.db` es reconstruible desde los CSV con el loader (34 s); los artefactos no reconstruibles son `runtime/bitacora_esquema.json`, `eval/baselines/` (ya en git), `logs/` (fuera de git) y los modelos de Ollama (~11.6 GB, se pueden volver a descargar). Faltaría: una tarea programada que copie `runtime/` y `logs/`, y una verificación de restauración (reconstruir la BD + `compute_ground_truth.py` debe dar `[OK]` 10/10).
