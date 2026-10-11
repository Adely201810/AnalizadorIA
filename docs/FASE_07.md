# Fase 7 — Pista específica entre intentos, sin filtrar nunca el valor correcto

Fecha: 2026-10-10 · Estado: **COMPLETA** · Código: `a6b75fb` · Pruebas: `tests.test_cadena.TestPistasSinFugas` (4/4)

## Qué se implementó (`eval/pistas.py`, verificador en `eval/run_eval.py`)
Entre intentos, el modelo recibe **qué tipo de problema** hubo, nunca la respuesta:
- **Error real del motor/validador** (como antes): texto de SQLite o del validador, por ejemplo `no such column: customer_state` o `la consulta superó el límite de 60 s…`.
- **Rechazo del árbitro** (nuevo, con `--cadena`), según `--feedback`:
  - `ninguno`: "El resultado de la consulta no es correcto. Genera una consulta distinta." (control).
  - `generico`: el tipo de discrepancia **sin cifras**. El árbitro informa cuántas filas tiene la referencia, y eso **no** se pasa (`motivo_generico`).
  - `juez`: lo anterior más el **diagnóstico del enfoque** del juez-LLM, que no conoce la referencia.
- **Guarda** (`censurar`): antes de enviarse, la pista pasa por un filtro que reemplaza por `[valor omitido]` cualquier forma escrita de los valores de la referencia y sus derivados evidentes: 0-3 decimales, coma o punto, separadores de miles y escalas ×100 y ÷100 (D-15).

## Prueba automática: el prompt de reintento no contiene la referencia
`tests/test_cadena.py::TestPistasSinFugas`. El caso más fuerte usa un juez guionado que **filtra a propósito** la respuesta de n01 (3.04) en tres formas: `3.04`, `3,04 %` y `0.0304`. La prueba comprueba que:
- la guarda censuró algo;
- **ningún prompt de generación de SQL** (intento 1 y reintento) contiene ninguna forma del valor;
- el reintento sí recibió `[valor omitido]` y el diagnóstico.

La síntesis posterior al acierto sí contiene el resultado del propio modelo, como es legítimo, y la prueba la excluye a propósito.
```
test_censurar_no_toca_numeros_que_no_son_la_referencia ... ok
test_formas_de_valor ... ok
test_juez_que_filtra_el_valor_es_censurado_y_no_llega_al_prompt ... ok
test_motivo_con_numero_de_filas_no_se_filtra ... ok

----------------------------------------------------------------------
Ran 4 tests in 21.401s

OK
```
Durante el desarrollo, la primera versión de esta prueba marcó como "fuga" el prompt de **síntesis**, que contiene `3.04` porque es el resultado del propio modelo tras acertar. No era una fuga: la prueba se acotó a los prompts de generación de SQL. Otra prueba detectó que el verificador pedía opiniones al juez que nadie usaba (llamadas extra); se separó (D-14).

**Auditoría de las corridas reales** (todas las pistas de las corridas de las Fases 6-9):
```
pistas generadas: 58 | pistas enviadas al modelo (incluye errores del motor): 94 | con alguna forma del valor de referencia: 0
```
En las corridas reales la guarda **no tuvo que censurar nada**: el juez nunca conoce la referencia.

## Comparación con y sin feedback (oráculo v2, llama3.1 8B, N=3, cadena con árbitro)
| Configuración | Correctas | Aciertos en el 1.er intento | Recuperadas tras ≥1 rechazo | Intentos verificados rechazados | Preguntas descompuestas | Latencia media |
|---|---|---|---|---|---|---|
| benchmark (N=2, sin cadena) | 0/10 | 0 | 0 | 0 | 3 | 36.45 s |
| N=3, cadena, sin pista | 0/10 | 0 | 0 | 9 | 3 | 47.77 s |
| N=3, cadena, pista genérica | 1/10 | 1 | 0 | 11 | 3 | 44.24 s |
| N=3, cadena, pista del juez | 1/10 | 1 | 0 | 9 | 3 | 48.46 s |
| N=3, cadena, genérica, temp 0.8 | 1/10 | 1 | 0 | 10 | 3 | 42.86 s |

Por pregunta (✅ = correcta; entre paréntesis, intentos):
| Necesidad | benchmark | sin pista | genérica | juez | genérica t=0.8 |
|---|---|---|---|---|---|
| n01 | ❌ (2) | ❌ (3) | ❌ (3) | ❌ (3) | ✅ (1) |
| n02 | ❌ (2) | ❌ (2) | ❌ (2) | ❌ (2) | ❌ (2) |
| n03 | ❌ (1) | ❌ (3) | ❌ (3) | ❌ (3) | ❌ (3) |
| n04 | ❌ (2) | ❌ (3) | ❌ (3) | ❌ (3) | ❌ (3) |
| n05 | ❌ (3) | ❌ (3) | ❌ (3) | ❌ (3) | ❌ (4) |
| n06 | ❌ (1) | ❌ (3) | ❌ (3) | ❌ (3) | ❌ (3) |
| n07 | ❌ (1) | ❌ (3) | ✅ (1) | ✅ (1) | ❌ (3) |
| n08 | ❌ (1) | ❌ (3) | ❌ (3) | ❌ (3) | ❌ (3) |
| n09 | ❌ (2) | ❌ (3) | ❌ (3) | ❌ (3) | ❌ (3) |
| n10 | ❌ (3) | ❌ (4) | ❌ (4) | ❌ (4) | ❌ (6) |

## Lectura (sin ir más allá de los datos)
- **Con este modelo, ninguna configuración recuperó una pregunta tras un rechazo (0 en todas).** Todos los aciertos llegaron en el **primer** intento, así que la diferencia 0/10 frente a 1/10 entre "sin pista" y "con pista" **no se puede atribuir a la pista**: es la variación del primer intento (n07 falla en unas corridas y acierta en otras).
- Los diagnósticos del juez **suelen señalar el problema real**, por ejemplo n03 *"La consulta está calculando el porcentaje de pedidos, no de ingresos"* o n06 *"no especifica que se refiere a pedidos válidos"*. Aun así, el generador no logra corregirlo. El cuello de botella es la capacidad del modelo de 8B para rehacer la lógica, no la falta de información.
- El clasificador descompone 3 de 10 en todas las configuraciones; esas preguntas no pasan por la cadena.
- Muestra: 10 preguntas, 1 corrida por configuración. No se puede descartar un efecto pequeño de las pistas.
