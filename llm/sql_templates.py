"""
Plantillas SQL fijas para patrones donde el LLM de 8B genera SQL plausible pero
semánticamente roto, aunque se le den ejemplos en el prompt:

  - Concentración / Pareto ("¿cuántos vendedores concentran el 80% de los
    ingresos?"): el modelo filtra `> 80` sobre el % individual en vez de armar
    un acumulado con ventana.
  - Series de tiempo mensuales ("ventas mes a mes", "meses incompletos",
    "crecimiento de 2017 a 2018"): el modelo devuelve pedidos sueltos sin GROUP BY.

La intención se detecta por REGLAS (palabras clave sobre la pregunta
normalizada, sin acentos) y, si hay coincidencia, el pipeline ejecuta la
plantilla en vez de pedirle el SQL al modelo. Si ninguna regla aplica, todo
sigue igual (generación libre + validación de llm/sql_guard.py).

Aparte hay plantillas de FALLBACK sobre vistas precalculadas
(`plantilla_fallback`): se usan solo cuando el SQL del LLM ya falló tras el
reintento (ej. joins con columnas inexistentes al armar "vendedores").

Todas las plantillas pasan por los mismos validadores y por la conexión
solo-lectura que el SQL generado por el modelo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Filas que se le muestran al modelo al sintetizar esta plantilla (una serie
# mensual de ~24 filas no debe truncarse a las primeras 15 y perder 2018).
LIMITE_SINTESIS_SERIE = 30

_PEDIDO_VALIDO = "order_status NOT IN ('canceled', 'unavailable')"


@dataclass(frozen=True)
class Plantilla:
    nombre: str
    sql: str
    subpregunta: str  # cómo se titula si la pregunta se descompone en varias plantillas
    limite_sintesis: int | None = None  # None = límite por defecto del pipeline


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos, para que las reglas no dependan de tildes."""
    sin_acentos = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# 1. Concentración (Pareto)
# ---------------------------------------------------------------------------

_CONCENTRACION_RE = re.compile(r"concentr|pareto|\btop\s*\d+(?:[.,]\d+)?\s*%|acumulad")
_TOP_PCT_RE = re.compile(r"\btop\s*(\d+(?:[.,]\d+)?)\s*%")
_PORCENTAJE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")

# entidad -> (etiqueta en el resultado, vista agregada, columna llave)
_ENTIDADES_PARETO = {
    "categorias": ("categorias", "vw_ingresos_por_categoria", "categoria_ingles"),
    "vendedores": ("vendedores", "vw_ingresos_por_vendedor", "seller_id"),
}


def _numero(texto: str) -> float:
    return float(texto.replace(",", "."))


def _sql_pareto_n_entidades(etiqueta: str, vista: str, llave: str, umbral: float) -> str:
    """¿Cuántas entidades (las de mayores ingresos primero) hacen falta para
    acumular al menos `umbral`% del total? Una entidad hace falta si lo acumulado
    ANTES de ella todavía no llega al umbral. Ventana con ROWS y desempate por la
    llave para que los empates no se agrupen (el frame por defecto es RANGE)."""
    return f"""
WITH base AS (
    SELECT {llave}, ingresos FROM {vista} WHERE ingresos > 0
),
ordenado AS (
    SELECT {llave}, ingresos,
           SUM(ingresos) OVER (ORDER BY ingresos DESC, {llave}
                               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS acumulado,
           SUM(ingresos) OVER () AS total
    FROM base
)
SELECT '{etiqueta}' AS entidad,
       {umbral:g} AS umbral_pct,
       COUNT(*) AS entidades_necesarias,
       (SELECT COUNT(*) FROM base) AS total_entidades,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM base), 2) AS pct_de_las_entidades,
       ROUND(MAX(100.0 * acumulado / total), 2) AS pct_de_ingresos_acumulado
FROM ordenado
WHERE (acumulado - ingresos) * 100.0 / total < {umbral:g}""".strip()


