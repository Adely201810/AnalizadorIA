# Etapa 2 · Paso 2 — Oráculo ampliado a 30 preguntas y dividido en DESARROLLO / PRUEBA

Fecha: 2026-10-11 · Estado: **COMPLETO** · SQL 30/30 · pandas 30/30 · pruebas 57/57

## Qué se hizo
- **`eval/ground_truth_olist.json` v3** (generado por `eval/construir_oraculo_v3.py`): 30 preguntas, cada una con UNA consulta. Incluye las 10 necesidades del dashboard (v2) y 20 nuevas de dificultad variada: conteos, promedios, porcentajes con denominadores, rankings, filtro de pedido válido y joins de 3-4 tablas. La v2 se puede reconstruir desde git.
- **Necesidad 4 restaurada con su criterio completo** (D-20): `CUME_DIST()` para el 25 % superior de ingresos **y** (calificación < 3.5 **o** > 15 % de entregas tardías) → **13** vendedores. El dashboard la muestra en su pestaña.
- **Empates:** en los rankings se comprobó que el 1.er puesto no empata ni queda a centésimas del 2.º. La única candidata dudosa (top 3 de ciudades: 3.ª con 2,712 frente a 4.ª con 2,693) se redujo a **top 2** (6,555 frente a 2,712).
- **Split** (D-21): 10 necesidades + 10 nuevas en DESARROLLO; 10 nuevas en PRUEBA, por sorteo con semilla `20261011`. Versionado en `eval/split_oraculo.json`.
- **Blindaje** (D-22): `tests/test_heldout.py`; `run_eval.py --conjunto` (por defecto `desarrollo`); la app solo ofrece las 10 necesidades como ejemplo.
- **No se ejecutó ningún modelo sobre PRUEBA.**

## Exploración previa (empates)
```
n04 (criterio completo): [(13,)]
x01_pedidos_cancelados [conteo] -> [(625,)]
x02_pct_entregas_con_retraso [porcentaje] -> [(8.11,)]
x03_flete_promedio_por_articulo [promedio] -> [(19.99,)]
x04_pct_resenas_5_estrellas [porcentaje] -> [(57.78,)]
x05_vendedor_mas_ingresos [ranking] -> [('4869f7a5dfa277a7dca6462dcf3b52b2', 229237.63)] | top: [('4869f7a5dfa277a7dca6462dcf3b52b2', 229237.63), ('53243585a1d6dc2643021fd1853d8905', 222776.05), ('4a3ca9315b744ce9f8e9374361493884', 200326.12)]
x06_pct_pedidos_varios_articulos [porcentaje] -> [(9.94,)]
x07_calificacion_pedidos_bed_bath_table [joins] -> [(3.97,)]
x08_dias_entrega_rj [promedio] -> [(15.31,)]
x09_mes_mas_cancelados [ranking] -> [('2018-08', 84)] | top: [('2018-08', 84), ('2018-02', 73), ('2018-07', 41)]
x10_categoria_precio_promedio_mas_alto [ranking] -> [('computers', 1098.34)] | top: [('computers', 1098.34), ('home_appliances_2', 470.85), ('agro_industry_and_commerce', 342.12)]
x11_clientes_unicos_sp [conteo] -> [(39749,)]
x12_vendedores_health_beauty [joins] -> [(489,)]
x13_estado_mayor_gasto_promedio [ranking] -> [('CE', 207.5)] | top: [('CE', 207.5), ('PE', 195.39), ('BA', 181.49)]
x14_ingresos_vendedores_sp_fuera_sp [joins] -> [(5101873.16,)]
x15_calificacion_pedidos_boleto [joins] -> [(4.12,)]
x16_pct_productos_sin_categoria [porcentaje] -> [(1.85,)]
x17_top3_ciudades_vendedores [ranking] -> [('sao paulo', 24457), ('ibitinga', 6555), ('curitiba', 2712)] | top: [('sao paulo', 24457), ('ibitinga', 6555), ('curitiba', 2712), ('santo andre', 2693)]
x18_peso_promedio_furniture_decor [joins] -> [(2649.19,)]
x19_anio_mas_ingresos [ranking] -> [('2018', 7341182.41)] | top: [('2018', 7341182.41), ('2017', 6108492.27), ('2016', 44726.06)]
x20_pct_clientes_resena_1_estrella [porcentaje] -> [(10.89,)]
```
(x17 se cambió después a top 2.)

