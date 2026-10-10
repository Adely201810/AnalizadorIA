"""
Genera una versión COMPACTA del esquema de la base de datos Olist para inyectar
como contexto al LLM (a diferencia de docs/esquema_olist.md, que es para
lectura humana y es mucho más extenso).

Se construye por introspección de db/olist_models.py (SQLAlchemy metadata), así
que nunca queda desincronizada del esquema real. Se mantiene deliberadamente
corta para no inflar el num_ctx del modelo en hardware con RAM limitada -- ver
llm/ollama_client.py.
"""
from __future__ import annotations

from sqlalchemy import text

from db.olist_database import engine
from db.olist_database import verificar_bd_existe as _verificar_bd_existe
from db.olist_models import OlistBase as Base

# Las vistas no forman parte de la metadata de SQLAlchemy (se crean con SQL
# crudo en db/olist_views.sql): sus columnas y tipos se leen de la base real
# (ver _vista_line); aquí solo va la descripción de cada una. NOMBRES_VISTAS
# se reusa para el validador de tablas conocidas (llm/sql_guard.py).
VISTAS_DESCRIPCION = {
    "vw_ventas_pedido": "grano: una fila por línea de pedido",
    "vw_clientes_recurrentes": "excluye pedidos canceled/unavailable",
    "vw_entregas_retrasos": "solo pedidos entregados",
    "vw_ingresos_por_categoria": "excluye canceled/unavailable; categoria_ingles='sin_categoria' si el producto no tiene categoría",
    "vw_ingresos_por_vendedor": "excluye canceled/unavailable",
    "vw_retraso_por_rango": "rango_retraso: a_tiempo|1-3|4-7|8-14|15+ (días); usa `orden` para ordenar de a_tiempo a 15+",
}
NOMBRES_VISTAS = list(VISTAS_DESCRIPCION)

# Columnas de vistas cuyo tipo de almacenamiento no dice lo que significan
# (SQLite no tiene BOOLEAN ni DATETIME nativos).
TIPOS_SEMANTICOS_VISTAS = {
    ("vw_clientes_recurrentes", "es_recurrente"): "INTEGER 0/1",
    ("vw_entregas_retrasos", "entrega_con_retraso"): "INTEGER 0/1",
    ("vw_clientes_recurrentes", "primera_compra"): "DATETIME",
    ("vw_clientes_recurrentes", "ultima_compra"): "DATETIME",
}

