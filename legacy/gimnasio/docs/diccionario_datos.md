# Diccionario de datos — FitZone (gimnasio ficticio)

Base de datos relacional que modela la operación de un gimnasio durante el año
2025: clientes y membresías, ingresos y gastos, personal, clases y asistencia,
inventario, marketing, satisfacción y calendario.

Motor de referencia: **SQLite** (`db/gimnasio.db`). El esquema está definido en
SQLAlchemy (`db/models.py`) y es portable a **PostgreSQL** cambiando la variable
de entorno `DATABASE_URL` (ver `docs/DEPLOY.md`).

Este documento es la fuente de verdad que se inyecta como contexto al LLM en el
módulo Text-to-SQL (`llm/text_to_sql.py`), para reducir alucinaciones y anclar
al modelo a los nombres reales de tablas/columnas.

> Convenciones: PK = llave primaria · FK = llave foránea · montos en **MXN**.
> Todas las fechas de negocio caen dentro del año **2025**.

---

## Índice de tablas

| Dominio | Tablas |
|---|---|
| Clientes / Membresías | `clientes`, `membresias` |
| Ingresos / Transacciones | `pagos`, `productos`, `ventas`, `descuentos` |
| Gastos operativos | `gastos_operativos`, `equipos`, `ordenes_mantenimiento` |
| Personal | `instructores`, `proveedores` |
| Clases y asistencia | `clases_catalogo`, `sesiones_clase`, `reservaciones`, `checkins` |
| Inventario | `movimientos_inventario` |
| Marketing | `campanias_marketing` |
| Satisfacción | `encuestas_satisfaccion`, `tickets_soporte` |
| Calendario | `calendario_eventos` |
| Vistas analíticas | `vw_ingresos_netos_mensuales`, `vw_retencion_churn_trimestral`, `vw_ltv_cliente` |

---

## `clientes`
Datos demográficos y de adquisición de cada cliente.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | Identificador único |
| nombre | VARCHAR(80) | No | Nombre de pila |
| apellido | VARCHAR(80) | No | Apellido |
| email | VARCHAR(150) | **Sí** | Puede faltar (dato sintético imperfecto) |
| telefono | VARCHAR(20) | **Sí** | Puede faltar |
| fecha_nacimiento | DATE | **Sí** | — |
| genero | VARCHAR(20) | Sí | `F` / `M` / `otro` |
| zona | VARCHAR(80) | Sí | Zona de la ciudad: Centro, Norte, Sur, Poniente, Oriente |
| colonia | VARCHAR(120) | **Sí** | Colonia/barrio; puede faltar |
| fecha_alta | DATE | No | Fecha de alta como cliente |
| canal_adquisicion | VARCHAR(30) | No | `redes_sociales` \| `referido` \| `walk_in` \| `campania` \| `otro` |
| referido_por_id | INTEGER FK → clientes.id | Sí | Self-FK: cliente que lo refirió (si `canal_adquisicion = 'referido'`) |
| campania_id | INTEGER FK → campanias_marketing.id | Sí | Campaña asociada al alta (si `canal_adquisicion = 'campania'`) |

---

## `membresias`
Historial de membresías por cliente (un cliente puede tener varias filas a lo
largo del año: altas, renovaciones, congelamientos y cancelaciones).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| cliente_id | INTEGER FK → clientes.id | No | |
| tipo | VARCHAR(20) | No | `mensual` \| `semestral` \| `anual` |
| precio | NUMERIC(10,2) | No | Precio del periodo contratado (MXN) |
| fecha_inicio | DATE | No | |
| fecha_fin | DATE | Sí | Fecha en que vence/venció el periodo |
| fecha_renovacion | DATE | Sí | Próxima fecha de renovación esperada |
| estado | VARCHAR(20) | No | `activa` \| `vencida` (ya renovada) \| `cancelada` \| `congelada` |
| motivo_cancelacion | VARCHAR(200) | Sí | Solo si `estado = 'cancelada'` |
| fecha_cancelacion | DATE | Sí | Solo si `estado = 'cancelada'` |
| motivo_congelamiento | VARCHAR(200) | Sí | Solo si `estado = 'congelada'` |

---