## Verificación: SQL contra la base (`python eval/compute_ground_truth.py`)
```
[OK] n01_pct_clientes_recurrentes           -> [(3.04,)]
[OK] n02_calificacion_retraso_vs_a_tiempo   -> [(2.57, 4.29)]
[OK] n03_pct_ingresos_top5_categorias       -> [(39.82,)]
[OK] n04_vendedores_problematicos           -> [(13,)]
[OK] n05_estado_mayor_peso_flete            -> [('RR', 28.55)]
[OK] n06_metodo_pago_mas_usado              -> [('credit_card', 75618)]
[OK] n07_mes_mayores_ingresos               -> [('2017-11', 1003862.14)]
[OK] n08_categoria_mas_resenas_1_estrella   -> [('fashion_male_clothing', 22.73, 110)]
[OK] n09_categorias_mas_compra_unica        -> [('consoles_games', 1054, 1050, 99.62), ('electronics', 2543, 2533, 99.61), ('cool_stuff', 3616, 3600, 99.56), ('small_appliances', 622, 619, 99.52), ('construction_tools_construction', 746, 742, 99.46)]
[OK] n10_estado_mas_clientes_por_vendedor   -> [('BA', 170.74, 3244, 19)]
[OK] x01_pedidos_cancelados                 -> [(625,)]
[OK] x02_pct_entregas_con_retraso           -> [(8.11,)]
[OK] x03_flete_promedio_por_articulo        -> [(19.99,)]
[OK] x04_pct_resenas_5_estrellas            -> [(57.78,)]
[OK] x05_vendedor_mas_ingresos              -> [('4869f7a5dfa277a7dca6462dcf3b52b2', 229237.63)]
[OK] x06_pct_pedidos_varios_articulos       -> [(9.94,)]
[OK] x07_calificacion_pedidos_bed_bath_table -> [(3.97,)]
[OK] x08_dias_entrega_rj                    -> [(15.31,)]
[OK] x09_mes_mas_cancelados                 -> [('2018-08', 84)]
[OK] x10_categoria_precio_promedio_mas_alto -> [('computers', 1098.34)]
[OK] x11_clientes_unicos_sp                 -> [(39749,)]
[OK] x12_vendedores_health_beauty           -> [(489,)]
[OK] x13_estado_mayor_gasto_promedio        -> [('CE', 207.5)]
[OK] x14_ingresos_vendedores_sp_fuera_sp    -> [(5101873.16,)]
[OK] x15_calificacion_pedidos_boleto        -> [(4.12,)]
[OK] x16_pct_productos_sin_categoria        -> [(1.85,)]
[OK] x17_top2_ciudades_vendedores           -> [('sao paulo', 24457), ('ibitinga', 6555)]
[OK] x18_peso_promedio_furniture_decor      -> [(2649.19,)]
[OK] x19_anio_mas_ingresos                  -> [('2018', 7341182.41)]
[OK] x20_pct_clientes_resena_1_estrella     -> [(10.89,)]
```

## Verificación independiente con pandas sobre los CSV (`dashboard/verify_pandas.py`)
```
[OK] n01_pct_clientes_recurrentes: pandas=[[3.04]] | oráculo=[[3.04]]
[OK] n02_calificacion_retraso_vs_a_tiempo: pandas=[[2.57, 4.29]] | oráculo=[[2.57, 4.29]]
[OK] n03_pct_ingresos_top5_categorias: pandas=[[39.82]] | oráculo=[[39.82]]
[OK] n04_vendedores_problematicos: pandas=[[13]] | oráculo=[[13]]
[OK] n05_estado_mayor_peso_flete: pandas=[['RR', 28.55]] | oráculo=[['RR', 28.55]]
[OK] n06_metodo_pago_mas_usado: pandas=[['credit_card', 75618]] | oráculo=[['credit_card', 75618]]
[OK] n07_mes_mayores_ingresos: pandas=[['2017-11', 1003862.14]] | oráculo=[['2017-11', 1003862.14]]
[OK] n08_categoria_mas_resenas_1_estrella: pandas=[['fashion_male_clothing', 22.73, 110]] | oráculo=[['fashion_male_clothing', 22.73, 110]]
[OK] n09_categorias_mas_compra_unica: pandas=[['consoles_games', 1054, 1050, 99.62], ['electronics', 2543, 2533, 99.61], ['cool_stuff', 3616, 3600, 99.56], ['small_appliances', 622, 619, 99.52], ['construction_tools_construction', 746, 742,
[OK] n10_estado_mas_clientes_por_vendedor: pandas=[['BA', 170.74, 3244, 19]] | oráculo=[['BA', 170.74, 3244, 19]]
[OK] x01_pedidos_cancelados: pandas=[[625]] | oráculo=[[625]]
[OK] x02_pct_entregas_con_retraso: pandas=[[8.11]] | oráculo=[[8.11]]
[OK] x03_flete_promedio_por_articulo: pandas=[[19.99]] | oráculo=[[19.99]]
[OK] x04_pct_resenas_5_estrellas: pandas=[[57.78]] | oráculo=[[57.78]]
[OK] x05_vendedor_mas_ingresos: pandas=[['4869f7a5dfa277a7dca6462dcf3b52b2', 229237.63]] | oráculo=[['4869f7a5dfa277a7dca6462dcf3b52b2', 229237.63]]
[OK] x06_pct_pedidos_varios_articulos: pandas=[[9.94]] | oráculo=[[9.94]]
[OK] x07_calificacion_pedidos_bed_bath_table: pandas=[[3.97]] | oráculo=[[3.97]]
[OK] x08_dias_entrega_rj: pandas=[[15.31]] | oráculo=[[15.31]]
[OK] x09_mes_mas_cancelados: pandas=[['2018-08', 84]] | oráculo=[['2018-08', 84]]
[OK] x10_categoria_precio_promedio_mas_alto: pandas=[['computers', 1098.34]] | oráculo=[['computers', 1098.34]]
[OK] x11_clientes_unicos_sp: pandas=[[39749]] | oráculo=[[39749]]
[OK] x12_vendedores_health_beauty: pandas=[[489]] | oráculo=[[489]]
[OK] x13_estado_mayor_gasto_promedio: pandas=[['CE', 207.5]] | oráculo=[['CE', 207.5]]
[OK] x14_ingresos_vendedores_sp_fuera_sp: pandas=[[5101873.16]] | oráculo=[[5101873.16]]
[OK] x15_calificacion_pedidos_boleto: pandas=[[4.12]] | oráculo=[[4.12]]
[OK] x16_pct_productos_sin_categoria: pandas=[[1.85]] | oráculo=[[1.85]]
[OK] x17_top2_ciudades_vendedores: pandas=[['sao paulo', 24457], ['ibitinga', 6555]] | oráculo=[['sao paulo', 24457], ['ibitinga', 6555]]
[OK] x18_peso_promedio_furniture_decor: pandas=[[2649.19]] | oráculo=[[2649.19]]
[OK] x19_anio_mas_ingresos: pandas=[['2018', 7341182.41]] | oráculo=[['2018', 7341182.41]]
[OK] x20_pct_clientes_resena_1_estrella: pandas=[[10.89]] | oráculo=[[10.89]]
OK: 30 / 30
```

