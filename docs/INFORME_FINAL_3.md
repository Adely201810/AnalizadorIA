# Informe final — Etapa 3: mejorar el contexto del modelo

Fecha: 2026-10-12 · Rama `main` (sin push) · Configuración congelada: **`740066a`** + `TEXT2SQL_AUTOCONSISTENCIA=5`, T = 0.3 · Pruebas: **78/78**
Detalle por paso: [CONTEXTO_ACTUAL.md](CONTEXTO_ACTUAL.md) (Paso 1) · [E3_PASO_2.md](E3_PASO_2.md) · [E3_PASO_3.md](E3_PASO_3.md) · [E3_PASO_4.md](E3_PASO_4.md) · decisiones D-27 a D-31 en [DECISIONES.md](DECISIONES.md).

## 1. Resultado en una frase
**Ninguna mejora de contexto ayudó:** E1-E6 empeoraron o quedaron en ruido. Lo único que subió la precisión fue la **autoconsistencia (E7)**, que vota entre 5 SQL generados: 13.33 → 15.33 de 30 en DESARROLLO, a cambio de ~3x de latencia. En PRUEBA_2, evaluado una sola vez, la configuración final da **13.0/20 con llama3.1 y 12.67/20 con qwen2.5-coder**.

## 2. Contexto antes y después

| | Caracteres | Tokens (llama3.1 / qwen2.5-coder) | Contenido |
|---|---|---|---|
| Antes (fin de la etapa 2, auditado) | 13,084 | 3,340 / — | esquema, 7 vistas, columnas de unión, 21 notas, 10 few-shot, reglas |
| **Después (configuración final)** | **12,984** | **3,329 / 3,333** | igual, pero sin las 2 notas que calcaban preguntas del oráculo (D-27) |

- El contexto final es **el mismo para cualquier pregunta** y apenas cambió (−100 caracteres). Lo que cambió es **cómo se usa**: con E7 se envía 5 veces por pregunta (×5 tokens procesados; la caché del prefijo de Ollama amortigua parte).
- Los experimentos movieron el prompt medio entre **9,088** (E2, esquema reducido) y **15,155** caracteres (E3, descripciones), **sin relación monótona** con la precisión (tabla en E3_PASO_3.md).

## 3. Experimentos (DESARROLLO 30, T = 0.3, 3 repeticiones, regla D-23, acumulativos)

| | Qué se probó | Fallos con esa causa (antes) | Aciertos | Media | Prompt medio | Latencia | Decisión | Motivo |
|---|---|---|---|---|---|---|---|---|
| Base | config. etapa 2 + D-27 | — | 13, 14, 13 | 13.33 | 13,148 | 13.1 s | — | — |
| E1 | glosario de negocio dinámico (14 términos) | 31 | 10, 10, 12 | 10.67 | 14,231 | 19.7 s | revertido | empeoró 2.7 |
| E2 | esquema por pregunta | 22 | 15, 14, 12 | 13.67 | **9,088** | 19.8 s | revertido | +0.33 (ruido); prompt −31 % sin perder precisión |
| E3 | 21 descripciones de columnas ambiguas | 25 | 12, 13, 16 | 13.67 | 15,155 | 16.3 s | revertido | +0.33, mínimo 12 |
| E4 | 3 vistas de negocio genéricas | 19 | 14, 10, 13 | 12.33 | 14,582 | 16.6 s | revertido | empeoró |
| E5 | few-shot dinámico (3 de 32, TF-IDF) | 50 | 8, 11, 6 | 8.33 | 11,786 | 32.2 s | revertido | el peor: ejemplos poco parecidos por diseño (disjuntos) |
| E6 | plan en palabras antes del SQL | 31 | 12, 8, 8 | 9.33 | 13,316 | 17.0 s | revertido | empeoró 4 |
| E7 k=3 | autoconsistencia, 3 candidatos | 47 | 15, 14, 16 | 15.00 | 13,148 | 26.5 s | pasa D-23 | — |
| **E7 k=5** | autoconsistencia, 5 candidatos | 47 | **17, 15, 14** | **15.33** | 13,148 | **38.0 s** | **conservado** | +2.0; elegido sobre k=3 por la regla fijada antes (mayor media) |
| Modelo | qwen2.5-coder + E7 k=5 | — | 20, 16, 19 | 18.33 | 13,148 | 50.5 s | evaluado en PRUEBA_2 | cumple D-23 frente a llama3.1 |

## 4. Cifras finales

| Conjunto | llama3.1 8B + E7 k=5 | qwen2.5-coder 7B + E7 k=5 |
|---|---|---|
| DESARROLLO (30) | 17, 15, 14 → media 15.33 (51.1 %); por pregunta 33.2–66.8 % | 20, 16, 19 → media 18.33 (61.1 %); por pregunta 45.5–78.1 % |
| DESARROLLO, solo preguntas nuevas (20) | 70.0 % (48.1–85.5 %) | 73.3 % (53.1–88.8 %) |
| **PRUEBA_2 (20, una sola vez)** | **14, 13, 12 → media 13.0 (65.0 %)** | **11, 14, 13 → media 12.67 (63.3 %)** |
| PRUEBA_2, intervalo sobre las 20 **preguntas** | **43.3–81.9 %** | **38.7–78.1 %** |
| PRUEBA_2 por tipo (respuestas) | simple 12/12 · porcentaje 7/15 · pedido válido 8/12 · ranking 9/9 · varios pasos 3/12 | simple 9/12 · porcentaje 10/15 · pedido válido 6/12 · ranking 7/9 · varios pasos 6/12 |

