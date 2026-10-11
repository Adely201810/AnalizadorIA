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

import os
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Ejecutado como script (`python llm/schema_context.py`): Python pone llm/ en
    # sys.path en vez de la raíz del proyecto, y `import db` fallaría (P2).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
# --- Etapa 2, Paso 3: mejoras con interruptor. Solo (b) quedó ENCENDIDA por defecto (A/B 5 -> 8.33,
# D-25; TEXT2SQL_VISTA_VALIDOS=0 la apaga). c, d1, d2 y d3 empeoraron y siguen APAGADAS (docs/E2_PASO_3.md) ---
#   (b)  TEXT2SQL_VISTA_VALIDOS=1      lista vw_pedidos_validos + regla de partir de ella
#   (c)  TEXT2SQL_REGLA_DENOMINADOR=1  regla de denominadores + 2 few-shot genéricos
#   (d1) TEXT2SQL_VISTAS_DOC=1         grano, uso y columnas que NO tiene cada vista
#   (d2) TEXT2SQL_VISTAS_OCULTAS=a,b   quita esas vistas del contexto (y notas/ejemplos que las nombran)
#   (d3) TEXT2SQL_REGLA_MULTIPLICIDAD=1 regla contra JOINs que multiplican filas + 1 few-shot genérico
USAR_VISTA_VALIDOS = os.environ.get("TEXT2SQL_VISTA_VALIDOS", "1") == "1"
USAR_REGLA_DENOMINADOR = os.environ.get("TEXT2SQL_REGLA_DENOMINADOR", "0") == "1"
USAR_VISTAS_DOC = os.environ.get("TEXT2SQL_VISTAS_DOC", "0") == "1"
VISTAS_OCULTAS = {v.strip() for v in os.environ.get("TEXT2SQL_VISTAS_OCULTAS", "").split(",") if v.strip()}
USAR_REGLA_MULTIPLICIDAD = os.environ.get("TEXT2SQL_REGLA_MULTIPLICIDAD", "0") == "1"

if USAR_VISTA_VALIDOS:
    VISTAS_DESCRIPCION["vw_pedidos_validos"] = (
        "UNA fila por pedido VÁLIDO (ya excluye canceled/unavailable), con customer_unique_id y customer_state"
    )
VISTAS_EN_PROMPT = [v for v in VISTAS_DESCRIPCION if v not in VISTAS_OCULTAS]
# Para validar SQL se conocen todas las vistas que existen en la base, estén o no en el prompt.
NOMBRES_VISTAS = list(dict.fromkeys(list(VISTAS_DESCRIPCION) + ["vw_pedidos_validos"]))

