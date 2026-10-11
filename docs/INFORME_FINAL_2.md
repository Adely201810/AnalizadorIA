# Informe final — Etapa 2: mejorar la precisión sin inflar las cifras

Fecha: 2026-10-11 · Rama `main` (sin push) · Configuración congelada: **`02f3dba`** · Pruebas: **64/64** (`python -m unittest discover -s tests -t .`)

## 1. Cifras, de principio a fin

**Aviso:** el oráculo cambió entre etapas (v1: 10 preguntas genéricas; v2: las 10 necesidades del dashboard; v3: 30 preguntas separadas en DESARROLLO 20 y PRUEBA 10). Las cifras de distintos oráculos **no son comparables entre sí**. Se listan para trazar la historia, no para restarlas.

| Momento | Oráculo | Configuración | Resultado |
|---|---|---|---|
| baseline_00 (etapa 1, evaluador original) | v1, 10 | con plantillas | 6/10 (con 3 falsos positivos) |
| baseline_00 recalificado (árbitro nuevo, tolerancia 0.006) | v1, 10 | — | **3/10** |
| baseline_01 (sin plantillas) | v1, 10 | con clasificador | 2/10; recalificado con 0.006: **2/10** |
| Fase 4 (sin plantillas) | v2, 10 necesidades | llama3.1 / qwen / llama3.2 | 0/10 · 1/10 · 0/10 |
| **Base de la etapa 2** | v3 DESARROLLO, 20 | con clasificador, N=2 | **3, 3, 3** (15.0 %; Wilson 8.1–26.1 %) |
| + sin clasificador (a) | v3 DESARROLLO | | 5, 5, 5 (25.0 %; 15.8–37.2 %) |
| + `vw_pedidos_validos` (b) | v3 DESARROLLO | | 8, 9, 8 (41.7 %; 30.1–54.3 %) |
| **Final, DESARROLLO** | v3 DESARROLLO, 20 | `02f3dba` | **10, 7, 9 → media 8.67, rango 7–10** (43.3 %; 31.6–55.9 %) |
| **Final, PRUEBA (una sola vez)** | v3 PRUEBA, 10 | `02f3dba` | **8, 8, 8 → media 8, rango 8–8** (80.0 %; 62.7–90.5 %) |

Todas las cifras de la etapa 2 son con llama3.1 8B, sin plantillas y con 3 repeticiones; los porcentajes de Wilson son sobre el total de respuestas. Detalle: [E2_PASO_3.md](E2_PASO_3.md) y [E2_PASO_5.md](E2_PASO_5.md).

## 2. Qué funcionó
- **Quitar el clasificador (a):** partía en sub-consultas 5 preguntas por corrida que se resolvían con una sola. 3/3/3 → 5/5/5.
- **Vista `vw_pedidos_validos` (b):** el modelo parte de una fila por pedido ya filtrada. 5/5/5 → 8/9/8. Es la mayor ganancia de la etapa.
- **Tolerancia de porcentajes 0.006:** eliminó los falsos aciertos tipo `3.01` frente a `3.04`.
- **Separar DESARROLLO y PRUEBA, con blindaje:** 8 pruebas impiden fugas de PRUEBA. Ya sirvió: rechazó 2 few-shot nuevos que se parecían a x16, que es de PRUEBA.
- **q01 del dashboard:** 31.4 s → 10.4 s, idéntico a pandas desde los CSV.
- **Mensajes del chat:** una negativa del modelo ya no se presenta como rechazo de seguridad (verificado en el chat real).
- **Bitácora:** diagnostica bien el SELECT sin FROM. Con el modelo real evita repetirlo (12/12 → 0/6 intentos), aunque no vuelve correcta la respuesta (0/6 → 0/6).

## 3. Qué no funcionó (medido y revertido)

