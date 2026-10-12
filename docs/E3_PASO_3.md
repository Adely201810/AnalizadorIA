# Etapa 3 · Paso 3 — Experimentos de contexto E1-E7 (solo DESARROLLO)

Fecha: 2026-10-11 · Estado: **COMPLETO** · Código: `d847cca` · DESARROLLO = 30 preguntas · T = 0.3 · 3 repeticiones por experimento · regla D-23.
Orquestador: `python -m eval.ab_acumulativo_e3` → `eval/baselines/etapa3/acumulativo.json` (salida en `logs/e3_acumulativo.log`, de 18:18 a 23:18).

## Método
- Cada experimento está detrás de un interruptor **apagado por defecto** (`llm/contexto_e3.py`, `llm/schema_context.py`). Con todos apagados, el system prompt es idéntico byte a byte al del Paso 2. Diseño en D-29.
- Experimentos **acumulativos**: cada uno se prueba encima de lo conservado. Como E1-E6 se revirtieron, todos terminaron comparados con la base. E7 se probó con k=3 y con k=5, ambos contra la misma configuración.
- **Antes** de cada experimento se midió cuántos fallos de la configuración vigente tenían la causa que ataca (heurística, ver `DETALLE` en el orquestador).
- **Regla D-23:** se conserva si la media sube al menos 1 **y** el mínimo nuevo es ≥ la media anterior.
- **Disyunción:** el glosario (14 términos) y el banco de ejemplos (32) se escribieron sin mirar el oráculo y se validaron contra las 50 preguntas (texto < 0.25, SQL < 0.5 y ningún fragmento de 4 palabras). Los primeros borradores tenían 7 + 13 choques, que se reformularon antes de cualquier corrida.

## Resultados

| Experimento | Fallos con la causa objetivo (antes) | Aciertos r1, r2, r3 (de 30) | Media | Mín. | Wilson sobre preguntas | Prompt medio (caracteres) | Latencia media | Duración | Decisión |
|---|---|---|---|---|---|---|---|---|---|
| **Base** (Paso 2) | — | 13, 14, 13 | 13.33 | 13 | 30.2–63.9 % | 13,148 | 13.08 s | — | punto de partida |
| E1 glosario dinámico | 31 (semánticos con término del glosario) | 10, 10, 12 | 10.67 | 10 | 19.2–51.2 % | 14,231 | 19.69 s | 32 min | **REVERTIDO** |
| E2 esquema por pregunta | 22 (tabla/columna inexistente o mal ubicada) | 15, 14, 12 | 13.67 | 12 | 30.2–63.9 % | **9,088** | 19.81 s | 32 min | **REVERTIDO** (+0.33) |
| E3 descripción de columnas | 25 (SQL usa una columna ambigua) | 12, 13, 16 | 13.67 | 12 | 30.2–63.9 % | 15,155 | 16.30 s | 27 min | **REVERTIDO** (+0.33) |
| E4 vistas de negocio | 19 (multiplicidad o varios pasos) | 14, 10, 13 | 12.33 | 10 | 24.6–57.7 % | 14,582 | 16.57 s | 28 min | **REVERTIDO** |
| E5 few-shot dinámico (3 de 32) | 50 (todos) | 8, 11, 6 | 8.33 | 6 | 11.8–40.9 % | 11,786 | 32.20 s | 51 min | **REVERTIDO** |
| E6 plan antes del SQL | 31 (semánticos) | 12, 8, 8 | 9.33 | 8 | 11.8–40.9 % | 13,316 | 17.02 s | 28 min | **REVERTIDO** |
| E7 autoconsistencia, k=3 | 47 (preguntas con SQL inestable) | 15, 14, 16 | 15.00 | 14 | 33.2–66.8 % | 13,148 | 26.48 s | 42 min | pasa D-23 |
| **E7 autoconsistencia, k=5** | 47 | **17, 15, 14** | **15.33** | 14 | 33.2–66.8 % | 13,148 | **38.03 s** | ~63 min | **CONSERVADO** |

Wilson sobre preguntas: una pregunta cuenta como acertada si acierta en al menos 2 de 3 repeticiones (30 preguntas).

**Configuración final del Paso 3:** la base (sin clasificador, con `vw_pedidos_validos`, D-27) **+ `TEXT2SQL_AUTOCONSISTENCIA=5`**, a T = 0.3.

## Relación tamaño del prompt / precisión

| Prompt medio | Experimento | Media |
|---|---|---|
| 9,088 | E2 (esquema reducido) | 13.67 |
| 11,786 | E5 (3 ejemplos dinámicos en lugar de 10 fijos) | 8.33 |
| 13,148 | base, E7 | 13.33 / 15.00 / 15.33 |
| 13,316 | E6 (regla de plan) | 9.33 |
| 14,231 | E1 (+ glosario) | 10.67 |
| 14,582 | E4 (+ 3 vistas) | 12.33 |
| 15,155 | E3 (+ 21 descripciones) | 13.67 |

