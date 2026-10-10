"""
Genera el reporte PDF del dashboard de verificación (sin IA) en memoria.

Usa reportlab para el documento (portada, hoja de respuestas, una sección por
necesidad y notas metodológicas) y matplotlib (backend Agg, sin navegador ni
kaleido) para las 10 gráficas, guardadas como PNG en memoria y embebidas en
el PDF. No modifica app.py, llm/ ni eval/; se apoya únicamente en
dashboard/queries.py y en db/olist_database.py.

Uso típico (desde pages/1_Dashboard.py):
    from dashboard.pdf_report import generar_pdf_bytes
    pdf_bytes = generar_pdf_bytes()  # o generar_pdf_bytes(resultados_ya_calculados)
"""
from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")  # headless: nada de ventanas ni navegador/kaleido

import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from dashboard import queries as q
from db.olist_database import get_readonly_connection

# ---------------------------------------------------------------------------
# Formateo (mismas convenciones que dashboard/queries.py: R$ 1,234.56, %, etc.)
# ---------------------------------------------------------------------------


def _money(v) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"R$ {v:,.2f}"


def _pct(v) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v:.1f}%"


def _rating(v) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v:.2f}"


def _entero(v) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{int(v):,}"


def _seller_id_corto(v) -> str:
    return f"{str(v)[:8]}…"


def _si_no(v) -> str:
    return "Sí" if bool(v) else "No"


_FORMATEADORES = {
    "texto": lambda s: [str(v) for v in s],
    "money": lambda s: [_money(v) for v in s],
    "pct": lambda s: [_pct(v) for v in s],
    "rating": lambda s: [_rating(v) for v in s],
    "int": lambda s: [_entero(v) for v in s],
    "seller_id": lambda s: [_seller_id_corto(v) for v in s],
    "bool_si_no": lambda s: [_si_no(v) for v in s],
}