## Split
```
{
  "semilla": 20261011,
  "desarrollo": [
    "n01_pct_clientes_recurrentes",
    "n02_calificacion_retraso_vs_a_tiempo",
    "n03_pct_ingresos_top5_categorias",
    "n04_vendedores_problematicos",
    "n05_estado_mayor_peso_flete",
    "n06_metodo_pago_mas_usado",
    "n07_mes_mayores_ingresos",
    "n08_categoria_mas_resenas_1_estrella",
    "n09_categorias_mas_compra_unica",
    "n10_estado_mas_clientes_por_vendedor",
    "x02_pct_entregas_con_retraso",
    "x03_flete_promedio_por_articulo",
    "x04_pct_resenas_5_estrellas",
    "x05_vendedor_mas_ingresos",
    "x07_calificacion_pedidos_bed_bath_table",
    "x10_categoria_precio_promedio_mas_alto",
    "x13_estado_mayor_gasto_promedio",
    "x17_top2_ciudades_vendedores",
    "x18_peso_promedio_furniture_decor",
    "x19_anio_mas_ingresos"
  ],
  "prueba": [
    "x01_pedidos_cancelados",
    "x06_pct_pedidos_varios_articulos",
    "x08_dias_entrega_rj",
    "x09_mes_mas_cancelados",
    "x11_clientes_unicos_sp",
    "x12_vendedores_health_beauty",
    "x14_ingresos_vendedores_sp_fuera_sp",
    "x15_calificacion_pedidos_boleto",
    "x16_pct_productos_sin_categoria",
    "x20_pct_clientes_resena_1_estrella"
  ]
}
```
Dificultad: DESARROLLO = necesidad 10, ranking 5, porcentaje 2, joins 2, promedio 1. PRUEBA = porcentaje 3, joins 3, conteo 2, promedio 1, ranking 1.

## Pruebas de blindaje
Primera corrida: 3 fallos reales. Dos few-shot se parecían a preguntas de PRUEBA (x16 con Jaccard 0.250; x08 con el fragmento "en promedio desde la compra hasta") y se reemplazaron por otros ejemplos. El tercero fue un falso positivo de la propia prueba (D-22). Corrida final:
```
test_app_no_ofrece_preguntas_de_prueba ... ok
test_bitacora_sin_contenido_de_prueba ... ok
test_clasificador_lejos_de_prueba ... ok
test_evaluacion_no_usa_bitacora_y_por_defecto_es_desarrollo ... ok
test_fewshot_lejos_de_prueba ... ok
test_prompt_sin_fragmentos_ni_resultados_de_prueba ... ok
test_las_10_necesidades_estan_en_desarrollo ... ok
test_split_coincide_con_el_oraculo ... ok
(+ 6 de tests.test_fewshot_disjunto, ahora contra las 30)
Ran 14 tests in 16.402s
OK
--- suite completa ---
Ran 57 tests in 119.848s
OK
```