- **No hay relación monótona.** Reducir el esquema un 31 % (E2) no cambió la precisión (+0.33, ruido), así que el tamaño en sí no era el problema. Añadir texto **específico de la pregunta** (E1 glosario, E5 ejemplos, E6 plan) **empeoró** entre 2.7 y 5 aciertos. Añadir texto estático (E3, E4) quedó neutro o peor.
- Es el mismo patrón de la etapa 2 (c, d1, d2 y d3 empeoraron): **con un modelo de 8B, lo que ayuda no es más contexto sino otra forma de usar el modelo** (la vista en la etapa 2; votar entre varias generaciones aquí).

## Lectura de E7
- Gana sobre todo en preguntas **inestables**: n05 (0 → 1/3), n07 (2 → 3), x03 (0 → 1), x09 (2 → 3), x10 (0 → 1/2), x17 (0 → 2). También pierde en algunas que antes acertaban siempre: x02 (3 → 1/2) y x14 (3 → 2 con k=3).
- **El número de votos funciona como señal de confianza** (k=5, 90 respuestas):

| Votos del ganador | Respuestas | Aciertos |
|---|---|---|
| 5 de 5 | 22 | 20 |
| 4 | 17 | 11 |
| 3 | 13 | 5 |
| 2 | 11 | 2 |
| 1 | 14 | 5 |
| 0 (ningún candidato corrió con filas) | 13 | 3 |

  En el chat podría usarse para avisar de baja confianza. **No se usó para ajustar nada**; queda como idea abierta.
- **Costo:** la latencia se multiplica por 2 con k=3 (26.5 s) y por 2.9 con k=5 (38.0 s).
- **k=5 frente a k=3:** la diferencia (15.33 frente a 15.00) es ruido; el intervalo por pregunta es idéntico. Se aplicó la regla fijada **antes** de ver los resultados ("mayor media; empate exacto → k=3") y ganó k=5. **Para revisión:** si la latencia importa, k=3 da prácticamente lo mismo un 30 % más rápido.
- **Dependencia de la temperatura:** E7 necesita diversidad entre candidatos. A T = 0.1, la temperatura del chat, los 5 candidatos serían casi iguales y el efecto probablemente menor (no medido).

## Lectura de los demás
- **E1:** las definiciones genéricas (porcentaje, retraso…) no corrigieron los fallos semánticos (31 antes) y añadieron 1,100 caracteres por pregunta. Empeoró preguntas que antes acertaban.
- **E2:** baja el prompt a 9,088 caracteres (-31 %) sin perder precisión, pero sube la latencia (19.8 s), probablemente porque el system cambia en cada pregunta y se pierde la caché del prefijo. No cumple D-23.
- **E3:** media +0.33 con mayor varianza (12-16); no cumple D-23.
- **E4:** las vistas nuevas no redujeron los fallos de multiplicidad; una repetición bajó a 10.
- **E5:** es el peor (8.33) y el más lento (32 s). Los ejemplos elegidos se parecen poco a la pregunta (Jaccard de texto medio 0.144, máximo 0.222, medido sobre las 30 de DESARROLLO). Es **estructural**: el banco tiene que ser disjunto del oráculo, así que no puede contener ejemplos muy parecidos. Además, quitar los 10 ejemplos fijos perjudicó.
- **E6:** el plan en palabras no mejoró el SQL (9.33). No faltaron tokens (0 de 125 intentos sin SQL), pero en 6 de 125 intentos el texto del plan quedó dentro del SQL extraído y la consulta no corrió.

## Comparación de modelos con la configuración final
Configuración: base + `TEXT2SQL_AUTOCONSISTENCIA=5`, T = 0.3, DESARROLLO 30, 3 repeticiones (`logs/e3_qwen.log`, de 23:19 a 00:37).

| Modelo | Aciertos r1, r2, r3 | Media | Mín.–máx. | Wilson sobre respuestas | Wilson sobre preguntas | Latencia media |
|---|---|---|---|---|---|---|
| llama3.1 8B (por defecto) | 17, 15, 14 | 15.33 | 14–17 | 41.0–61.2 % | 33.2–66.8 % | 38.03 s |
| **qwen2.5-coder 7B** | **20, 16, 19** | **18.33** | 16–20 | 50.8–70.5 % | 45.5–78.1 % | **50.47 s** |

- **qwen cumple D-23 frente a llama3.1:** media +3.0 y mínimo 16 ≥ 15.33. En la etapa 2, sin autoconsistencia y con 20 preguntas, habían empatado (8.33 y 8.33).
- Pregunta por pregunta, qwen acierta más veces en 8 preguntas (n01, n03, n05, x02, x03, x06, x10, x17) y llama3.1 en 3 (x05, x12, x18).
- **Costo:** un 33 % más de latencia (50.5 s frente a 38.0 s por pregunta con k=5).
- **Decisión sobre el modelo por defecto:** según la regla establecida (mejor en DESARROLLO **y** no peor en PRUEBA_2), qwen se evalúa también en PRUEBA_2 en el Paso 4, **una sola vez**, junto con llama3.1. No se cambia nada antes de eso.