def _resumen_bd() -> dict:
    """Mismo resumen de cabecera que pages/1_Dashboard.py, calculado aparte
    (independiente) para que este módulo no dependa de un módulo de Streamlit."""
    conn = get_readonly_connection()
    try:
        cur = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM orders) AS total_pedidos,
                (SELECT COUNT(DISTINCT customer_unique_id) FROM customers) AS clientes_unicos,
                (SELECT COUNT(*) FROM sellers) AS vendedores,
                (SELECT COUNT(*) FROM products) AS productos,
                (SELECT MIN(order_purchase_timestamp) FROM orders) AS fecha_min,
                (SELECT MAX(order_purchase_timestamp) FROM orders) AS fecha_max
            """
        )
        columnas = [d[0] for d in cur.description]
        return dict(zip(columnas, cur.fetchone()))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Gráficas (matplotlib, en memoria)
# ---------------------------------------------------------------------------


def _fig_a_bytes(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _grafica_q01(r: dict) -> io.BytesIO:
    comp = r["tablas"]["comparacion_recurrentes_vs_no"].copy()
    comp["grupo"] = comp["es_recurrente"].map({0: "No recurrente", 1: "Recurrente"})
    fig, ax = plt.subplots(figsize=(6.3, 3.4))
    barras = ax.bar(comp["grupo"], comp["gasto_promedio"], color=["#B8C7DA", "#2E86DE"])
    for b in barras:
        ax.annotate(_money(b.get_height()), (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=8)
    ax.set_title("Gasto total promedio: recurrentes vs no recurrentes")
    ax.set_ylabel("Gasto promedio (R$)")
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q02(r: dict) -> io.BytesIO:
    t = r["tablas"]["retraso_vs_calificacion"].sort_values("orden")
    fig, ax1 = plt.subplots(figsize=(6.3, 3.5))
    ax1.bar(t["rango_retraso"], t["calificacion_promedio"], color="#2E86DE", label="Calificación promedio")
    ax1.set_ylabel("Calificación promedio (1-5)")
    ax1.set_ylim(0, 5)
    ax1.set_xlabel("Rango de retraso (días)")
    ax2 = ax1.twinx()
    ax2.plot(t["rango_retraso"], t["pct_1_2_estrellas"], color="#E74C3C", marker="o", label="% de 1-2 estrellas")
    ax2.set_ylabel("% de reseñas 1-2 estrellas")
    ax1.set_title("Calificación y % de reseñas negativas por rango de retraso")
    lineas1, etiquetas1 = ax1.get_legend_handles_labels()
    lineas2, etiquetas2 = ax2.get_legend_handles_labels()
    ax1.legend(lineas1 + lineas2, etiquetas1 + etiquetas2, loc="lower left", fontsize=8)
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q03(r: dict) -> io.BytesIO:
    cat = r["tablas"]["pareto_categorias"].sort_values("rango").head(15)
    vend = r["tablas"]["pareto_vendedores"].sort_values("rango").head(15)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6))
    for ax, df, titulo, es_categoria in [
        (axes[0], cat, "Categorías (top 15 por ingreso)", True),
        (axes[1], vend, "Vendedores (top 15 por ingreso)", False),
    ]:
        etiquetas = (
            df["categoria"].astype(str) if es_categoria else [_seller_id_corto(s) for s in df["seller_id"]]
        )
        ax.bar(range(len(df)), df["ingresos"], color="#2E86DE")
        ax.set_xticks(range(len(df)))
        ax.set_xticklabels(etiquetas, rotation=60, ha="right", fontsize=6)
        ax.set_ylabel("Ingresos (R$)", fontsize=8)
        ax_acum = ax.twinx()
        ax_acum.plot(range(len(df)), df["pct_acumulado"], color="#E74C3C", marker="o", markersize=3)
        ax_acum.set_ylim(0, 105)
        ax_acum.set_ylabel("% acumulado", fontsize=8)
        ax.set_title(titulo, fontsize=9)
    fig.suptitle("Curva de Pareto de ingresos", fontsize=11)
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q04(r: dict) -> io.BytesIO:
    t = r["tablas"]["vendedores"]
    fig, ax = plt.subplots(figsize=(6.3, 3.8))
    colores = t["vendedor_a_revisar"].map({True: "#E74C3C", False: "#2ECC71"})
    ax.scatter(t["ingresos"], t["calificacion_promedio"], c=colores, alpha=0.6, s=25)
    ax.set_xlabel("Ingresos (R$)")
    ax.set_ylabel("Calificación promedio (1-5)")
    ax.set_title("Vendedores: ingresos vs calificación")
    manejadores = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c, label=etiqueta, markersize=8)
        for c, etiqueta in [("#E74C3C", "A revisar"), ("#2ECC71", "OK")]
    ]
    ax.legend(handles=manejadores, loc="lower right", fontsize=8)
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q05(r: dict) -> io.BytesIO:
    t = r["tablas"]["flete_por_estado"].sort_values("pct_flete_sobre_precio", ascending=False)
    fig, ax = plt.subplots(figsize=(6.8, 3.4))
    ax.bar(t["customer_state"], t["pct_flete_sobre_precio"], color="#2E86DE")
    ax.set_ylabel("% flete / precio")
    ax.set_xlabel("Estado del cliente")
    ax.set_title("% de flete sobre precio por estado")
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right", fontsize=7)
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q06(r: dict) -> io.BytesIO:
    tipo = r["tablas"]["por_metodo_pago"]
    cuotas = r["tablas"]["ticket_por_rango_cuotas"].sort_values("orden")
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.4))
    axes[0].bar(tipo["payment_type"], tipo["ticket_promedio"], color="#2E86DE")
    axes[0].set_title("Ticket promedio por método de pago", fontsize=9)
    axes[0].set_ylabel("Ticket promedio (R$)")
    plt.setp(axes[0].get_xticklabels(), rotation=45, ha="right", fontsize=7)
    axes[1].bar(cuotas["rango_cuotas"], cuotas["ticket_promedio"], color="#F39C12")
    axes[1].set_title("Ticket promedio por rango de cuotas", fontsize=9)
    axes[1].set_xlabel("Cuotas")
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q07(r: dict) -> io.BytesIO:
    t = r["tablas"]["ingresos_por_mes"].sort_values("mes")
    fig, ax = plt.subplots(figsize=(7.8, 3.4))
    colores = ["#E74C3C" if excluido else "#2E86DE" for excluido in t["excluido"]]
    ax.plot(t["mes"], t["ingresos"], color="#2E86DE", linewidth=1.2, zorder=1)
    ax.scatter(t["mes"], t["ingresos"], c=colores, zorder=2, s=28)
    ax.set_title("Ingresos por mes (rojo = mes excluido por incompleto)")
    ax.set_ylabel("Ingresos (R$)")
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right", fontsize=6)
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q08(r: dict) -> io.BytesIO:
    t = r["tablas"]["insatisfaccion_por_categoria"]
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    mapa_color = {"problema_de_producto": "#E74C3C", "problema_logistico": "#F39C12", "otro": "#2ECC71"}
    for clase, color in mapa_color.items():
        sub = t[t["clasificacion"] == clase]
        if not sub.empty:
            ax.scatter(sub["pct_tardios"], sub["calificacion_promedio"], c=color, label=clase, alpha=0.7, s=25)
    if not t.empty:
        ax.axhline(t["calificacion_global"].iloc[0], color="gray", linestyle="--", linewidth=1)
        ax.axvline(t["pct_tardios_global"].iloc[0], color="gray", linestyle="--", linewidth=1)
    ax.set_xlabel("% de entregas tardías")
    ax.set_ylabel("Calificación promedio")
    ax.set_title("Categorías: calificación vs % de entregas tardías")
    ax.legend(fontsize=7, loc="lower left")
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q09(r: dict) -> io.BytesIO:
    cat = r["tablas"]["top_10_categorias_audiencia"]
    edo = r["tablas"]["top_10_estados_audiencia"]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6))
    axes[0].bar(cat["categoria"], cat["clientes"], color="#2E86DE")
    axes[0].set_title("Top 10 categorías", fontsize=9)
    plt.setp(axes[0].get_xticklabels(), rotation=60, ha="right", fontsize=6)
    axes[1].bar(edo["customer_state"], edo["clientes"], color="#8E44AD")
    axes[1].set_title("Top 10 estados", fontsize=9)
    fig.suptitle("Clientes de un solo pedido calificado con 5 estrellas", fontsize=10)
    fig.tight_layout()
    return _fig_a_bytes(fig)


def _grafica_q10(r: dict) -> io.BytesIO:
    t = r["tablas"]["oportunidad_por_estado"].dropna(subset=["clientes_por_vendedor"])
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    maximo = t["clientes_por_vendedor"].max() or 1
    tam = (t["clientes_por_vendedor"] / maximo) * 300 + 20
    ax.scatter(t["vendedores"], t["clientes"], s=tam, color="#2E86DE", alpha=0.6)
    for _, fila in t.iterrows():
        ax.annotate(fila["estado"], (fila["vendedores"], fila["clientes"]), fontsize=6,
                    xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("Vendedores activos")
    ax.set_ylabel("Clientes")
    ax.set_title("Clientes vs vendedores por estado (tamaño = clientes/vendedor)")
    fig.tight_layout()
    return _fig_a_bytes(fig)


_GENERADORES_GRAFICA = {
    1: _grafica_q01, 2: _grafica_q02, 3: _grafica_q03, 4: _grafica_q04, 5: _grafica_q05,
    6: _grafica_q06, 7: _grafica_q07, 8: _grafica_q08, 9: _grafica_q09, 10: _grafica_q10,
}


# ---------------------------------------------------------------------------
# Tabla resumen (máximo 10 filas) por necesidad
# ---------------------------------------------------------------------------

_TABLA_SPECS = {
    1: dict(
        obtener=lambda r: r["tablas"]["tasa_recompra_por_categoria"].sort_values(
            "tasa_recompra_pct", ascending=False
        ).head(10),
        titulo="Top 10 categorías por tasa de recompra",
        columnas=[
            ("categoria", "Categoría", "texto"),
            ("clientes", "Clientes", "int"),
            ("clientes_recurrentes", "Recurrentes", "int"),
            ("tasa_recompra_pct", "% recompra", "pct"),
        ],
        pesos=[2, 1, 1, 1],
    ),
    2: dict(
        obtener=lambda r: r["tablas"]["retraso_vs_calificacion"].sort_values("orden"),
        titulo="Calificación y reseñas negativas por rango de retraso",
        columnas=[
            ("rango_retraso", "Rango retraso", "texto"),
            ("pedidos", "Pedidos", "int"),
            ("calificacion_promedio", "Calificación", "rating"),
            ("pct_1_2_estrellas", "% 1-2 estrellas", "pct"),
        ],
        pesos=[1, 1, 1, 1],
    ),
    3: dict(
        obtener=lambda r: r["tablas"]["pareto_categorias"].sort_values("rango").head(10),
        titulo="Top 10 categorías por ingreso (curva de Pareto)",
        columnas=[
            ("categoria", "Categoría", "texto"),
            ("ingresos", "Ingresos", "money"),
            ("pct_ingresos", "% ingresos", "pct"),
            ("pct_acumulado", "% acumulado", "pct"),
        ],
        pesos=[2, 1, 1, 1],
    ),
    4: dict(
        obtener=lambda r: r["tablas"]["vendedores_a_revisar"].sort_values("ingresos", ascending=False).head(10),
        titulo="Vendedores marcados para revisión",
        columnas=[
            ("seller_id", "Vendedor", "seller_id"),
            ("ingresos", "Ingresos", "money"),
            ("calificacion_promedio", "Calificación", "rating"),
            ("pct_entregas_tardias", "% tardías", "pct"),
            ("pct_cancelados", "% cancelados", "pct"),
        ],
        pesos=[1.3, 1, 1, 1, 1],
    ),
    5: dict(
        obtener=lambda r: r["tablas"]["flete_por_estado"].sort_values(
            "pct_flete_sobre_precio", ascending=False
        ).head(10),
        titulo="Top 10 estados por % de flete sobre precio",
        columnas=[
            ("customer_state", "Estado", "texto"),
            ("ingresos", "Ingresos", "money"),
            ("flete_total", "Flete total", "money"),
            ("pct_flete_sobre_precio", "% flete/precio", "pct"),
        ],
        pesos=[0.8, 1, 1, 1],
    ),
    6: dict(
        obtener=lambda r: r["tablas"]["categorias_mas_pagadas_a_plazos"].sort_values(
            "pct_mas_de_1_cuota", ascending=False
        ).head(10),
        titulo="Top 10 categorías pagadas a más de 1 cuota",
        columnas=[
            ("categoria", "Categoría", "texto"),
            ("pedidos", "Pedidos", "int"),
            ("pct_mas_de_1_cuota", "% a plazos", "pct"),
        ],
        pesos=[2, 1, 1],
    ),
    7: dict(
        obtener=lambda r: r["tablas"]["ingresos_por_mes"].sort_values("ingresos", ascending=False).head(10),
        titulo="Top 10 meses por ingresos",
        columnas=[
            ("mes", "Mes", "texto"),
            ("pedidos", "Pedidos", "int"),
            ("ingresos", "Ingresos", "money"),
            ("excluido", "Excluido", "bool_si_no"),
        ],
        pesos=[1, 1, 1.2, 1],
    ),
    8: dict(
        obtener=lambda r: r["tablas"]["insatisfaccion_por_categoria"].sort_values(
            "pct_1_estrella", ascending=False
        ).head(10),
        titulo="Top 10 categorías por % de reseñas de 1 estrella",
        columnas=[
            ("categoria", "Categoría", "texto"),
            ("num_resenas", "Reseñas", "int"),
            ("calificacion_promedio", "Calificación", "rating"),
            ("pct_1_estrella", "% 1 estrella", "pct"),
            ("pct_tardios", "% tardíos", "pct"),
            ("clasificacion", "Clasificación", "texto"),
        ],
        pesos=[1.6, 0.9, 0.9, 0.9, 0.9, 1.6],
    ),
    9: dict(
        obtener=lambda r: r["tablas"]["top_10_categorias_audiencia"],
        titulo="Top 10 categorías de la audiencia (1 pedido, 5 estrellas)",
        columnas=[
            ("categoria", "Categoría", "texto"),
            ("clientes", "Clientes", "int"),
        ],
        pesos=[2, 1],
    ),
    10: dict(
        obtener=lambda r: r["tablas"]["oportunidad_por_estado"].dropna(
            subset=["clientes_por_vendedor"]
        ).sort_values("clientes_por_vendedor", ascending=False).head(10),
        titulo="Top 10 estados por clientes por vendedor",
        columnas=[
            ("estado", "Estado", "texto"),
            ("clientes", "Clientes", "int"),
            ("vendedores", "Vendedores", "int"),
            ("clientes_por_vendedor", "Clientes/vend.", "rating"),
            ("pct_items_otro_estado", "% otro estado", "pct"),
            ("dias_promedio_entrega", "Días entrega", "rating"),
            ("flete_promedio", "Flete prom.", "money"),
        ],
        pesos=[0.8, 0.9, 0.9, 1, 1, 0.9, 1],
    ),
}


NOTAS_METODOLOGICAS = [
    (
        "Pedido válido",
        "Se excluyen los pedidos con order_status en ('canceled', 'unavailable') de todos los "
        "cálculos de ingresos, ventas y recurrencia. Cuando una métrica necesita otros estatus "
        "(por ejemplo, la tasa de cancelación en la sección 4) se indica explícitamente en sus notas.",
    ),
    (
        "Cliente",
        "Se identifica como customer_unique_id, no como customer_id: en el dataset Olist una misma "
        "persona puede tener varios customer_id (uno por pedido).",
    ),
    (
        "Meses incompletos",
        "En la sección 7 (Estacionalidad) se excluyen el primer y el último mes del dataset (casi "
        "seguro truncados a mitad de mes) y cualquier mes cuyo número de pedidos sea menor a una "
        "fracción configurable de la mediana mensual de pedidos (20% por defecto).",
    ),
    (
        "Categoría de producto",
        "Se usa la traducción al inglés de product_category_translation; cuando no existe traducción "
        "para una categoría, se etiqueta como 'sin_categoria'.",
    ),
    (
        "Qué NO contiene esta base de datos",
        "El dataset Olist no incluye el costo de los productos ni márgenes de utilidad, tampoco una "
        "tabla de descuentos aplicados (el precio de order_items ya es el precio final pagado), ni "
        "datos posteriores a 2018 (el último mes con actividad relevante es octubre de 2018). Los "
        "análisis de rentabilidad o de tendencias recientes quedan fuera del alcance de esta base.",
    ),
]


# ---------------------------------------------------------------------------
# Construcción del documento
# ---------------------------------------------------------------------------


def _imagen_ajustada(buf: io.BytesIO, ancho_deseado: float, alto_maximo: float) -> RLImage:
    buf.seek(0)
    with PILImage.open(buf) as im:
        ancho_px, alto_px = im.size
    buf.seek(0)
    alto_deseado = ancho_deseado * (alto_px / ancho_px)
    if alto_deseado > alto_maximo:
        alto_deseado = alto_maximo
        ancho_deseado = alto_deseado * (ancho_px / alto_px)
    imagen = RLImage(buf, width=ancho_deseado, height=alto_deseado)
    imagen.hAlign = "CENTER"
    return imagen


def _construir_tabla(df: pd.DataFrame, columnas: list, ancho_total: float, pesos: list | None = None) -> Table:
    estilos = getSampleStyleSheet()
    estilo_celda = ParagraphStyle("CeldaTabla", parent=estilos["Normal"], fontSize=7.5, leading=9.5)
    estilo_header = ParagraphStyle(
        "HeaderTabla", parent=estilos["Normal"], fontSize=8, leading=10,
        textColor=colors.white, fontName="Helvetica-Bold",
    )

    pesos = pesos or [1] * len(columnas)
    suma_pesos = sum(pesos)
    anchos = [ancho_total * peso / suma_pesos for peso in pesos]

    valores_formateados = {
        nombre: _FORMATEADORES[tipo](df[nombre]) for nombre, _, tipo in columnas
    }

    filas = [[Paragraph(header, estilo_header) for _, header, _ in columnas]]
    for i in range(len(df)):
        filas.append([Paragraph(valores_formateados[nombre][i], estilo_celda) for nombre, _, _ in columnas])

    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86DE")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F8FC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tabla


def _encabezado_pie(canvas, doc) -> None:
    canvas.saveState()
    ancho, alto = A4
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(2 * cm, alto - 1.3 * cm, "Dashboard de verificación — Olist (sin IA)")
    canvas.drawRightString(ancho - 2 * cm, alto - 1.3 * cm, datetime.now().strftime("%d/%m/%Y"))
    canvas.line(2 * cm, alto - 1.45 * cm, ancho - 2 * cm, alto - 1.45 * cm)
    canvas.drawString(2 * cm, 1.3 * cm, "Generado con SQL directo sobre la base de datos, sin IA")
    canvas.drawRightString(ancho - 2 * cm, 1.3 * cm, f"Página {doc.page}")
    canvas.line(2 * cm, 1.5 * cm, ancho - 2 * cm, 1.5 * cm)
    canvas.restoreState()


def generar_pdf_bytes(resultados: dict[int, dict] | None = None) -> bytes:
    """Genera el PDF completo y lo devuelve como bytes (no escribe a disco).

    Si `resultados` no se pasa, se calcula llamando q01()..q10() con sus
    parámetros por defecto (para que el reporte sea reproducible). Si ya se
    tienen resultados calculados (p. ej. cacheados por Streamlit con los
    mismos parámetros por defecto), se pueden pasar aquí para no repetir
    las consultas.
    """
    if resultados is None:
        resultados = {i: getattr(q, f"q{i:02d}")() for i in range(1, 11)}

    resumen = _resumen_bd()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2.2 * cm,
        title="Reporte del Dashboard de verificación — Olist",
    )
    ancho_disponible = A4[0] - doc.leftMargin - doc.rightMargin
    alto_maximo_imagen = 10 * cm

    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle("TituloPortada", parent=estilos["Title"], fontSize=22, spaceAfter=10)
    estilo_h2 = ParagraphStyle(
        "H2", parent=estilos["Heading2"], textColor=colors.HexColor("#1B4F72"), spaceBefore=4, spaceAfter=6
    )
    estilo_normal = estilos["Normal"]
    estilo_respuesta = ParagraphStyle(
        "Respuesta", parent=estilos["Normal"], fontSize=10.5, leading=14,
        backColor=colors.HexColor("#EAF2FB"), borderPadding=8, spaceBefore=4, spaceAfter=10,
    )
    estilo_nota = ParagraphStyle(
        "Nota", parent=estilos["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#555555")
    )
    estilo_caption = ParagraphStyle(
        "Caption", parent=estilos["Normal"], fontSize=9, leading=12,
        spaceBefore=8, spaceAfter=4, fontName="Helvetica-Bold",
    )

    story = []

    # --- 1. Portada ---
    story.append(Spacer(1, 2.5 * cm))
    story.append(Paragraph("Dashboard de verificación — Olist", estilo_titulo))
    story.append(
        Paragraph(
            "Reporte de las 10 necesidades del dueño, calculado con SQL directo sobre la base de datos",
            estilos["Heading3"],
        )
    )
    story.append(Spacer(1, 0.4 * cm))
    fecha_generacion = datetime.now().strftime("%d/%m/%Y %H:%M")
    story.append(Paragraph(f"Generado el {fecha_generacion}", estilo_normal))
    story.append(Spacer(1, 1 * cm))

    datos_resumen = [
        ["Pedidos", f"{resumen['total_pedidos']:,}"],
        ["Clientes únicos", f"{resumen['clientes_unicos']:,}"],
        ["Vendedores", f"{resumen['vendedores']:,}"],
        ["Productos", f"{resumen['productos']:,}"],
        ["Rango de fechas", f"{str(resumen['fecha_min'])[:10]} a {str(resumen['fecha_max'])[:10]}"],
    ]
    tabla_resumen_bd = Table(datos_resumen, colWidths=[ancho_disponible * 0.4, ancho_disponible * 0.6])
    tabla_resumen_bd.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ]
        )
    )
    story.append(tabla_resumen_bd)
    story.append(Spacer(1, 1.5 * cm))
    story.append(
        Paragraph(
            "<b>Aviso:</b> todas las cifras de este reporte se calculan con consultas SQL directas "
            "sobre las tablas base de la base de datos (orders, order_items, customers, sellers, "
            "products, order_payments, order_reviews) — ningún dato pasa por un modelo de IA. Sirve "
            "para comparar de forma independiente contra lo que responde el asistente conversacional.",
            estilo_nota,
        )
    )
    story.append(PageBreak())

    # --- 2. Hoja de respuestas ---
    story.append(Paragraph("Hoja de respuestas", estilo_h2))
    story.append(
        Paragraph(
            "Resumen de las 10 necesidades, con la respuesta calculada directamente de la base de datos.",
            estilo_normal,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    estilo_celda_hoja = ParagraphStyle("CeldaHoja", parent=estilos["Normal"], fontSize=8.5, leading=11)
    estilo_header_hoja = ParagraphStyle(
        "HeaderHoja", parent=estilos["Normal"], fontSize=9, leading=11,
        textColor=colors.white, fontName="Helvetica-Bold",
    )
    filas_hoja = [
        [Paragraph("N.º", estilo_header_hoja), Paragraph("Pregunta", estilo_header_hoja),
         Paragraph("Respuesta clave", estilo_header_hoja)]
    ]
    for i in range(1, 11):
        r = resultados[i]
        filas_hoja.append(
            [
                Paragraph(str(i), estilo_celda_hoja),
                Paragraph(r["pregunta"], estilo_celda_hoja),
                Paragraph(r["respuesta_clave"], estilo_celda_hoja),
            ]
        )
    ancho_num = ancho_disponible * 0.06
    ancho_pregunta = ancho_disponible * 0.32
    ancho_respuesta = ancho_disponible - ancho_num - ancho_pregunta
    tabla_hoja = Table(filas_hoja, colWidths=[ancho_num, ancho_pregunta, ancho_respuesta], repeatRows=1)
    tabla_hoja.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86DE")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F8FC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(tabla_hoja)
    story.append(PageBreak())

    # --- 3. Una sección por necesidad ---
    for i in range(1, 11):
        r = resultados[i]
        story.append(Paragraph(f"{i}. {r['pregunta']}", estilo_h2))
        story.append(Paragraph(r["respuesta_clave"], estilo_respuesta))

        try:
            buf_img = _GENERADORES_GRAFICA[i](r)
            story.append(_imagen_ajustada(buf_img, ancho_disponible, alto_maximo_imagen))
        except Exception as e:  # noqa: BLE001
            story.append(Paragraph(f"(No se pudo generar la gráfica: {e})", estilo_nota))

        story.append(Spacer(1, 0.2 * cm))

        spec = _TABLA_SPECS[i]
        story.append(Paragraph(spec["titulo"], estilo_caption))
        df_tabla = spec["obtener"](r)
        if df_tabla.empty:
            story.append(Paragraph("Sin datos para los parámetros por defecto.", estilo_nota))
        else:
            story.append(_construir_tabla(df_tabla, spec["columnas"], ancho_disponible, spec.get("pesos")))

        story.append(Spacer(1, 0.25 * cm))
        if r["parametros"]:
            parametros_txt = ", ".join(f"{k} = {v}" for k, v in r["parametros"].items())
        else:
            parametros_txt = "esta necesidad no tiene parámetros ajustables."
        story.append(Paragraph(f"<b>Parámetros usados (valores por defecto):</b> {parametros_txt}", estilo_nota))
        story.append(Spacer(1, 0.1 * cm))
        story.append(Paragraph(f"<b>Notas de cálculo:</b> {r['notas']}", estilo_nota))
        story.append(PageBreak())

    # --- 4. Notas metodológicas y límites ---
    story.append(Paragraph("Notas metodológicas y límites", estilo_h2))
    for titulo_nota, texto_nota in NOTAS_METODOLOGICAS:
        story.append(Paragraph(f"<b>{titulo_nota}.</b> {texto_nota}", estilo_normal))
        story.append(Spacer(1, 0.25 * cm))

    doc.build(story, onFirstPage=_encabezado_pie, onLaterPages=_encabezado_pie)
    return buffer.getvalue()