## `pagos`
Pagos de cuota (membresía) y cobros recurrentes.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| cliente_id | INTEGER FK → clientes.id | No | |
| membresia_id | INTEGER FK → membresias.id | Sí | Periodo de membresía que se está pagando |
| fecha_pago | DATE | No | |
| monto | NUMERIC(10,2) | **Sí** | Puede faltar (error de captura). Ojo: hay outliers de montos anormalmente altos (~0.5% de filas) que simulan cobros duplicados |
| metodo_pago | VARCHAR(20) | No | `efectivo` \| `tarjeta` \| `transferencia` |
| concepto | VARCHAR(30) | No | `cuota_mensual` \| `cuota_semestral` \| `cuota_anual` \| `otro` |
| descuento_id | INTEGER FK → descuentos.id | Sí | |

> **Ingresos por venta de productos/servicios NO están en `pagos`**, están en `ventas`.

---

## `productos`
Catálogo de productos/servicios adicionales (suplementos, ropa, accesorios, servicios).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| nombre | VARCHAR(150) | No | |
| categoria | VARCHAR(40) | No | `suplemento` \| `ropa` \| `accesorio` \| `servicio` |
| costo | NUMERIC(10,2) | No | Costo de adquisición |
| precio_venta | NUMERIC(10,2) | No | Precio al público |
| proveedor_id | INTEGER FK → proveedores.id | Sí | |
| activo | BOOLEAN | No | |

## `ventas`
Ventas de productos/servicios (a clientes o visitantes ocasionales).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| cliente_id | INTEGER FK → clientes.id | **Sí** | NULL si fue venta a visitante sin membresía (~10% de las ventas) |
| producto_id | INTEGER FK → productos.id | No | |
| fecha | DATE | No | |
| cantidad | INTEGER | No | |
| precio_unitario | NUMERIC(10,2) | No | Puede ser 0 en una pequeña fracción de filas (outlier: error de captura en punto de venta) |
| descuento_id | INTEGER FK → descuentos.id | Sí | |

> Ingreso de una venta = `cantidad * precio_unitario`.

## `descuentos`
Catálogo de descuentos/promociones aplicables a pagos o ventas.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| nombre | VARCHAR(120) | No | |
| tipo | VARCHAR(20) | No | `porcentaje` \| `monto_fijo` |
| valor | NUMERIC(10,2) | No | Porcentaje (0-100) o monto fijo en MXN, según `tipo` |
| fecha_inicio | DATE | No | |
| fecha_fin | DATE | Sí | |
| campania_id | INTEGER FK → campanias_marketing.id | Sí | |

---

## `gastos_operativos`
Gastos operativos del gimnasio (servicios básicos, mantenimiento/limpieza,
nómina agregada, renta). **No incluye desglose de sueldos individuales.**

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| categoria | VARCHAR(30) | No | `servicios_basicos` \| `mantenimiento_limpieza` \| `nomina` \| `renta` \| `otro` |
| subcategoria | VARCHAR(40) | Sí | Ej: `agua`, `luz`, `internet`, `insumos_limpieza`, `nomina_general`, `renta_local` |
| monto | NUMERIC(10,2) | No | MXN. Servicios básicos oscilan $500–$2,000, con estacionalidad (luz sube en meses calurosos abr-sep). **Julio 2025 tiene un outlier de luz (~$5,000-6,000) por falla de A/C**, útil para pruebas de detección de anomalías |
| fecha | DATE | No | Una fila por servicio/categoría por mes |
| descripcion | VARCHAR(255) | Sí | |

## `equipos`
Catálogo de equipo/máquinas del gimnasio.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| nombre | VARCHAR(150) | No | Ej: Caminadora, Rack de sentadillas, TRX |
| categoria | VARCHAR(40) | No | `cardio` \| `fuerza` \| `funcional` \| `accesorio` |
| fecha_compra | DATE | No | Puede ser anterior a 2025 |
| costo | NUMERIC(10,2) | No | |
| vida_util_anios | INTEGER | No | Vida útil estimada |
| estado | VARCHAR(20) | No | `operativo` \| `en_reparacion` \| `baja` |

