| Modelo | Conjunto | Modo | Aciertos (por repetición) | Media | Mínimo | ¿Mejora D-23 vs Base? | Tokens de prompt SQL por pregunta | s/pregunta | Intentos medios | % preguntas con ejemplos |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.1 | casos_juez | base | 1, 2, 1 (de 6) | 1.33 | 1 | — | 6599.8 | 29.14 | 1.78 | 0 |
| llama3.1 | casos_juez | fewshot | 1, 1, 2 (de 6) | 1.33 | 1 | no | 7813.9 | 36.12 | 1.78 | 100 |
| llama3.1 | casos_juez | rag | 2, 3, 3 (de 6) | 2.67 | 2 | sí | 6228.4 | 35.7 | 1.39 | 100 |
| llama3.1 | casos_juez | harness | 3, 3, 3 (de 6) | 3 | 3 | sí | 13306.6 | 58.72 | 2.83 | 100 |
| llama3.1 | desarrollo | base | 16, 15, 13 (de 30) | 14.67 | 13 | — | 4574.9 | 14.69 | 1.32 | 0 |
| llama3.1 | desarrollo | fewshot | 9, 6, 5 (de 30) | 6.67 | 5 | no | 5159.2 | 23.44 | 1.24 | 100 |
| llama3.1 | desarrollo | rag | 10, 10, 11 (de 30) | 10.33 | 10 | no | 5281.0 | 26.05 | 1.26 | 100 |
| llama3.1 | desarrollo | harness | 10, 12, 12 (de 30) | 11.33 | 10 | no | 8592.7 | 39.33 | 2 | 100 |
| qwen2.5-coder | casos_juez | base | 1, 1, 1 (de 6) | 1 | 1 | — | 6140.6 | 42.07 | 1.67 | 0 |
| qwen2.5-coder | casos_juez | fewshot | 1, 1, 1 (de 6) | 1 | 1 | no | 7828.9 | 51.32 | 1.78 | 100 |
| qwen2.5-coder | casos_juez | rag | 3, 2, 2 (de 6) | 2.33 | 2 | sí | 6525.2 | 42.56 | 1.44 | 100 |
| qwen2.5-coder | casos_juez | harness | 3, 2, 2 (de 6) | 2.33 | 2 | sí | 14733.2 | 88.85 | 3.11 | 100 |
| qwen2.5-coder | desarrollo | base | 14, 15, 15 (de 30) | 14.67 | 14 | — | 5135.6 | 19.24 | 1.48 | 0 |
| qwen2.5-coder | desarrollo | fewshot | 14, 13, 16 (de 30) | 14.33 | 13 | no | 4820.3 | 23.34 | 1.17 | 100 |
| qwen2.5-coder | desarrollo | rag | 13, 14, 14 (de 30) | 13.67 | 13 | no | 4999.0 | 29.32 | 1.19 | 100 |
| qwen2.5-coder | desarrollo | harness | 15, 15, 14 (de 30) | 14.67 | 14 | no | 8020.3 | 43.91 | 1.86 | 100 |