NOTAS_TEXTO = """
Notas importantes:
- Solo SQLite. Para diferencias de fechas en días usa julianday(fecha_a) - julianday(fecha_b). Para agrupar por mes usa strftime('%Y-%m', fecha).
- `customer_id` es único POR PEDIDO, no por persona. La persona real es `customer_unique_id` (tabla `customers`). Agrupa por `customer_unique_id` para "clientes únicos"/"clientes recurrentes", nunca por `customer_id`.
- Para CONTAR clientes reales usa siempre COUNT(DISTINCT customer_unique_id), NUNCA COUNT(customer_unique_id) sin DISTINCT: `customers` tiene una fila POR PEDIDO, así que el mismo customer_unique_id se repite y un COUNT sin DISTINCT cuenta pedidos, no personas.
- Para relacionar `customers` con `order_items`, `order_payments` u `order_reviews` siempre pasa por `orders`: `customers.customer_id = orders.customer_id` y luego `orders.order_id = order_items.order_id` (o `order_payments.order_id` / `order_reviews.order_id`). NUNCA unas `customers.customer_id` directamente con `order_items.order_id` ni con ninguna otra tabla que no sea `orders`.
- Antes de reconstruir a mano un JOIN para preguntas de ventas por pedido, clientes recurrentes o retrasos de entrega, revisa primero si `vw_ventas_pedido`, `vw_clientes_recurrentes` o `vw_entregas_retrasos` ya resuelven la pregunta -- son más confiables que rearmar la lógica a mano.
- `vw_ingresos_por_categoria`, `vw_ingresos_por_vendedor` y `vw_retraso_por_rango` YA ESTÁN AGREGADAS (una fila por categoría/vendedor/rango) y ya traen todas las columnas necesarias. Selecciona sus columnas directamente (con WHERE/ORDER BY/LIMIT si hace falta); NUNCA les aplique otro SUM/AVG por encima, ni las uses sin GROUP BY junto a una columna no agregada, ni las vuelvas a unir (JOIN) con `vw_entregas_retrasos`/`order_reviews` -- eso o no tiene sentido (mezcla categorías/rangos en una sola fila) o no encuentra coincidencias (`rango_retraso` es texto, no se puede comparar/unir contra `dias_retraso` que es numérico).
- Preguntas sobre desde qué punto/umbral de retraso empieza a bajar la calificación (o similares) se responden con `SELECT * FROM vw_retraso_por_rango ORDER BY orden` (o sus columnas específicas) -- la vista ya trae el desglose completo por rango, no hay que re-agregar ni filtrar `review_score_promedio` a mano en otra tabla.
- `orders.order_delivered_customer_date` y otras fechas de `orders` pueden ser NULL si el pedido no llegó a esa etapa (ej. cancelado). Filtra con IS NOT NULL para hablar de tiempos de entrega.
- `order_reviews.review_id` no es único y un pedido puede tener varias reseñas; para "la calificación de un pedido" usa AVG(review_score) agrupado por order_id (o la vista vw_ventas_pedido/vw_entregas_retrasos, que ya lo resuelven).
- `products.product_category_name` no tiene FK formal a `product_category_translation` (traducción incompleta); únelas con LEFT JOIN, nunca JOIN.
- El monto realmente pagado de un pedido está en `order_payments.payment_value`, no en `order_items.price + freight_value`.
- El flete de un pedido es `freight_value` en `order_items`, NUNCA `payment_value` de `order_payments` (eso es el monto pagado, no el costo de envío). Para "peso del flete sobre el precio" usa SUM(freight_value) / SUM(price) (o `ratio_flete_ingresos` de las vistas), nunca `payment_value`.
- "Estado" en sentido geográfico = `customer_state`/`seller_state` (estados de Brasil, ej. SP, RJ). NUNCA confundir con `order_status` (estatus del pedido: delivered/shipped/canceled/...). Usa `order_status` solo cuando la pregunta hable explícitamente de estatus/status del pedido.
- "Ingresos" = SUM(price) excluyendo pedidos con order_status IN ('canceled','unavailable') -- un pedido cancelado no es ingreso real. Las vistas vw_ingresos_por_categoria/vw_ingresos_por_vendedor ya aplican esta exclusión, úsalas de preferencia.
- El flete como proporción de las ventas se calcula SUM(freight_value) / SUM(price) (agregado), NUNCA como promedio de la razón por pedido (AVG(freight_value/price)) -- eso pondera mal los pedidos baratos.
- Los datos de Olist cubren pedidos de 2016 a 2018 (no hay datos de años posteriores ni anteriores). Si preguntan por un periodo fuera de ese rango, lo correcto es decir que no hay registros para ese periodo, sin inventar una cifra.
- Solo se ejecutan consultas SELECT. Nunca generes INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/ATTACH.
- Responde con una sola sentencia SQL, sin punto y coma final si no es necesario.
""".strip()