def _sql_pareto_top_pct(etiqueta: str, vista: str, llave: str, top_pct: float) -> str:
    """¿Qué % de los ingresos concentra el `top_pct`% de entidades con más ingresos?"""
    return f"""
WITH base AS (
    SELECT {llave}, ingresos FROM {vista} WHERE ingresos > 0
),
ordenado AS (
    SELECT {llave}, ingresos,
           ROW_NUMBER() OVER (ORDER BY ingresos DESC, {llave}) AS posicion,
           COUNT(*) OVER () AS total_entidades,
           SUM(ingresos) OVER () AS total
    FROM base
)
SELECT '{etiqueta}' AS entidad,
       {top_pct:g} AS top_pct,
       MAX(CAST(total_entidades * {top_pct:g} / 100.0 + 0.999999 AS INTEGER)) AS entidades_en_el_top,
       MAX(total_entidades) AS total_entidades,
       ROUND(100.0 * SUM(ingresos) / MAX(total), 2) AS pct_de_ingresos_del_top
FROM ordenado
WHERE posicion <= CAST(total_entidades * {top_pct:g} / 100.0 + 0.999999 AS INTEGER)""".strip()


def _plantilla_concentracion(n: str) -> Plantilla | None:
    if not _CONCENTRACION_RE.search(n):
        return None
    entidades = []
    if "vendedor" in n or "seller" in n:
        entidades.append(_ENTIDADES_PARETO["vendedores"])
    if "categor" in n:
        entidades.append(_ENTIDADES_PARETO["categorias"])
    if not entidades:
        return None  # no se sabe qué entidad concentra: se deja al LLM

    top = _TOP_PCT_RE.search(n)
    if top:
        valor = _numero(top.group(1))
        if not 0 < valor < 100:
            return None
        partes = [_sql_pareto_top_pct(*e, valor) for e in entidades]
        nombre = "concentracion_top_pct"
    else:
        pct = _PORCENTAJE_RE.search(n)
        valor = _numero(pct.group(1)) if pct else 80.0  # "pocas" sin cifra -> regla 80/20
        if not 0 < valor < 100:
            return None
        partes = [_sql_pareto_n_entidades(*e, valor) for e in entidades]
        nombre = "concentracion_pareto"
    return Plantilla(
        nombre=nombre,
        sql="\nUNION ALL\n".join(f"SELECT * FROM ({p})" for p in partes),
        subpregunta="¿Qué tan concentrados están los ingresos?",
    )


# ---------------------------------------------------------------------------
# 2. Series de tiempo mensuales
# ---------------------------------------------------------------------------

_MES_RE = re.compile(r"\bmes(?:es)?\b|mensual|estacional")
_TEMA_VENTAS_RE = re.compile(r"venta|ingreso|pedido|factur|negocio|vend|compra")
_SERIE_RE = re.compile(r"mes a mes|mensual|por mes|cada mes|vari[ao]|evoluci|tendencia|estacional|comport")
_INCOMPLETO_RE = re.compile(r"incomplet|truncad|parcial|no representativ")
_CRECIMIENTO_RE = re.compile(r"\bcrec|interanual|anual|ano contra ano|\byoy\b")
_ANIO_RE = re.compile(r"\b(20\d\d)\b")

# Base compartida por las plantillas mensuales: pedidos válidos, un registro por
# línea de pedido. `pedidos` cuenta order_id DISTINTOS (vw_ventas_pedido tiene
# una fila por línea de pedido, así que COUNT(*) contaría líneas, no pedidos).
_BASE_MENSUAL = f"""
mensual AS (
    SELECT strftime('%Y-%m', order_purchase_timestamp) AS mes,
           COUNT(DISTINCT order_id) AS pedidos,
           ROUND(SUM(price), 2) AS ingresos,
           MIN(date(order_purchase_timestamp)) AS primer_dia,
           MAX(date(order_purchase_timestamp)) AS ultimo_dia
    FROM vw_ventas_pedido
    WHERE {_PEDIDO_VALIDO}
    GROUP BY mes
),
rango AS (
    SELECT MIN(mes) AS primer_mes, MAX(mes) AS ultimo_mes FROM mensual
)""".strip()

