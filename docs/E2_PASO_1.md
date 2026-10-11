# Etapa 2 · Paso 1 — Tolerancia de porcentajes 0.006 y recalificación offline

Fecha: 2026-10-11 · Estado: **COMPLETO**

## Cambio
`eval/comparador.py`: `TOL_PORCENTAJE = 0.05` → **`0.006`** (decisión del usuario, D-17). Así solo se admiten diferencias de redondeo a 2 decimales. Pruebas nuevas en `tests/test_comparador.py`: `3.01` vs `3.04` se rechaza y `3.0453` vs `3.04` se acepta. `python -m unittest tests.test_comparador` → `Ran 20 tests … OK`.

## Recalificación de todas las corridas guardadas, sin el modelo (`python -m eval.recalificar_todo`)
Se reejecuta en solo lectura el SQL **final** que generó el modelo en cada pregunta y se compara con la referencia.
```
baseline_00_actual.json                          antes 6/10  ahora 3/10  cambios: q5_retraso_baja_calificacion ✅→❌ (valores: ninguna asignación de columnas del modelo coincide ), q6_metodo_pago_mayor_venta_promedio ✅→❌ (valores: ninguna asignación de columnas del modelo coincide ), q7_estado_mas_pedidos_entregados ✅→❌ (el SQL no ejecuta: no such column: customer_state)
baseline_01_endurecido.json                      antes 2/10  ahora 2/10  cambios: ninguno
fase2_clasificacion.json                         antes 2/10  ahora 2/10  cambios: ninguno
fase4_llama3_1_8b_instruct_q4_k_m_r1.json        antes 0/10  ahora 0/10  cambios: ninguno
fase4_llama3_2_3b_instruct_q4_k_m_r1.json        antes 0/10  ahora 0/10  cambios: ninguno
fase4_qwen2_5_coder_7b_instruct_q4_k_m_r1.json   antes 1/10  ahora 1/10  cambios: ninguno
fase6_n3_cadena_generico.json                    antes 1/10  ahora 1/10  cambios: ninguno
fase7_n3_cadena_sin_feedback.json                antes 0/10  ahora 0/10  cambios: ninguno
fase8_n3_cadena_juez.json                        antes 1/10  ahora 1/10  cambios: ninguno
fase9_dirigida_r1.json                           antes 1/3  ahora 0/3  cambios: n01_pct_clientes_recurrentes ✅→❌ (valores: ninguna asignación de columnas del modelo coincide )
fase9_dirigida_r2.json                           antes 0/3  ahora 0/3  cambios: ninguno
fase9_dirigida_r3.json                           antes 2/3  ahora 1/3  cambios: n01_pct_clientes_recurrentes ✅→❌ (valores: ninguna asignación de columnas del modelo coincide )
fase9_n3_cadena_temp08.json                      antes 1/10  ahora 1/10  cambios: ninguno
Guardado en C:\Users\alexp\OneDrive\Documentos\GitHub\AnalizadorIA\eval\baselines\recalificacion_tol0006.json
```

## Lectura
- **Los dos `3.01` (denominador equivocado: 2,888 / 96,096) pasan a rechazados**, como se esperaba: `fase9_dirigida_r1` 1/3 → 0/3 y `fase9_dirigida_r3` 2/3 → 1/3.
- Ninguna otra corrida cambia con la tolerancia nueva. baseline_00 aparece como 6 → 3 porque su "antes" es el evaluador original de la etapa 1 (los 3 falsos positivos ya conocidos: q5, q6, q7), no por la tolerancia.
- **Limitación:** en las corridas con cadena, un intento que antes se aceptaba ahora se habría rechazado y la cadena habría seguido; eso no se puede simular sin el modelo. Aquí solo se recalifica la respuesta final.
- Detalle por pregunta en `eval/baselines/recalificacion_tol0006.json`. Cifras actualizadas en `docs/INFORME_FINAL.md` y `docs/PROGRESO.md`.
