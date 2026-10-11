# Etapa 2 · Paso 5 — Evaluación única de PRUEBA con la configuración congelada

Fecha: 2026-10-11 · Estado: **COMPLETO**

## Configuración congelada
- **Commit `02f3dba`**: árbol limpio al lanzar; el log `logs/e2_final.log` empieza con `commit 02f3dba`.
- llama3.1 8B (`llama3.1:8b-instruct-q4_K_M`), Ollama 0.40.3, sin plantillas, N=2 intentos.
- Clasificador **apagado** y `vw_pedidos_validos` **en el prompt** (valores por defecto del código, D-25).
- Mejoras c, d1, d2 y d3 apagadas.
- Comando por corrida: `python eval/run_eval.py --sin-plantillas --conjunto {desarrollo|prueba} --output eval/baselines/etapa2/final_{conjunto}_r{k}.json`
- PRUEBA se evaluó **una sola vez** (3 repeticiones seguidas) y no se ajustó nada después.

## Resultados (salida exacta)
```
commit 02f3dba
[desarrollo r1] exit 0 | === RESULTADO FINAL: correctas 10/20 (50.0%) | texto respaldado 16/20 | latencia media 15.33 s | origen {'llm'
[desarrollo r2] exit 0 | === RESULTADO FINAL: correctas 7/20 (35.0%) | texto respaldado 15/20 | latencia media 14.34 s | origen {'llm':
[desarrollo r3] exit 0 | === RESULTADO FINAL: correctas 9/20 (45.0%) | texto respaldado 16/20 | latencia media 14.46 s | origen {'llm':
[prueba r1] exit 0 | === RESULTADO FINAL: correctas 8/10 (80.0%) | texto respaldado 10/10 | latencia media 11.05 s | origen {'llm':
[prueba r2] exit 0 | === RESULTADO FINAL: correctas 8/10 (80.0%) | texto respaldado 10/10 | latencia media 11.13 s | origen {'llm':
[prueba r3] exit 0 | === RESULTADO FINAL: correctas 8/10 (80.0%) | texto respaldado 10/10 | latencia media 11.15 s | origen {'llm':
```

| Conjunto | Preguntas | Aciertos r1, r2, r3 | Media | Mín.–máx. | % | Wilson 95 % | Latencia media |
|---|---|---|---|---|---|---|---|
| DESARROLLO | 20 | 10, 7, 9 | 8.67 | 7–10 | 43.3 | 31.6–55.9 | 14.71 s |
| **PRUEBA** | 10 | 8, 8, 8 | 8 | 8–8 | **80.0** | 62.7–90.5 | 11.11 s |

El DESARROLLO de esta corrida (8.67) es coherente con el A/B del Paso 3 para la misma configuración (b: 8, 9, 8; media 8.33).

### Por pregunta (aciertos de 3)
- **PRUEBA:** x01 3, x06 **0**, x08 3, x09 3, x11 3, x12 3, x14 3, x15 3, x16 3, x20 **0**. Las dos que fallan son porcentajes, con fallo `semantico` y causa `c_denominador` en las 6 respuestas:
  - **x06:** cuenta pedidos con artículos y divide por todos los pedidos válidos, pero mezcla universos;
  - **x20:** usa `COUNT(DISTINCT rv.order_id)` (pedidos) como numerador de un porcentaje de **clientes**.
- **DESARROLLO:** n05 3, n07 3, x02 3, x04 3, x10 3, x18 3, x19 3, n09 2, x05 2, n01 1; las otras 10, 0/3.

### Por tipo de pregunta (aciertos de 3 corridas)

| Tipo | DESARROLLO | PRUEBA |
|---|---|---|
| 10 necesidades del dashboard | 9/30 | — (no hay ninguna) |
| Preguntas nuevas, en total | **17/30 (56.7 %)** | **24/30 (80.0 %)** |
| conteo | — | 6/6 |
| joins | 3/6 | 9/9 |
| porcentaje | 6/6 | **3/9** |
| promedio | 0/3 | 3/3 |
| ranking | 8/15 | 3/3 |

## ¿Sobreajuste?
**PRUEBA no salió peor que DESARROLLO** (80 % frente a 43.3 %), pero eso no basta para descartar sobreajuste, porque los conjuntos no son comparables (ver [INFORME_FINAL_2.md](INFORME_FINAL_2.md), sección 6). Además, las 3 repeticiones de PRUEBA fueron idénticas, así que el intervalo sobre las 10 preguntas es 49.0–94.3 %, no 62.7–90.5 %. Pero la comparación directa engaña:
- DESARROLLO contiene las 10 necesidades del dashboard (D-21: van todas a DESARROLLO por instrucción del usuario), que son las más difíciles (9/30). PRUEBA solo tiene preguntas nuevas.
- Comparando solo preguntas nuevas, la distancia se reduce: **56.7 % frente a 80.0 %**. El resto depende de qué tipos tocaron en el sorteo (PRUEBA tiene más conteos y joins simples, D-21).
- **Señal de alerta:** los porcentajes rinden 6/6 en DESARROLLO pero **3/9 en PRUEBA**. Las mejoras se eligieron con 2 preguntas de porcentaje de DESARROLLO (x02, x04), que ya acertaban. La regla de denominador (c), que apuntaba justo a este fallo, se **revirtió** porque empeoró DESARROLLO (6/3/6). Es un hueco real que DESARROLLO no podía revelar. No se ajustó nada tras verlo.
- No se evaluó la base (con clasificador, sin vista) sobre PRUEBA, así que **no hay cifra de "mejora" en PRUEBA**; solo la cifra absoluta de la configuración final.

## Modelo por defecto (D-25)
Se mantiene **llama3.1 8B**. qwen2.5-coder 7B empató en DESARROLLO (8/8/9 frente a 8/9/8) y la regla exige ser **mejor** en DESARROLLO antes de mirar PRUEBA, así que qwen no se evaluó en PRUEBA. **Cómo cambiarlo, si se decide:** `OLLAMA_MODEL=qwen2.5-coder:7b-instruct-q4_K_M` (variable que lee `llm/ollama_client.py`); revertir es quitar la variable.

Archivos: `eval/baselines/etapa2/final_{desarrollo,prueba}_r{1,2,3}.json` y `final_{desarrollo,prueba}_resumen.json`.