# "Mes incompleto" = primer y último mes del rango de datos (casi seguro
# truncados a mitad de mes); lo decide la regla, no el modelo.
SQL_SERIE_MENSUAL = f"""
WITH {_BASE_MENSUAL}
SELECT m.mes, m.pedidos, m.ingresos,
       CASE WHEN m.mes = r.primer_mes OR m.mes = r.ultimo_mes THEN 1 ELSE 0 END AS mes_incompleto
FROM mensual m, rango r
ORDER BY m.mes""".strip()

SQL_MESES_INCOMPLETOS = f"""
WITH {_BASE_MENSUAL}
SELECT m.mes, m.pedidos, m.ingresos, m.primer_dia, m.ultimo_dia,
       CASE WHEN m.mes = r.primer_mes THEN 'primer mes del rango de datos'
            ELSE 'ultimo mes del rango de datos' END AS motivo
FROM mensual m, rango r
WHERE m.mes = r.primer_mes OR m.mes = r.ultimo_mes
ORDER BY m.mes""".strip()


def _sql_crecimiento_anual(anio_base: int, anio_comp: int) -> str:
    """Crecimiento de `anio_base` a `anio_comp` comparando SOLO los meses que
    existen en ambos años y no son incompletos (primer/último mes del rango):
    comparar un 2018 recortado contra un 2017 completo inflaría el resultado."""
    return f"""
WITH {_BASE_MENSUAL},
comparables AS (
    SELECT substr(m.mes, 1, 4) AS anio, substr(m.mes, 6, 2) AS mm, m.pedidos, m.ingresos
    FROM mensual m, rango r
    WHERE m.mes > r.primer_mes AND m.mes < r.ultimo_mes
),
pares AS (
    SELECT a.pedidos AS pedidos_base, a.ingresos AS ingresos_base,
           b.pedidos AS pedidos_comparado, b.ingresos AS ingresos_comparado
    FROM comparables a JOIN comparables b ON b.mm = a.mm
    WHERE a.anio = '{anio_base}' AND b.anio = '{anio_comp}'
)
SELECT {anio_base} AS anio_base,
       {anio_comp} AS anio_comparado,
       COUNT(*) AS meses_comparados,
       ROUND(SUM(ingresos_base), 2) AS ingresos_{anio_base}_solo_meses_comparables,
       ROUND(SUM(ingresos_comparado), 2) AS ingresos_{anio_comp}_solo_meses_comparables,
       ROUND(100.0 * (SUM(ingresos_comparado) / SUM(ingresos_base) - 1), 2) AS crecimiento_ingresos_pct,
       SUM(pedidos_base) AS pedidos_{anio_base}_solo_meses_comparables,
       SUM(pedidos_comparado) AS pedidos_{anio_comp}_solo_meses_comparables,
       ROUND(100.0 * (SUM(pedidos_comparado) * 1.0 / SUM(pedidos_base) - 1), 2) AS crecimiento_pedidos_pct
FROM pares""".strip()


def _plantillas_temporales(n: str) -> list[Plantilla]:
    """Puede devolver varias: una pregunta compuesta ("...mes a mes, qué meses son
    incompletos y cómo creció de 2017 a 2018") se resuelve con una plantilla por parte."""
    hay_mes = bool(_MES_RE.search(n))
    if not hay_mes and not _CRECIMIENTO_RE.search(n):
        return []
    tema_ventas = bool(_TEMA_VENTAS_RE.search(n))

    encontradas: list[Plantilla] = []
    if hay_mes and tema_ventas and _SERIE_RE.search(n):
        encontradas.append(Plantilla(
            "serie_mensual", SQL_SERIE_MENSUAL,
            "¿Cómo varían las ventas mes a mes?", LIMITE_SINTESIS_SERIE,
        ))
    if hay_mes and _INCOMPLETO_RE.search(n):  # "¿qué meses son incompletos?" no menciona ventas
        encontradas.append(Plantilla(
            "meses_incompletos", SQL_MESES_INCOMPLETOS, "¿Qué meses son incompletos?",
        ))
    anios = _ANIO_RE.findall(n)
    if tema_ventas and _CRECIMIENTO_RE.search(n) and (anios or "ano" in n):
        base, comp = (int(anios[0]), int(anios[1])) if len(anios) >= 2 else (2017, 2018)
        if base > comp:
            base, comp = comp, base
        encontradas.append(Plantilla(
            "crecimiento_anual", _sql_crecimiento_anual(base, comp),
            f"¿Cómo creció el negocio de {base} a {comp}?",
        ))
    return encontradas


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def detectar_plantillas(pregunta: str) -> list[Plantilla]:
    """Plantillas cuyo patrón coincide con `pregunta` (lista vacía = generación
    libre por el LLM). Varias plantillas = pregunta compuesta, en el orden en que
    conviene presentarlas."""
    n = normalizar(pregunta)
    concentracion = _plantilla_concentracion(n)
    if concentracion:
        return [concentracion]
    return _plantillas_temporales(n)


