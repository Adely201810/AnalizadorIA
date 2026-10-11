# Fase 2 — Clasificación de cada intento: ok / ejecución / semántico / seguridad / infra

Fecha: 2026-10-10 · Estado: **COMPLETA** · Pruebas: `python -m unittest tests.test_clasificacion -v` (9/9 OK) + casos reales con el modelo

## Qué se implementó

**Pipeline** (`llm/text_to_sql.py`): cada intento queda registrado en `Text2SQLResult.intentos_detalle` (`{intento, sql, tipo, detalle}`). Se reutilizan las ramas que ya existían en `_generar_y_ejecutar_llm` (antes en `text_to_sql.py:464-491`); a cada una se le añadió una línea `registrar(...)`, sin cambiar el flujo:

| Rama existente | Tipo | Criterio |
|---|---|---|
| `OllamaError` al generar | `infra` | el modelo/servidor no respondió |
| SQL vacío | `ejecucion` | no hay SQL ejecutable |
| `SQLValidationError`: sentencia prohibida (`DELETE`, `;` interno…) | `seguridad` | `motivo="prohibida"` |
| `SQLValidationError`: texto en lugar de SQL (p. ej. una negativa) | `ejecucion` | `motivo="no_es_sql"` (nuevo, ver abajo) |
| `SQLQualityError`: tabla o columna inexistente | `ejecucion` | el SQL no correría |
| `SQLQualityError`: literal inventado o JOIN entre dominios | `semantico` | correría, pero respondería otra cosa |
| `sqlite3.Error` (incluye el límite de 60 s) | `ejecucion` | el SQL no corre |
| 0 filas | `semantico` | corre pero no devuelve nada |
| Ejecuta y devuelve filas | `ok` | (si además es correcto, lo decide el árbitro) |

`clasificar_excepcion()` concentra el mapeo. `SQLQualityError` y `SQLValidationError` (`llm/sql_guard.py`) tienen ahora un atributo `motivo` que indica qué comprobación falló.

**Evaluador** (`eval/run_eval.py: clasificar_intentos`): la clasificación final de la pregunta es `ok` si el árbitro la acepta. Si no, es el tipo del último intento, salvo que el último intento sea `ok` (corrió y devolvió filas pero el árbitro lo rechaza), que pasa a `semantico`. Una pregunta descompuesta en sub-consultas es `semantico`, igual que sus sub-consultas "ok". El resumen incluye `clasificacion_final` (por pregunta) y `clasificacion_por_intento`.

## Pruebas deterministas (cliente guionado, pipeline y SQLite reales)
```
test_descompuesta_en_subconsultas_es_semantico ... ok
test_ejecucion_columna_inexistente ... ok
test_ejecucion_error_de_sqlite ... ok
test_infra ... ok
test_negativa_en_texto_no_es_seguridad ... ok
test_ok ... ok
test_seguridad ... ok
test_semantico_cero_filas_y_luego_corregido ... ok
test_semantico_corre_pero_responde_otra_cosa ... ok

----------------------------------------------------------------------
Ran 9 tests in 17.406s

OK
```

## Casos reales con el modelo (`llama3.1:8b-instruct-q4_K_M`)

### Seguridad — sentencia no permitida
Primera ejecución, antes del ajuste de `no_es_sql`:
```
PREGUNTA: Borra de la base de datos todos los pedidos cancelados.
  SQL: "DELETE FROM orders WHERE order_status = 'canceled';"
  error: La consulta generada no es una lectura segura y fue rechazada: Solo se permiten consultas SELECT. La consulta generada empieza con 'delete'.
  intentos: [('seguridad', "Solo se permiten consultas SELECT. La consulta generada empieza con 'delete'.")]
PREGUNTA: Actualiza el estatus de todos los pedidos cancelados a delivered.
  SQL: 'No puedo ayudarte a generar una consulta SQL que actualice datos en la base de datos. ¿Hay algo más en lo que pueda ayudarte?'
  error: La consulta generada no es una lectura segura y fue rechazada: Solo se permiten consultas SELECT. La consulta generada empieza con 'no'.
  intentos: [('seguridad', "Solo se permiten consultas SELECT. La consulta generada empieza con 'no'.")]
```
**Error de clasificación detectado:** la segunda respuesta es una **negativa del modelo en texto**, no una sentencia insegura, y se clasificaba como `seguridad`. Ajuste: `validate_select_only` distingue entre `motivo="prohibida"` (la primera palabra es una sentencia SQL distinta de SELECT) y `motivo="no_es_sql"` (texto), y `no_es_sql` se clasifica como `ejecucion`. **El comportamiento del pipeline no cambió** (sigue rechazando sin reintento); solo cambia la clasificación. Después del ajuste:
```
PREGUNTA: Borra de la base de datos todos los pedidos cancelados.
  SQL: "DELETE FROM orders WHERE order_status = 'canceled';"
  intentos: [('seguridad', "Solo se permiten consultas SELECT. La consulta generada empieza con 'delete'.")]
PREGUNTA: Actualiza el estatus de todos los pedidos cancelados a delivered.
  SQL: 'No puedo ayudarte a generar una consulta SQL que actualice los datos en la base de datos. ¿Hay algo más en lo que pueda ayudarte?'
  intentos: [('ejecucion', "Solo se permiten consultas SELECT. La consulta generada empieza con 'no'.")]
```
Queda como hallazgo para la UI (Fases 10-11): ante una negativa del modelo, el usuario ve "no es una lectura segura y fue rechazada", que no describe lo que pasó.

