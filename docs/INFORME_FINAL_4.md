# Informe final — Etapa 4: juez con retroalimentación iterativa

Fecha: 2026-10-17 · Modelo qwen2.5-coder 7B (Q4_K_M) en Ollama 0.40.5, RX 6600 de 8 GB · Detalle completo en [INFORME_JUEZ.md](INFORME_JUEZ.md); decisiones D-32 a D-40 en [DECISIONES.md](DECISIONES.md).

## 1. Qué es el juez y cómo decide sin LLM
El juez es un ciclo de evaluación para 6 preguntas del catálogo: el control (total de pedidos) y las necesidades 2, 4, 5, 6 y 8 del dashboard. En cada intento:
1. El modelo genera un SQL.
2. El SQL se ejecuta en solo lectura, con los mismos validadores que el chat.
3. Un **veredicto determinista** compara el resultado con el criterio del caso: valor con tolerancia, fila que contiene las cifras clave, top-k o conjunto. Las tolerancias son las del árbitro del proyecto (conteo exacto, dinero ±0.1 %, porcentaje ±0.006).
4. Si falla, una **pista** describe el error real, la forma del resultado, los patrones de error detectados y los chequeos de sensatez.

Las referencias salen de las funciones `qNN()` del dashboard y dan cifras idénticas (6/6). Ningún LLM decide si una respuesta es correcta.

## 2. Garantías anti-fuga
- El modelo candidato solo ve la pregunta, su propio SQL anterior, el resumen de su propio resultado y las pistas.
- **Toda** pista pasa por un filtro determinista que la rechaza si contiene:
  - una cifra del resultado esperado, también redondeada (19.1 por 19.08);
  - un valor de texto esperado (por ejemplo, el nombre de una categoría);
  - 6 o más tokens seguidos del SQL de referencia.
- Una prueba automática corre el ciclo completo con un juez falso que intenta filtrar la respuesta y comprueba que nada de eso llega al prompt del candidato.
- En todas las corridas reales hubo 0 fugas.

## 3. Resultados (6 casos; acierto en el intento 1 → con juez, hasta 5 intentos)
| Ronda | Configuración | Acierto | Reintentos con SQL repetido | Fallos que no ejecutan / ejecutan con otro resultado* | s/intento |
|---|---|---|---|---|---|
| 1 | qwen, pistas de plantilla | 2/6 → 2/6 | 9/16 | 20 / 0 | 18.8 |
| 1 | qwen, pistas escritas por el LLM | 2/6 → 2/6 | 10/16 | 17 / 3 | 27.8 |
| 1 | llama3.1 8B, plantilla / LLM | 1/6 → 1/6 | 6/20 · 7/20 | 22 / 3 · 18 / 7 | 17.8 · 25.1 |
| 2 | A: anti-repetición (reintentos a T=0.5) | 2/6 → 2/6 | 3/16 | 18 / 2 | 31.5 |
| 2 | A + reparación con esquema real | 2/6 → 2/6 | 3/16 | 12 / 8 | 31.3 |
| 2 | B: A + reparación + pistas v2 | 2/6 → 2/6 | 4/16 | 13 / 7 | 35.5 |
| 2 | C: B + modo edición | 2/6 → 2/6 | 6/16 | 13 / 7 | 31.3 |

\* Fallos por validación o ejecución (la consulta no corre) / resultados incorrectos (corre, pero la cifra no coincide).

El esquema completo (5,294 tokens de system prompt frente a 3,333) tampoco ayudó: 9/42 aciertos en el intento 1 con los dos esquemas.

## 4. Por qué no rescató casos
- c01 y n05 aciertan siempre en el intento 1. **n02, n04, n06 y n08 nunca aciertan**, en ninguna de las 11 configuraciones medidas. Apunta a un límite del modelo de 7B con preguntas de varios pasos, no a falta de pistas.
- A T=0, el modelo repite su SQL. Re-muestrear rompe la repetición, pero el modelo produce otro SQL igual de equivocado.
- La reparación con el esquema real logra que más consultas **corran** (fallos que no ejecutan: 18 → 12). Después el modelo cae en el error lógico: en n06 suma sobre artículos × pagos y da 91.16 % en vez del valor esperado, aunque la pista nombra la causa.

## 5. Qué quedó en el chat
Del juez, el chat se lleva solo lo que **no necesita la respuesta correcta**. Se midió con la regla de siempre (D-23: DESARROLLO, 3 repeticiones, mismo modelo y temperatura):

| Configuración del chat | Aciertos en DESARROLLO (de 30) | Media | Mínimo |
|---|---|---|---|
| Antes (qwen2.5-coder, sin autoconsistencia) | 15, 13, 14 | 14.00 | 13 |
| **Con reparación con esquema + texto con umbrales** | 14, 15, 17 | **15.33** | 14 |

Cumple D-23 (+1.33 de media y un mínimo ≥ la media anterior), así que los dos quedan **encendidos por defecto**:
- **Reparación con esquema real** (`TEXT2SQL_REPARAR_ESQUEMA`): cuando una columna o tabla no existe, el reintento recibe las columnas reales y la ruta por tablas base. Apareció en 36 respuestas; 7 acabaron acertando.
- **Texto con umbrales** (`TEXT2SQL_TEXTO_UMBRALES`): la síntesis ya no se descarta por citar el umbral de la pregunta. Las síntesis descartadas bajaron de 8 a 3.

La ganancia es pequeña, los intervalos se solapan y no se confirmó en PRUEBA_2 (no se volvió a usar).

Además, el **modo evaluación con juez** está en la app (apagado por defecto) para demostrar el ciclo en vivo: muestra cada intento con su SQL, su error o resultado y su pista.

## 6. Limitaciones
- Solo 6 casos y una semilla por configuración en el ciclo: una diferencia de 1 caso no es señal.
- El juez conoce la respuesta correcta. Su acierto **no es comparable** con DESARROLLO ni con PRUEBA_2, y solo sirve para preguntas del catálogo.
- Los casos reutilizan necesidades del dashboard que ya estaban en DESARROLLO. PRUEBA_2 no se tocó.
- Los patrones de error y los chequeos de sensatez son heurísticos.
- Las cifras dependen de la versión de Ollama (0.40.5, que se actualizó sola durante el proyecto) y del hardware.