### Limitaciones de estas cifras
1. **DESARROLLO y PRUEBA_2 no son comparables en total:** las 10 necesidades difíciles están solo en DESARROLLO. La comparación justa es con las preguntas nuevas de DESARROLLO (70.0 % frente a 65.0 % con llama3.1).
2. **Muestra chica:** el intervalo sobre las 20 preguntas de PRUEBA_2 va de ~40 % a ~80 %. Los dos modelos no se distinguen en PRUEBA_2.
3. **No hay cifra de mejora en PRUEBA_2:** la base (sin E7) no se evaluó ahí. El +2 de E7 es solo de DESARROLLO.
4. **Temperatura 0.3** en toda la evaluación (indicación del usuario). A 0.1, la temperatura del chat, la base daba 16.33 frente a 13.33. Las cifras absolutas subestiman el chat, y E7 necesita temperatura > 0.1 para tener efecto.
5. **El chat no usa la configuración evaluada:** la autoconsistencia no está activada por defecto (D-30), así que las cifras de E7 describen una configuración opcional.
6. **PRUEBA_2 la escribió el mismo agente que diseñó las mejoras.** Mitigaciones: se congeló antes de diseñar E1-E7, hay pruebas de disyunción sobre las 50 preguntas y se evaluó una sola vez. Aun así, no es un conjunto escrito por un tercero.
7. **PRUEBA_2 ya fue vista:** para medir mejoras futuras sin sesgo hace falta un conjunto nuevo.

## 5. ¿Sobreajuste?
- **llama3.1:** PRUEBA_2 (65.0 %) queda 5 puntos por debajo de las preguntas comparables de DESARROLLO (70.0 %), dentro del ruido. **No es una caída notable.**
- **Elección del modelo:** la ventaja de qwen en DESARROLLO (+3) **no se replicó** en PRUEBA_2 (−0.33). Es la señal de sobreajuste por selección más clara de la etapa, porque esa ventaja venía de las necesidades, que PRUEBA_2 no tiene.
- **D-27 destapó una contaminación previa:** al quitar una nota que calcaba la pregunta n05, esa pregunta pasó de 3/3 a 0/3. Parte de la cifra de la etapa 2 estaba inflada por esa nota.

## 6. Decisiones que tomé por mi cuenta (para revisar)
1. **D-27:** reescribí 2 notas del contexto que calcaban preguntas del oráculo (n05 y q5 de la v1), **antes** de medir la nueva base. Así, n05 dejó de acertar.
2. **D-28:** temperatura 0.3 como pediste, aunque cuesta ~3 aciertos frente a 0.1 y casi no cambia el resultado entre repeticiones (es mixto en 2 de 30 preguntas).
3. **D-28:** PRUEBA_2 con 20 preguntas propias (simple 4, porcentaje 5, pedido válido 4, ranking 3, varios pasos 4). Cambié una antes de congelarla porque chocaba con un few-shot.
4. **D-29:** diseño de E1-E7. Descarté una columna de "métodos de pago" en una vista y una pista del día de la semana en el glosario porque venían de conocer PRUEBA_2.
5. **E7 k=5 sobre k=3:** por la regla fijada (mayor media; 15.33 frente a 15.00). La diferencia es ruido, y k=3 es un 30 % más rápido.
6. **D-30:** la autoconsistencia **no** se activa en el chat por defecto (multiplica la latencia por ~3 y necesita temperatura > 0.1). Es decisión tuya.
7. **D-31: el modelo por defecto pasa a qwen2.5-coder** por la regla establecida (mejor en DESARROLLO y no peor en PRUEBA_2, umbral −1 fijado antes). **Revertir:** `OLLAMA_MODEL=llama3.1:8b-instruct-q4_K_M`. La regla se cumple, pero la ventaja no se replicó en PRUEBA_2 y qwen es más lento.

## 7. Problemas abiertos
- **Los porcentajes siguen siendo el punto débil** (llama3.1 7/15 en PRUEBA_2; p2_06 y p2_07 fallan siempre). Ni la regla de denominador (etapa 2) ni el glosario (E1) lo arreglaron.
- **Las 10 necesidades del dashboard:** 4/30 con llama3.1 + E7 y 11/30 con qwen + E7. El chat sigue sin responder bien las preguntas de varios pasos; para ellas, el dashboard es la fuente fiable.
- **Más contexto empeora a un 8B:** los 7 intentos de añadir texto al prompt (c, d1 y d3 en la etapa 2; E1, E3, E4 y E6 aquí) empeoraron o fueron neutros. Quitar o reemplazar texto (d2, E2, E5) tampoco ayudó. Lo que funcionó cambia la estructura (vista de pedidos válidos) o el procedimiento (votación).
- **La votación como señal de confianza:** con 5/5 votos acierta 20 de 22; con ≤2 votos, 10 de 38. Podría usarse para avisar en el chat. No está implementado ni medido en PRUEBA_2.
- **E2 reduce el prompt un 31 % sin perder precisión**, pero sube la latencia por la caché; podría servir con modelos de contexto corto.
- **La heurística de causas es aproximada** (`eval/causas.py`, `DETALLE` del orquestador).
- **Hace falta un conjunto de prueba nuevo**, idealmente escrito por un tercero, para futuras mejoras.