# Ejemplos few-shot (conjunto de ENTRENAMIENTO). Deben ser disjuntos de las
# preguntas de evaluación de eval/ground_truth_olist.json: lo comprueba
# tests/test_fewshot_disjunto.py con eval/similitud.py.
EJEMPLOS_FEW_SHOT: list[tuple[str, str]] = [
    (
        '¿Cuántos clientes tenemos?',
        'SELECT COUNT(DISTINCT customer_unique_id) FROM customers',
    ),
    (
        '¿Cuántos días tardan en promedio los clientes en recibir respuesta a su reseña?',
        'SELECT ROUND(AVG(julianday(review_answer_timestamp) - julianday(review_creation_date)), 2) AS dias_promedio FROM order_reviews WHERE review_answer_timestamp IS NOT NULL',
    ),
    (
        '¿Cuántos productos distintos hay en cada categoría (en inglés)?',
        'SELECT COALESCE(t.product_category_name_english, p.product_category_name) AS categoria, COUNT(*) AS productos FROM products p LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name GROUP BY categoria ORDER BY productos DESC LIMIT 10',
    ),
    (
        '¿Cuáles son mis clientes recurrentes?',
        'SELECT * FROM vw_clientes_recurrentes WHERE es_recurrente = 1',
    ),
    (
        '¿Cuántos vendedores hay en cada estado?',
        'SELECT seller_state, COUNT(*) AS vendedores FROM sellers GROUP BY seller_state ORDER BY vendedores DESC',
    ),
    (
        '¿Qué porcentaje de las reseñas es de 1 o 2 estrellas, por año de compra?',
        "SELECT strftime('%Y', o.order_purchase_timestamp) AS anio, ROUND(100.0 * AVG(CASE WHEN rv.review_score <= 2 THEN 1 ELSE 0 END), 2) AS pct_1_2_estrellas FROM order_reviews rv JOIN orders o ON o.order_id = rv.order_id GROUP BY anio ORDER BY anio",
    ),
    (
        '¿Desde cuántos días de demora empiezan a bajar las reseñas?',
        'SELECT rango_retraso, calificacion_promedio, pct_1_2_estrellas FROM vw_retraso_por_rango ORDER BY orden',
    ),
    (
        '¿En qué estados el flete pesa más sobre el precio de los productos?',
        "SELECT v.customer_state, ROUND(SUM(v.freight_value) * 1.0 / SUM(v.price), 4) AS ratio_flete_precio FROM vw_ventas_pedido v WHERE v.order_status NOT IN ('canceled','unavailable') GROUP BY v.customer_state ORDER BY ratio_flete_precio DESC LIMIT 10",
    ),
    (
        '¿En qué categorías el flete pesa más sobre lo que se cobra por el producto?',
        'SELECT categoria_ingles, flete_total, ingresos, ratio_flete_ingresos FROM vw_ingresos_por_categoria ORDER BY ratio_flete_ingresos DESC LIMIT 10',
    ),
    (
        '¿En qué combinaciones de estado y categoría el flete pesa más sobre el precio?',
        "SELECT v.customer_state, v.categoria_ingles, ROUND(SUM(v.freight_value) * 1.0 / SUM(v.price), 4) AS ratio_flete_precio FROM vw_ventas_pedido v WHERE v.order_status NOT IN ('canceled','unavailable') GROUP BY v.customer_state, v.categoria_ingles HAVING COUNT(*) >= 30 ORDER BY ratio_flete_precio DESC LIMIT 10",
    ),
    (
        '¿Qué categorías concentran el 80% de los ingresos?',
        'SELECT categoria_ingles, ingresos FROM (SELECT categoria_ingles, ingresos, SUM(ingresos) OVER (ORDER BY ingresos DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) - ingresos AS acumulado_previo, SUM(ingresos) OVER () AS total FROM vw_ingresos_por_categoria) WHERE acumulado_previo < 0.8 * total ORDER BY ingresos DESC',
    ),
    (
        '¿Cuántos vendedores concentran el 80% de los ingresos?',
        'SELECT COUNT(*) AS vendedores_que_forman_el_80pct FROM (SELECT seller_id, SUM(ingresos) OVER (ORDER BY ingresos DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) - ingresos AS acumulado_previo, SUM(ingresos) OVER () AS total FROM vw_ingresos_por_vendedor) WHERE acumulado_previo < 0.8 * total',
    ),
]

EJEMPLOS_TEXTO = "Ejemplos de pregunta -> SQL correcto:\n\n" + "\n\n".join(
    f"Pregunta: {q}\nSQL: {sql}" for q, sql in EJEMPLOS_FEW_SHOT
)


def _valores_categoricos(table, col) -> list[str] | None:
    """Para columnas tipo-enum (documentadas con 'a | b | c' en su comment),
    consulta los valores DISTINCT reales en la BD -- el comment en models.py
    puede quedar desactualizado o ser solo un ejemplo ('Ej: ...'), pero los
    datos reales sembrados son la fuente de verdad que necesita el modelo
    para no adivinar texto "humano" (ej. 'Luz') en vez del valor real
    almacenado (ej. 'luz', 'nomina_general')."""
    if not col.comment or "|" not in col.comment:
        return None
    try:
        with engine.connect() as conn:
            filas = conn.execute(
                text(
                    f"SELECT DISTINCT {col.name} FROM {table.name} "
                    f"WHERE {col.name} IS NOT NULL ORDER BY {col.name} LIMIT 30"
                )
            ).fetchall()
        return [str(f[0]) for f in filas]
    except Exception:
        return None