### Infra — Ollama detenido de verdad
Se detuvieron todos los procesos `ollama*` (`Procesos ollama tras detener: 0`; `API: no responde (La operación sobrepasó el tiempo de espera.)`):
```
error: No se pudo conectar a Ollama en http://localhost:11434. ¿Está corriendo? Prueba con: ollama serve
clasificación final: infra
intentos: [('infra', 'No se pudo conectar a Ollama en http://localhost:11434. ¿Está corriendo? Prueba con: ollama serve'), ('infra', 'No se pudo conectar a Ollama en http://localhost:11434. ¿Está corriendo? Prueba con: ollama serve')]
tiempo: 26.2 s
===== $ python eval/run_eval.py --limit 1 (con Ollama detenido)
⚠ No se pudo conectar a Ollama en http://localhost:11434. Ejecuta 'ollama serve' e intenta de nuevo.
[exit code: 1]
```

**Problema operativo abierto:** al volver a abrir la app de bandeja de Ollama (`ollama app.exe`), esta **no logra levantar su servidor** (`app.log`: `"ollama server not ready after retries"`; no aparece ningún proceso `ollama.exe`). Hubo dos intentos (relanzar la app; detener todo y relanzarla limpia), ambos fallidos. Lanzar `ollama serve` directamente sí funciona (`Listening on 127.0.0.1:11434 (version 0.40.2)`, Vulkan con la RX 6600). Para no bloquear el plan, el servidor corre como `ollama serve` en segundo plano desde esta sesión. **Al terminar la sesión puede que Ollama quede detenido**: reiniciar Windows o abrir Ollama desde el menú Inicio probablemente lo resuelva (no verificado).

### Ok / ejecución / semántico — corrida completa (`eval/baselines/fase2_clasificacion.json`)
Mismo oráculo (v1) y configuración que baseline_01 (sin plantillas). Inicio 17:53:41, fin 18:07:44.
```
[1/10] q1_pedidos_totales      Intentos: ['ok']                    ✅ [ok]
[2/10] q2_categoria_mas_ingresos  Intentos: ['semantico']          ❌ [semantico] valores: …
[3/10] q3_pct_clientes_recurrentes Intentos: ['semantico']         ❌ [semantico] valores: …
[4/10] q4_categorias_mas_compra_unica Intentos: ['ejecucion', 'ejecucion']  ❌ [ejecucion] filas: el modelo devolvió 0, la referencia tiene 5
[5/10] q5_retraso_baja_calificacion Intentos: ['ok', 'ok']         ❌ [semantico] pipeline: la pregunta se descompuso en sub-consultas
[6/10] q6_metodo_pago_mayor_venta_promedio Intentos: ['ok', 'ok']  ❌ [semantico] pipeline: la pregunta se descompuso en sub-consultas
[7/10] q7_estado_mas_pedidos_entregados Intentos: ['ejecucion', 'ejecucion'] ❌ [ejecucion] filas: el modelo devolvió 0, la referencia tiene 1
[8/10] q8_tiempo_promedio_entrega Intentos: ['semantico']           ❌ [semantico] valores: …
[9/10] q9_pedidos_sin_entrega   Intentos: ['ok']                    ✅ [ok]
[10/10] q10_ticket_promedio_pedido Intentos: ['semantico']          ❌ [semantico] valores: …
=== RESULTADO FINAL: correctas 2/10 (20.0%) | texto respaldado 6/10 | latencia media 81.33 s | origen {'llm': 8, 'sin_origen': 2} | recursos {'size_bytes': 6138678475, 'size_vram_bytes': 5644998410, 'pct_gpu': 92.0, 'context_length': 8192} ===
=== CLASIFICACIÓN FINAL (por pregunta): {'ok': 2, 'ejecucion': 2, 'semantico': 6, 'seguridad': 0, 'infra': 0} ===
=== CLASIFICACIÓN POR INTENTO: {'ok': 6, 'ejecucion': 4, 'semantico': 4, 'seguridad': 0, 'infra': 0} ===
```
(Líneas resumidas del log `logs/fase2.log`; el JSON versionado tiene el detalle completo por intento.)

Notas sobre esta corrida:
- En q5 y q6 (descompuestas), las sub-consultas aparecían como `ok` en el desglose **por intento**. Después de esta corrida se ajustó para que cuenten como `semantico`, con una prueba (`test_descompuesta_en_subconsultas_es_semantico`). La clasificación final por pregunta no cambia. Con la regla corregida, el desglose por intento de esta corrida sería `ok 2, ejecucion 4, semantico 8`.
- Precisión 2/10, igual que baseline_01. Las mismas preguntas fallan por las mismas causas.
- **Latencia media 81 s.** En un primer momento la atribuí a consultas pesadas de la Fase 5 que corrían en paralelo. **Corrección (Fase 4):** la causa principal más probable es que, desde que el servidor de Ollama se relanzó a mano (~17:50), llama3.1 genera a 3.6-4.8 tok/s en vez de 36 tok/s; ver FASE_04.md, "Salvedad de velocidad". **VRAM:** esta vez el modelo quedó al **92 % en GPU** (5.64 de 6.14 GB), porque había menos VRAM libre que antes. Ambas cosas obligan a controlar las condiciones al medir en la Fase 4.

## Lectura de los fallos (lo que muestra el desglose)
Con este modelo y este pipeline, **la mayoría de los fallos son semánticos (6 de 8)**: el SQL corre y devuelve una cifra, pero no la pedida. Los reintentos actuales solo se activan con errores de ejecución o con 0 filas, así que **nunca corrigen un fallo semántico**. Eso es lo que abordan las Fases 6, 7 y 9.

## Decisiones propias
D-09 (0 filas = semántico; SQL vacío o texto = ejecución; pregunta descompuesta = semántico). Ver DECISIONES.md.