| Mejora (sobre b) | Aciertos | Media frente a 8.33 |
|---|---|---|
| c: regla y ejemplos de denominador | 6, 3, 6 | 5 |
| d1: documentar el uso y las columnas de cada vista | 4, 5, 6 | 5 |
| d2: ocultar 3 vistas agregadas | 8, 6, 7 | 7 |
| d3: regla y ejemplo contra JOINs que multiplican filas | 5, 5, 4 | 4.67 |

Las cuatro añaden texto al prompt y todas empeoraron. Hipótesis, no demostrada: un modelo de 8B se dispersa con más reglas. (d) causaba 25 de los 45 fallos de DESARROLLO, pero ninguna de sus tres variantes lo arregló de forma consistente. **qwen2.5-coder 7B** empató exactamente con llama3.1 (8/8/9), acertando otras preguntas; **llama3.2 3B** dio 3/2/3.

## 4. Decisiones que tomé por mi cuenta (para revisar)
1. **D-23, regla de conservación:** una mejora se queda si la media sube al menos 1 y el mínimo nuevo es ≥ la media anterior; las mejoras se prueban acumulativamente, en el orden a → b → c → d1 → d2 → d3. El orden importa: c–d3 solo se probaron encima de b.
2. **D-25, clasificador apagado por defecto también en el chat.** Contrapartida: las preguntas compuestas de verdad ("X y además Y") ya no se parten. Revertir con `TEXT2SQL_CLASIFICADOR=1`.
3. **D-24, vista `vw_pedidos_validos` creada en `db/olist.db`.** Solo se recrearon vistas; las tablas no cambiaron (conteos antes y después guardados). Se reconstruye con el loader.
4. **D-25, modelo sin cambio:** un empate no es "mejor en DESARROLLO", así que qwen no se evaluó en PRUEBA.
5. **Ollama se actualizó solo (0.40.2 → 0.40.3) a mitad del A/B.** Repetí base y (a) en 0.40.3 y archivé las corridas anteriores en `eval/baselines/etapa2/ollama_0402/`, en lugar de mezclarlas.
6. **D-26:** tras una negativa del modelo se sigue cortando sin reintentar (solo cambió el texto), para no alterar lo medido.

## 5. Problemas abiertos
- **Porcentajes en PRUEBA: 3/9** (x06 y x20 fallan 3/3 por el denominador), frente a 6/6 en DESARROLLO. La mejora (c), dirigida a esto, empeoró DESARROLLO. DESARROLLO tiene pocas preguntas de porcentaje que fallen, así que no podía guiar esta mejora. **Siguiente paso posible:** ampliar DESARROLLO con preguntas de porcentaje nuevas antes de volver a probar (c). **No** se debe ajustar mirando x06 o x20.
- **Las 10 necesidades del dashboard siguen en 9/30** (n02, n03, n04, n06, n08 y n10 en 0/3). Son consultas de varios pasos que un 8B no resuelve en una sola sentencia.
- **La heurística de causas (`eval/causas.py`) está inflada** después de b: "no such column + vw_" cae en `d_vista_agregada` aunque la vista sea `vw_pedidos_validos`.
- **Muestra chica:** 20 preguntas en DESARROLLO y 10 en PRUEBA. Los intervalos de Wilson de configuraciones vecinas se solapan, y D-23 es una regla prudente, no un test estadístico.
- **Variación entre repeticiones:** la misma configuración dio 8/9/8 y luego 10/7/9.
- **Dashboard:** a 1024 px con la barra lateral se truncan todas las métricas (límite del layout de 5 columnas).
- No se evaluó la base sobre PRUEBA, así que no hay cifra de mejora en PRUEBA, solo la absoluta.

## 6. Commits de la etapa 2
`eee86bb` (Paso 0) · `d21de4b` (Paso 1) · `b2e99ec` (Paso 2) · `5cc911f`, `57b5902` (infraestructura del Paso 3) · `1a1c39f` (Paso 3) · `02f3dba` (Paso 4, **configuración congelada**) · Paso 5 + este informe: commit siguiente.