def _valores_categoricos_texto() -> str | None:
    lineas = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            valores = _valores_categoricos(table, col)
            if valores:
                lineas.append(f"- {table.name}.{col.name}: {', '.join(valores)}")
    if not lineas:
        return None
    return (
        "Valores REALES (exactos, snake_case, tal cual están almacenados) de "
        "columnas tipo-enum -- úsalos literalmente en filtros WHERE, no los "
        "traduzcas ni capitalices ni les quites/pongas acentos:\n" + "\n".join(lineas)
    )


def _tipo_corto(declarado: str) -> str:
    """Tipo SQLite legible y corto a partir del tipo declarado (VARCHAR(32) ->
    TEXT, NUMERIC(10, 2) -> NUMERIC, ...). '' si no hay tipo declarado."""
    t = declarado.upper()
    if not t:
        return ""
    if "INT" in t:
        return "INTEGER"
    if "BOOL" in t:
        return "INTEGER 0/1"
    if any(x in t for x in ("CHAR", "TEXT", "CLOB", "STRING")):
        return "TEXT"
    if "DATE" in t or "TIME" in t:
        return "DATETIME"
    if any(x in t for x in ("NUMERIC", "DECIMAL")):
        return "NUMERIC"
    if any(x in t for x in ("REAL", "FLOA", "DOUB")):
        return "REAL"
    return t


def _column_line(col) -> str:
    parts = [col.name]
    if col.primary_key:
        parts.append("PK")
    fks = list(col.foreign_keys)
    if fks:
        target = next(iter(fks)).target_fullname
        parts.append(f"FK->{target}")
    if col.nullable and not col.primary_key:
        parts.append("NULL?")
    parts.append(_tipo_corto(col.type.compile(dialect=engine.dialect)))
    return " ".join(parts)


def _tipo_por_valor(valor) -> str:
    if isinstance(valor, bool) or isinstance(valor, int):
        return "INTEGER"
    if isinstance(valor, float):
        return "REAL"
    return "TEXT"


def _vista_line(nombre: str) -> str:
    """`- vista(col TIPO, ...) -- descripción`. El tipo es el declarado en la
    base; si la columna es una expresión sin tipo declarado, se infiere del
    primer valor no nulo de una muestra (o de TIPOS_SEMANTICOS_VISTAS)."""
    with engine.connect() as conn:
        info = conn.execute(text(f"PRAGMA table_info({nombre})")).fetchall()
        muestra = conn.execute(text(f"SELECT * FROM {nombre} LIMIT 200")).fetchall()
    cols = []
    for i, fila_info in enumerate(info):
        col = fila_info[1]
        tipo = TIPOS_SEMANTICOS_VISTAS.get((nombre, col)) or _tipo_corto(fila_info[2] or "")
        if not tipo:
            no_nulo = next((f[i] for f in muestra if f[i] is not None), None)
            tipo = _tipo_por_valor(no_nulo) if no_nulo is not None else ""
        cols.append(f"{col} {tipo}".strip())
    return f"- {nombre}({', '.join(cols)}) -- {VISTAS_DESCRIPCION[nombre]}"


def _vistas_texto() -> str:
    lineas = ["Vistas analíticas disponibles (úsalas en vez de recalcular a mano cuando aplique):"]
    lineas.extend(_vista_line(v) for v in NOMBRES_VISTAS)
    return "\n".join(lineas)


_CACHED_ESQUEMA: dict[str, set[str]] | None = None