# ---------------------------------------------------------------------------
# Fallbacks sobre vistas precalculadas (cuando el SQL del LLM ya falló)
# ---------------------------------------------------------------------------

SQL_VENDEDORES_TOP_INGRESOS = """
SELECT seller_id, seller_state, pedidos, ingresos
FROM vw_ingresos_por_vendedor
ORDER BY ingresos DESC
LIMIT 10""".strip()

# Vendedores del cuartil superior de ingresos (con volumen mínimo) que además
# tienen mala calificación o muchas entregas tardías. Umbrales iguales a los
# defaults del dashboard (q04): >=30 pedidos, calificación < 3.5, > 15% tardías.
# Calificación y retraso se miden por PEDIDO (no por línea) sobre pedidos entregados.
SQL_VENDEDORES_A_REVISAR = f"""
WITH por_vendedor AS (
    SELECT so.seller_id,
           COUNT(*) AS pedidos_entregados,
           ROUND(AVG(e.review_score_promedio), 2) AS calificacion_promedio,
           ROUND(100.0 * SUM(e.entrega_con_retraso) / COUNT(*), 2) AS pct_entregas_tardias
    FROM (SELECT DISTINCT seller_id, order_id FROM vw_ventas_pedido WHERE {_PEDIDO_VALIDO}) so
    JOIN vw_entregas_retrasos e ON e.order_id = so.order_id
    GROUP BY so.seller_id
),
cuartiles AS (
    SELECT seller_id, seller_state, ingresos,
           NTILE(4) OVER (ORDER BY ingresos DESC) AS cuartil_ingresos
    FROM vw_ingresos_por_vendedor
)
SELECT c.seller_id, c.seller_state, c.ingresos, p.pedidos_entregados,
       p.calificacion_promedio, p.pct_entregas_tardias
FROM cuartiles c
JOIN por_vendedor p ON p.seller_id = c.seller_id
WHERE c.cuartil_ingresos = 1
  AND p.pedidos_entregados >= 30
  AND (p.calificacion_promedio < 3.5 OR p.pct_entregas_tardias > 15)
ORDER BY c.ingresos DESC
LIMIT 20""".strip()


def plantilla_fallback(pregunta: str) -> Plantilla | None:
    """Plantilla de respaldo para preguntas sobre vendedores, basada en las
    vistas ya calculadas en vez de joins armados a mano por el modelo."""
    n = normalizar(pregunta)
    if "vendedor" not in n and "seller" not in n:
        return None
    if re.search(r"calificaci|resena|satisfac|tard|retras|revis|mala|peor|queja", n):
        return Plantilla(
            "vendedores_a_revisar", SQL_VENDEDORES_A_REVISAR,
            "¿Qué vendedores con muchos ingresos tienen mala calificación o entregas tardías?",
        )
    if re.search(r"ingres|venta|factur|vend[ea]n|\bmas\b|top", n):
        return Plantilla(
            "vendedores_top_ingresos", SQL_VENDEDORES_TOP_INGRESOS, "¿Qué vendedores generan más ingresos?",
        )
    return None