## `ordenes_mantenimiento`
Órdenes de mantenimiento/reparación de equipo.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| equipo_id | INTEGER FK → equipos.id | No | |
| fecha | DATE | No | |
| tipo | VARCHAR(20) | No | `preventivo` \| `correctivo` |
| costo | NUMERIC(10,2) | No | |
| descripcion | VARCHAR(255) | Sí | |

---

## `instructores`
Entrenadores/instructores (sin montos de sueldo).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| nombre | VARCHAR(80) | No | |
| apellido | VARCHAR(80) | No | |
| puesto | VARCHAR(60) | No | `instructor_grupal` \| `entrenador_personal` \| `coordinador` |
| fecha_contratacion | DATE | No | |
| tipo_contrato | VARCHAR(20) | No | `planta` \| `honorarios` \| `medio_tiempo` |
| activo | BOOLEAN | No | |

## `proveedores`
Proveedores de productos e insumos.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| nombre | VARCHAR(150) | No | |
| contacto | VARCHAR(120) | Sí | |
| telefono | VARCHAR(20) | Sí | |
| email | VARCHAR(150) | Sí | |

---

## `clases_catalogo`
Catálogo de tipos de clase (spinning, crossfit, yoga, etc.) con instructor titular.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| nombre | VARCHAR(60) | No | Spinning, CrossFit, Yoga, Zumba, Box, Funcional, Pilates, HIIT, Step, Aqua Aeróbics, Calistenia, Stretching |
| instructor_id | INTEGER FK → instructores.id | Sí | Instructor titular |
| capacidad | INTEGER | No | Cupo por sesión |
| duracion_minutos | INTEGER | No | |

## `sesiones_clase`
Instancia concreta de una clase en el calendario (fecha/hora reales).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| clase_id | INTEGER FK → clases_catalogo.id | No | |
| instructor_id | INTEGER FK → instructores.id | Sí | |
| fecha | DATE | No | |
| hora_inicio | VARCHAR(5) | No | Formato HH:MM |
| hora_fin | VARCHAR(5) | No | Formato HH:MM |
| capacidad | INTEGER | No | |
| sala | VARCHAR(40) | Sí | |

## `reservaciones`
Reservaciones de clientes a sesiones de clase (incluye no-shows).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| sesion_id | INTEGER FK → sesiones_clase.id | No | |
| cliente_id | INTEGER FK → clientes.id | No | |
| fecha_reservacion | DATE | No | Fecha en que se hizo la reservación |
| estado | VARCHAR(20) | No | `reservado` \| `asistio` \| `no_show` \| `cancelado` |

## `checkins`
Registro de asistencia diaria al gimnasio, con o sin clase asociada.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| cliente_id | INTEGER FK → clientes.id | No | |
| fecha | DATE | No | |
| hora | VARCHAR(5) | No | Formato HH:MM |
| tipo | VARCHAR(20) | No | `entrenamiento_libre` \| `clase` |
| sesion_id | INTEGER FK → sesiones_clase.id | Sí | Solo si `tipo = 'clase'` |

---

## `movimientos_inventario`
Entradas (compra a proveedor) y salidas (venta) de inventario.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| producto_id | INTEGER FK → productos.id | No | |
| tipo | VARCHAR(10) | No | `entrada` \| `salida` |
| cantidad | INTEGER | No | |
| fecha | DATE | No | |
| proveedor_id | INTEGER FK → proveedores.id | Sí | Solo en entradas |
| motivo | VARCHAR(60) | Sí | `compra` \| `venta` \| `merma` \| `ajuste` |

---

## `campanias_marketing`
Campañas de marketing relacionadas con nuevas altas de clientes.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| nombre | VARCHAR(150) | No | |
| tipo | VARCHAR(30) | No | `redes_sociales` \| `volanteo` \| `referidos` \| `evento` \| `google_ads` |
| fecha_inicio | DATE | No | |
| fecha_fin | DATE | No | |
| costo | NUMERIC(10,2) | No | |
| descripcion | VARCHAR(255) | Sí | |

---