def get_esquema_real() -> dict[str, set[str]]:
    """{tabla_o_vista_en_minúsculas: {columnas en minúsculas}} leído de la base
    real con PRAGMA table_info (tablas de la metadata + vistas analíticas).
    Es la fuente de verdad que usa llm/sql_guard.py para rechazar columnas
    inexistentes ANTES de ejecutar el SQL."""
    global _CACHED_ESQUEMA
    if _CACHED_ESQUEMA is None:
        _verificar_bd_existe()
        nombres = [t.name for t in Base.metadata.sorted_tables] + list(NOMBRES_VISTAS)
        esquema: dict[str, set[str]] = {}
        with engine.connect() as conn:
            for nombre in nombres:
                filas = conn.execute(text(f"PRAGMA table_info({nombre})")).fetchall()
                if filas:
                    esquema[nombre.lower()] = {str(f[1]).lower() for f in filas}
        _CACHED_ESQUEMA = esquema
    return _CACHED_ESQUEMA


# Columnas que sirven de llave de unión. Se listan explícitamente qué tablas/vistas
# tienen cada una porque el modelo confunde dónde vive cada llave (ej. asume
# `orders.seller_id`, que no existe: seller_id está en order_items).
COLUMNAS_UNION = ["order_id", "customer_id", "customer_unique_id", "seller_id", "product_id", "product_category_name"]


def _columnas_de_union_texto() -> str:
    esquema = get_esquema_real()
    lineas = [
        "Columnas de unión (JOIN) -- SOLO las tablas/vistas listadas tienen cada columna; en las demás NO existe:"
    ]
    for col in COLUMNAS_UNION:
        donde = [t for t in esquema if col in esquema[t]]
        lineas.append(f"- {col}: {', '.join(donde)}")
    lineas.append(
        "- Ejemplos de columnas que NO existen: orders.seller_id, orders.product_id, order_reviews.seller_id, "
        "customers.order_id, sellers.order_id, vw_ingresos_por_vendedor.order_id. "
        "Para llegar a un vendedor desde un pedido pasa por order_items (order_items.order_id = orders.order_id "
        "y order_items.seller_id = sellers.seller_id) o usa vw_ventas_pedido / vw_ingresos_por_vendedor."
    )
    lineas.append(
        "- Une SOLO columnas del mismo dominio (order_id con order_id, seller_id con seller_id, "
        "customer_id con customer_id). NUNCA order_id = seller_id ni ninguna otra combinación cruzada."
    )
    lineas.append(
        "- Nunca uses palabras reservadas de SQL como alias (or, and, in, is, on, as, by, group, order, ...). "
        "Alias sugeridos: order_reviews -> rv, orders -> o, order_items -> oi."
    )
    return "\n".join(lineas)


def get_known_names() -> set[str]:
    """Nombres de tablas + vistas conocidas por el esquema, para que
    llm/sql_guard.py pueda rechazar SQL que referencia algo inexistente."""
    return {t.name for t in Base.metadata.sorted_tables} | set(NOMBRES_VISTAS)


def build_schema_context() -> str:
    """Devuelve el esquema compacto en texto plano, listo para insertarse en el prompt del sistema."""
    _verificar_bd_existe()
    lines = ["Tablas disponibles (SQLite):", ""]
    for table in Base.metadata.sorted_tables:
        cols = ", ".join(_column_line(c) for c in table.columns)
        lines.append(f"{table.name}({cols})")
    lines.append("")
    lines.append(_vistas_texto())
    lines.append("")
    lines.append(_columnas_de_union_texto())

    valores_texto = _valores_categoricos_texto()
    if valores_texto:
        lines.append("")
        lines.append(valores_texto)

    lines.append("")
    lines.append(NOTAS_TEXTO)
    lines.append("")
    lines.append(EJEMPLOS_TEXTO)
    return "\n".join(lines)


# Se calcula una sola vez por proceso (el esquema no cambia en tiempo de ejecución).
_CACHED_CONTEXT: str | None = None


def get_schema_context() -> str:
    global _CACHED_CONTEXT
    if _CACHED_CONTEXT is None:
        _CACHED_CONTEXT = build_schema_context()
    return _CACHED_CONTEXT


if __name__ == "__main__":
    ctx = get_schema_context()
    print(ctx)
    print(f"\n--- ~{len(ctx.split())} palabras, {len(ctx)} caracteres ---")