# (d1) Para qué sirve cada vista y qué columnas NO tiene (las que el modelo le pedía por error).
USO_VISTAS = {
    "vw_ventas_pedido": "úsala para sumar/contar a nivel de artículo con categoría y estados ya unidos; trae TODOS los estatus (filtra order_status si la pregunta pide pedidos válidos)",
    "vw_clientes_recurrentes": "YA AGREGADA: 1 fila por cliente único con sus pedidos válidos; solo sirve para preguntas por cliente",
    "vw_entregas_retrasos": "1 fila por pedido entregado; para retrasos y su calificación",
    "vw_ingresos_por_categoria": "YA AGREGADA: 1 fila por categoría con totales; no se filtra por estatus ni se vuelve a sumar price",
    "vw_ingresos_por_vendedor": "YA AGREGADA: 1 fila por vendedor con totales; no se filtra por estatus ni se vuelve a sumar price",
    "vw_retraso_por_rango": "YA AGREGADA: 1 fila por rango de días de retraso",
    "vw_pedidos_validos": "1 fila por pedido válido; punto de partida para cualquier pregunta sobre pedidos válidos",
}
COLUMNAS_FRECUENTES = ["order_id", "order_status", "price", "freight_value", "customer_unique_id", "customer_state",
                       "seller_id", "seller_city", "review_score", "order_purchase_timestamp"]

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
- `vw_retraso_por_rango` trae, por cada rango de días de retraso (a_tiempo, 1-3, 4-7, 8-14, 15+), los pedidos, la calificación promedio y la proporción de calificaciones bajas (1-2 estrellas); ordénala por `orden` y usa sus columnas tal cual, sin re-agregar `review_score_promedio` en otra tabla.
- `orders.order_delivered_customer_date` y otras fechas de `orders` pueden ser NULL si el pedido no llegó a esa etapa (ej. cancelado). Filtra con IS NOT NULL para hablar de tiempos de entrega.
- `order_reviews.review_id` no es único y un pedido puede tener varias reseñas; para "la calificación de un pedido" usa AVG(review_score) agrupado por order_id (o la vista vw_ventas_pedido/vw_entregas_retrasos, que ya lo resuelven).
- `products.product_category_name` no tiene FK formal a `product_category_translation` (traducción incompleta); únelas con LEFT JOIN, nunca JOIN.
- El monto realmente pagado de un pedido está en `order_payments.payment_value`, no en `order_items.price + freight_value`.
- El flete de un pedido es `freight_value` en `order_items`, NUNCA `payment_value` de `order_payments` (eso es el monto pagado, no el costo de envío).
- "Estado" en sentido geográfico = `customer_state`/`seller_state` (estados de Brasil, ej. SP, RJ). NUNCA confundir con `order_status` (estatus del pedido: delivered/shipped/canceled/...). Usa `order_status` solo cuando la pregunta hable explícitamente de estatus/status del pedido.
- "Ingresos" = SUM(price) excluyendo pedidos con order_status IN ('canceled','unavailable') -- un pedido cancelado no es ingreso real. Las vistas vw_ingresos_por_categoria/vw_ingresos_por_vendedor ya aplican esta exclusión, úsalas de preferencia.
- El flete como proporción de las ventas se calcula SUM(freight_value) / SUM(price) (agregado; o `ratio_flete_ingresos` de las vistas), nunca con `payment_value`, y NUNCA como promedio de la razón por pedido (AVG(freight_value/price)) -- eso pondera mal los pedidos baratos.
- Los datos de Olist cubren pedidos de 2016 a 2018 (no hay datos de años posteriores ni anteriores). Si preguntan por un periodo fuera de ese rango, lo correcto es decir que no hay registros para ese periodo, sin inventar una cifra.
- Solo se ejecutan consultas SELECT. Nunca generes INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/ATTACH.
- Responde con una sola sentencia SQL, sin punto y coma final si no es necesario.
""".strip()

# Ejemplos few-shot (conjunto de ENTRENAMIENTO). Deben ser disjuntos de las
# preguntas de evaluación de eval/ground_truth_olist.json: lo comprueba
# tests/test_fewshot_disjunto.py con eval/similitud.py.
EJEMPLOS_FEW_SHOT: list[tuple[str, str]] = [
    # Cada ejemplo enseña una TÉCNICA (conteo de clientes únicos, julianday,
    # LEFT JOIN a la traducción, promedio por pedido, literal de enum, razón de
    # sumas, ranking, ventana) sobre una métrica que NO es ninguna de las 10
    # necesidades del oráculo (docs/FASE_05.md, decisión D-10).
    (
        '¿Cuántos clientes tenemos?',
        'SELECT COUNT(DISTINCT customer_unique_id) FROM customers',
    ),
    (
        '¿Cuántos días tardan en promedio los clientes en recibir respuesta a su reseña?',
        'SELECT ROUND(AVG(julianday(review_answer_timestamp) - julianday(review_creation_date)), 2) AS dias_promedio FROM order_reviews WHERE review_answer_timestamp IS NOT NULL',
    ),
    (
        '¿Cuántas fotos tienen en promedio los productos de cada categoría (en inglés)?',
        'SELECT COALESCE(t.product_category_name_english, p.product_category_name) AS categoria, ROUND(AVG(p.product_photos_qty), 2) AS fotos_promedio FROM products p LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name GROUP BY categoria ORDER BY fotos_promedio DESC LIMIT 10',
    ),
    (
        '¿Cuánto gasta en total, en promedio, cada cliente único?',
        'SELECT ROUND(AVG(gasto_total), 2) AS gasto_promedio FROM vw_clientes_recurrentes',
    ),
    (
        '¿Cuántos artículos tiene en promedio un pedido?',
        'SELECT ROUND(AVG(articulos), 2) AS articulos_promedio FROM (SELECT order_id, COUNT(*) AS articulos FROM order_items GROUP BY order_id)',
    ),
    (
        '¿Cuántas cuotas usan en promedio los pagos con tarjeta de crédito?',
        "SELECT ROUND(AVG(payment_installments), 2) AS cuotas_promedio FROM order_payments WHERE payment_type = 'credit_card'",
    ),
    (
        '¿Cuántos días pasan, como promedio, entre la compra y el momento en que la transportista recibe el pedido?',
        'SELECT ROUND(AVG(julianday(order_delivered_carrier_date) - julianday(order_purchase_timestamp)), 2) AS dias_promedio FROM orders WHERE order_delivered_carrier_date IS NOT NULL',
    ),
    (
        '¿Qué porcentaje del valor total pagado se pagó con voucher?',
        "SELECT ROUND(100.0 * SUM(CASE WHEN payment_type = 'voucher' THEN payment_value ELSE 0 END) / SUM(payment_value), 2) AS pct_voucher FROM order_payments",
    ),
    (
        '¿Cuáles son las 5 ciudades con más clientes únicos?',
        'SELECT customer_city, COUNT(DISTINCT customer_unique_id) AS clientes FROM customers GROUP BY customer_city ORDER BY clientes DESC LIMIT 5',
    ),
    (
        '¿Cuáles son los 5 productos con más artículos vendidos y en qué posición del ranking está cada uno?',
        'SELECT product_id, COUNT(*) AS articulos, RANK() OVER (ORDER BY COUNT(*) DESC) AS posicion FROM order_items GROUP BY product_id ORDER BY posicion LIMIT 5',
    ),
]

REGLA_VISTA_VALIDOS = (
    "- PEDIDOS VÁLIDOS: cuando la pregunta hable de pedidos válidos (sin cancelados ni no disponibles), "
    "parte de la vista vw_pedidos_validos en lugar de orders y únela por order_id a order_items, "
    "order_payments u order_reviews. Así el filtro de estatus ya está aplicado y no hay que repetirlo."
)
REGLA_DENOMINADOR = (
    "- PORCENTAJES: calcula numerador y denominador sobre el MISMO conjunto que nombra la pregunta, en una sola "
    "consulta: AVG(CASE WHEN <condición> THEN 100.0 ELSE 0 END) sobre UNA fila por unidad (si la unidad es el "
    "cliente o el pedido, agrega antes por esa unidad o usa COUNT(DISTINCT ...)). El universo de la pregunta va en el WHERE o en el FROM; la condición del "
    "numerador va SOLO en el CASE. Si pones la condición del numerador en el WHERE, el resultado es 100 %."
)
REGLA_MULTIPLICIDAD = (
    "- NO MULTIPLIQUES FILAS: order_items, order_payments y order_reviews tienen VARIAS filas por pedido. Si unes "
    "dos de ellas (o una con otra tabla por order_id) cada pedido se repite y las sumas, promedios y conteos salen "
    "inflados. Primero agrega cada tabla por order_id en una subconsulta o CTE (una fila por pedido) y después "
    "únelas. Para contar pedidos, clientes o vendedores usa COUNT(DISTINCT ...), nunca COUNT(*) sobre un JOIN."
)
# Ejemplos genéricos (distintos de DESARROLLO y PRUEBA: tests/test_fewshot_disjunto.py y tests/test_heldout.py).
EJEMPLOS_DENOMINADOR: list[tuple[str, str]] = [
    (
        'Entre los registros de geolocalización del estado PR, ¿qué parte (en por ciento) pertenece a la ciudad de curitiba?',
        "SELECT ROUND(AVG(CASE WHEN geolocation_city = 'curitiba' THEN 100.0 ELSE 0 END), 2) AS pct FROM geolocation WHERE geolocation_state = 'PR'",
    ),
    (
        'Entre los pagos hechos con tarjeta de crédito, ¿qué parte (en por ciento) se dividió en más de 6 cuotas?',
        "SELECT ROUND(AVG(CASE WHEN payment_installments > 6 THEN 100.0 ELSE 0 END), 2) AS pct FROM order_payments WHERE payment_type = 'credit_card'",
    ),
]
EJEMPLOS_MULTIPLICIDAD: list[tuple[str, str]] = [
    (
        '¿Cuánto se pagó en promedio por los pedidos que tienen exactamente 2 artículos?',
        'WITH art AS (SELECT order_id, COUNT(*) AS n FROM order_items GROUP BY order_id), pag AS (SELECT order_id, SUM(payment_value) AS total FROM order_payments GROUP BY order_id) SELECT ROUND(AVG(pag.total), 2) AS pago_promedio FROM art JOIN pag ON pag.order_id = art.order_id WHERE art.n = 2',
    ),
]
if VISTAS_OCULTAS:
    EJEMPLOS_FEW_SHOT = [(q, s) for q, s in EJEMPLOS_FEW_SHOT if not any(v in s for v in VISTAS_OCULTAS)]
if USAR_REGLA_DENOMINADOR:
    EJEMPLOS_FEW_SHOT = EJEMPLOS_FEW_SHOT + EJEMPLOS_DENOMINADOR
if USAR_REGLA_MULTIPLICIDAD:
    EJEMPLOS_FEW_SHOT = EJEMPLOS_FEW_SHOT + EJEMPLOS_MULTIPLICIDAD

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
    for v in VISTAS_EN_PROMPT:
        lineas.append(_vista_line(v))
        if USAR_VISTAS_DOC:
            cols = get_esquema_real().get(v, set())
            faltan = [c for c in COLUMNAS_FRECUENTES if c not in cols]
            lineas.append(f"    uso: {USO_VISTAS.get(v, '')}. NO tiene: {', '.join(faltan) or '(nada relevante)'}.")
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
    visibles = [t for t in esquema if not t.startswith("vw_") or t in VISTAS_EN_PROMPT]
    for col in COLUMNAS_UNION:
        donde = [t for t in visibles if col in esquema[t]]
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


def _sin_vistas_ocultas(linea: str) -> str:
    """(d2) Quita de una nota las frases que nombran una vista oculta. Si la nombra la primera
    frase, se quita la nota entera (las siguientes dependen de ella); '' si no queda nada."""
    if not any(v in linea for v in VISTAS_OCULTAS):
        return linea
    frases = re.split(r"(?<=\.) ", linea.removeprefix("- "))
    if any(v in frases[0] for v in VISTAS_OCULTAS):
        return ""
    quedan = [f for f in frases if not any(v in f for v in VISTAS_OCULTAS)]
    return "- " + " ".join(quedan)


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
    notas = NOTAS_TEXTO
    if VISTAS_OCULTAS:
        notas = "\n".join(_sin_vistas_ocultas(l) for l in notas.splitlines() if _sin_vistas_ocultas(l))
    lines.append(notas)
    if USAR_VISTA_VALIDOS:
        lines.append(REGLA_VISTA_VALIDOS)
    if USAR_REGLA_DENOMINADOR:
        lines.append(REGLA_DENOMINADOR)
    if USAR_REGLA_MULTIPLICIDAD:
        lines.append(REGLA_MULTIPLICIDAD)
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