## `encuestas_satisfaccion`
Encuestas de satisfacción/NPS post-clase. **Solo calificación numérica y
comentario opcional — sin datos de salud.**

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| cliente_id | INTEGER FK → clientes.id | Sí | |
| sesion_id | INTEGER FK → sesiones_clase.id | Sí | |
| fecha | DATE | No | |
| calificacion | INTEGER | No | Escala NPS 0-10 (mayoría 7-10, con una cola de calificaciones bajas ligada a quejas) |
| comentario | TEXT | Sí | Opcional; más frecuente en calificaciones muy altas o muy bajas |

## `tickets_soporte`
Tickets de soporte/quejas de clientes.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| cliente_id | INTEGER FK → clientes.id | No | |
| fecha_apertura | DATE | No | |
| categoria | VARCHAR(40) | No | `equipo` \| `limpieza` \| `atencion` \| `cobros` \| `instalaciones` \| `otro` |
| estado | VARCHAR(20) | No | `abierto` \| `en_proceso` \| `cerrado` |
| descripcion | TEXT | Sí | |
| fecha_cierre | DATE | Sí | Solo si `estado = 'cerrado'` |

---

## `calendario_eventos`
Días festivos y eventos especiales del gimnasio (para correlacionar con picos
de asistencia/ventas).

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| id | INTEGER PK | No | |
| fecha | DATE | No | |
| nombre_evento | VARCHAR(150) | No | Ej: "Reto Año Nuevo, Vida Nueva", "Aniversario del gimnasio" |
| tipo | VARCHAR(30) | No | `feriado_nacional` \| `evento_gimnasio` |
| descripcion | VARCHAR(255) | Sí | |

---

## Vistas analíticas (pre-calculadas para Text-to-SQL)

### `vw_ingresos_netos_mensuales`
Ingresos netos por mes calendario (`YYYY-MM`).

| Columna | Descripción |
|---|---|
| mes | `YYYY-MM` |
| ingresos_cuotas | Suma de `pagos.monto` del mes |
| ingresos_productos | Suma de `ventas.cantidad * ventas.precio_unitario` del mes |
| ingresos_totales | `ingresos_cuotas + ingresos_productos` |
| gastos_totales | Suma de `gastos_operativos.monto` del mes |
| ingreso_neto | `ingresos_totales - gastos_totales` |

### `vw_retencion_churn_trimestral`
Retención/churn por trimestre, basada en membresías iniciadas en el trimestre
(`membresias.fecha_inicio`) y canceladas dentro de él (`membresias.fecha_cancelacion`).

| Columna | Descripción |
|---|---|
| anio | Año (texto) |
| trimestre | 1-4 |
| total_activas | Membresías con `fecha_inicio` en ese trimestre |
| total_canceladas | De esas, cuántas se cancelaron con `fecha_cancelacion` en el mismo trimestre |
| tasa_churn | `total_canceladas / total_activas` |
| tasa_retencion | `1 - tasa_churn` |

### `vw_ltv_cliente`
LTV aproximado por cliente = pagos de cuota + ventas de producto, acumulados.

| Columna | Descripción |
|---|---|
| cliente_id | |
| nombre / apellido | |
| total_pagos_cuotas | Suma histórica de `pagos.monto` |
| total_ventas_productos | Suma histórica de `ventas.cantidad * precio_unitario` |
| ltv_aproximado | Suma de ambos |

---

## Notas para generación de SQL (Text-to-SQL)

1. Todas las fechas están en 2025; usa `strftime('%Y-%m', fecha)` para agrupar
   por mes y `strftime('%m', fecha)` para el mes en SQLite.
2. `monto` en `pagos` y `precio_unitario` en `ventas` pueden tener valores
   `NULL` o atípicos — usar `COALESCE`/`AVG` con cuidado si la pregunta pide
   "promedio" o "total".
3. El ingreso por productos **no** está en `pagos`, está en `ventas`
   (`cantidad * precio_unitario`).
4. Para preguntas de retención/churn, usar `vw_retencion_churn_trimestral` en
   vez de recalcular desde `membresias` a mano.
5. Para "gasto en luz/agua/internet", filtrar `gastos_operativos` por
   `subcategoria`, no por `categoria` (la categoría es `servicios_basicos`).
6. Solo se permiten consultas de lectura (`SELECT`); el ejecutor rechaza
   cualquier sentencia que no sea `SELECT`.
