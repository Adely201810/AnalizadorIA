"""
Dashboard de verificación (sin IA) — página de Streamlit.

Muestra, con gráficas Plotly interactivas, las 10 necesidades del dueño
resueltas con SQL directo (dashboard/queries.py) sobre las TABLAS BASE de
db/olist.db. Sirve para comparar de un vistazo contra lo que responde el
chatbot (app.py) y confirmar que la base de datos sí contiene esa
información. Streamlit agrega esta página sola al menú lateral por vivir en
pages/.

No importa ni modifica app.py, llm/ ni eval/.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard import queries as q
from dashboard.export_json import exportar_necesidad_json
from dashboard.pdf_report import generar_pdf_bytes
from db.olist_database import get_readonly_connection

st.set_page_config(page_title="Dashboard de verificación — Olist", page_icon="📈", layout="wide")


# ---------------------------------------------------------------------------
# Datos cacheados (una consulta por combinación de parámetros)
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_resumen_bd() -> dict:
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


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q01(min_clientes_categoria: int = 200) -> dict:
    return q.q01(min_clientes_categoria=min_clientes_categoria)


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q02() -> dict:
    return q.q02()


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q03(top_n_categorias: int = 5, top_m_vendedores: int = 10) -> dict:
    return q.q03(top_n_categorias=top_n_categorias, top_m_vendedores=top_m_vendedores)


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q04(
    min_pedidos: int = 30,
    umbral_calificacion: float = 3.5,
    umbral_pct_tardias: float = 15.0,
    percentil_ingresos_top: float = 0.25,
) -> dict:
    return q.q04(
        min_pedidos=min_pedidos,
        umbral_calificacion=umbral_calificacion,
        umbral_pct_tardias=umbral_pct_tardias,
        percentil_ingresos_top=percentil_ingresos_top,
    )


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q05(min_ingresos_categoria: float = 5000.0) -> dict:
    return q.q05(min_ingresos_categoria=min_ingresos_categoria)


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q06(min_pedidos_categoria: int = 100) -> dict:
    return q.q06(min_pedidos_categoria=min_pedidos_categoria)


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q07(pct_umbral_bajo_volumen: float = 0.2) -> dict:
    return q.q07(pct_umbral_bajo_volumen=pct_umbral_bajo_volumen)


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q08(min_resenas: int = 100) -> dict:
    return q.q08(min_resenas=min_resenas)


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q09() -> dict:
    return q.q09()


@st.cache_data(show_spinner="Consultando la base de datos...")
def cached_q10() -> dict:
    return q.q10()


@st.cache_data(show_spinner="Generando el reporte PDF...")
def cached_reporte_pdf() -> bytes:
    """Arma el PDF reusando los resultados YA cacheados (parámetros por
    defecto de cada consulta), para no repetir las consultas SQL."""
    resultados = {
        1: cached_q01(), 2: cached_q02(), 3: cached_q03(), 4: cached_q04(), 5: cached_q05(),
        6: cached_q06(), 7: cached_q07(), 8: cached_q08(), 9: cached_q09(), 10: cached_q10(),
    }
    return generar_pdf_bytes(resultados)


# ---------------------------------------------------------------------------
# Componentes reutilizables
# ---------------------------------------------------------------------------


def bloque_respuesta_clave(respuesta: str) -> None:
    st.markdown(
        f"""
        <div style="
            background-color: rgba(46, 134, 222, 0.10);
            border-left: 6px solid #2E86DE;
            border-radius: 6px;
            padding: 1rem 1.25rem;
            font-size: 1.05rem;
            line-height: 1.5;
            margin: 0.5rem 0 1rem 0;
        ">
        {respuesta}
        </div>
        """,
        unsafe_allow_html=True,
    )


def bloque_tablas(tablas: dict[str, pd.DataFrame], key_prefix: str) -> None:
    nombres = list(tablas.keys())
    if len(nombres) > 1:
        elegido = st.selectbox(
            "Tabla a mostrar",
            nombres,
            format_func=lambda n: n.replace("_", " ").capitalize(),
            key=f"{key_prefix}_tabla_sel",
        )
    else:
        elegido = nombres[0]
    df = tablas[elegido]
    st.dataframe(df, width="stretch", hide_index=True)
    st.download_button(
        "⬇️ Descargar CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"{key_prefix}_{elegido}.csv",
        mime="text/csv",
        key=f"{key_prefix}_descarga_{elegido}",
    )


def bloque_descarga_json(n: int, resultado: dict) -> None:
    """Botón 'Descargar JSON' de la necesidad `n`, con el resultado que la
    pestaña ya calculó con los parámetros actuales de sus sliders."""
    datos = exportar_necesidad_json(n, resultado_precalculado=resultado)
    st.download_button(
        "⬇️ Descargar JSON",
        data=json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"),
        file_name=f"necesidad_{n:02d}_software.json",
        mime="application/json",
        key=f"q{n:02d}_descarga_json",
    )


def bloque_como_se_calculo(resultado: dict) -> None:
    with st.expander("🔍 Cómo se calculó"):
        if resultado.get("parametros"):
            st.markdown("**Parámetros usados:**")
            st.json(resultado["parametros"])
        st.markdown("**SQL ejecutado (sobre las tablas base, no vw_\\*):**")
        st.code(resultado["sql"], language="sql")
        st.markdown("**Notas:**")
        st.caption(resultado["notas"])


def render_seccion(titulo: str, fn) -> None:
    """Ejecuta el cuerpo de una pestaña sin tumbar el resto de la página si falla."""
    try:
        fn()
    except sqlite3.OperationalError as e:
        st.error(
            f"No se pudo consultar la base de datos para '{titulo}'. "
            f"Verifica que `db/olist.db` exista y no esté bloqueada. Detalle técnico: {e}"
        )
    except Exception as e:  # noqa: BLE001 - queremos capturar cualquier falla de consulta
        st.error(f"Ocurrió un problema calculando '{titulo}'. Detalle técnico: {e}")


# ---------------------------------------------------------------------------
# Encabezado
# ---------------------------------------------------------------------------

st.title("📈 Dashboard de verificación — Olist")
st.caption(
    "Datos directos de la base de datos (consultas SQL sobre las tablas base), "
    "sin pasar por el modelo de IA. Úsalo para comparar contra las respuestas del chatbot."
)

try:
    resumen = cached_resumen_bd()
except sqlite3.OperationalError as e:
    st.error(
        "No se encontró o no se pudo abrir la base de datos (`db/olist.db`). "
        "Verifica que el archivo exista y que la carga inicial (`db/olist_init_db.py`) "
        f"se haya ejecutado. Detalle técnico: {e}"
    )
    st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"No se pudo leer el resumen de la base de datos. Detalle técnico: {e}")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Pedidos", f"{resumen['total_pedidos']:,}")
c2.metric("Clientes únicos", f"{resumen['clientes_unicos']:,}")
c3.metric("Vendedores", f"{resumen['vendedores']:,}")
c4.metric("Productos", f"{resumen['productos']:,}")
fecha_min = str(resumen["fecha_min"])[:10]
fecha_max = str(resumen["fecha_max"])[:10]
c5.metric("Rango de fechas", f"{fecha_min} → {fecha_max}")

col_pdf, _ = st.columns([1, 3])
with col_pdf:
    try:
        pdf_bytes = cached_reporte_pdf()
        nombre_archivo = f"reporte_dashboard_olist_{datetime.now().strftime('%Y%m%d')}.pdf"
        st.download_button(
            "📄 Descargar reporte PDF",
            data=pdf_bytes,
            file_name=nombre_archivo,
            mime="application/pdf",
            key="btn_descargar_pdf_reporte",
        )
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo generar el reporte PDF. Detalle técnico: {e}")

st.markdown("---")


# ---------------------------------------------------------------------------
# Pestañas
# ---------------------------------------------------------------------------

ESPECIFICACIONES = [
    ("1. Retención", cached_q01),
    ("2. Retraso vs reseñas", cached_q02),
    ("3. Concentración", cached_q03),
    ("4. Vendedores problemáticos", cached_q04),
    ("5. Flete", cached_q05),
    ("6. Pagos", cached_q06),
    ("7. Estacionalidad", cached_q07),
    ("8. Insatisfacción", cached_q08),
    ("9. Recompra", cached_q09),
    ("10. Oportunidad geográfica", cached_q10),
]


def _tab_resumen() -> None:
    st.subheader("Las 10 preguntas del dueño — respuesta directa de la base de datos")
    filas = []
    for nombre, fn in ESPECIFICACIONES:
        try:
            r = fn()
            filas.append(
                {"Necesidad": nombre, "Pregunta": r["pregunta"], "Respuesta clave": r["respuesta_clave"]}
            )
        except Exception as e:  # noqa: BLE001
            filas.append(
                {"Necesidad": nombre, "Pregunta": "(error)", "Respuesta clave": f"No se pudo calcular: {e}"}
            )
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)


def _tab_retencion() -> None:
    min_clientes = st.slider(
        "Mínimo de clientes por categoría (para la tasa de recompra)",
        min_value=50, max_value=2000, value=200, step=50, key="q01_min_clientes",
    )
    r = cached_q01(min_clientes_categoria=min_clientes)
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    comp = r["tablas"]["comparacion_recurrentes_vs_no"].copy()
    comp["grupo"] = comp["es_recurrente"].map({0: "No recurrente", 1: "Recurrente"})
    fig = go.Figure()
    fig.add_bar(x=comp["grupo"], y=comp["gasto_promedio"], marker_color="#2E86DE")
    fig.update_layout(
        title="Gasto total promedio: recurrentes vs no recurrentes",
        xaxis_title="Grupo de cliente",
        yaxis_title="Gasto promedio",
    )
    fig.update_yaxes(tickprefix="R$ ")
    st.plotly_chart(fig, width="stretch")

    col_a, col_b = st.columns(2)
    with col_a:
        top_cat = r["tablas"]["top_10_categorias_recurrentes"]
        fig2 = px.bar(top_cat, x="categoria", y="ingresos", title="Top 10 categorías de clientes recurrentes")
        fig2.update_layout(xaxis_title="Categoría", yaxis_title="Ingresos")
        fig2.update_yaxes(tickprefix="R$ ")
        fig2.update_xaxes(tickangle=45)
        st.plotly_chart(fig2, width="stretch")
    with col_b:
        top_edo = r["tablas"]["top_10_estados_recurrentes"]
        fig3 = px.bar(top_edo, x="customer_state", y="clientes_recurrentes", title="Top 10 estados de clientes recurrentes")
        fig3.update_layout(xaxis_title="Estado", yaxis_title="Clientes recurrentes")
        st.plotly_chart(fig3, width="stretch")

    bloque_tablas(r["tablas"], "q01")
    bloque_descarga_json(1, r)
    bloque_como_se_calculo(r)


def _tab_retraso() -> None:
    r = cached_q02()
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    tabla = r["tablas"]["retraso_vs_calificacion"].sort_values("orden")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=tabla["rango_retraso"], y=tabla["calificacion_promedio"], name="Calificación promedio", marker_color="#2E86DE")
    fig.add_trace(
        go.Scatter(
            x=tabla["rango_retraso"], y=tabla["pct_1_2_estrellas"],
            name="% de 1-2 estrellas", mode="lines+markers", line=dict(color="#E74C3C"),
        ),
        secondary_y=True,
    )
    fig.update_layout(title="Calificación y % de reseñas negativas por rango de retraso")
    fig.update_xaxes(title_text="Rango de retraso (días)")
    fig.update_yaxes(title_text="Calificación promedio (1-5)", range=[0, 5], secondary_y=False)
    fig.update_yaxes(title_text="% de reseñas 1-2 estrellas", ticksuffix="%", secondary_y=True)
    st.plotly_chart(fig, width="stretch")

    bloque_tablas(r["tablas"], "q02")
    bloque_descarga_json(2, r)
    bloque_como_se_calculo(r)


def _pareto_fig(df: pd.DataFrame, x_col: str, titulo: str, n_marca: int, max_barras: int) -> go.Figure:
    df = df.sort_values("rango").head(max_barras)
    colores = ["#2E86DE" if rango <= n_marca else "#B8C7DA" for rango in df["rango"]]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=df[x_col].astype(str), y=df["ingresos"], name="Ingresos", marker_color=colores)
    fig.add_trace(
        go.Scatter(
            x=df[x_col].astype(str), y=df["pct_acumulado"],
            name="% acumulado", mode="lines+markers", line=dict(color="#E74C3C"),
        ),
        secondary_y=True,
    )
    fig.update_layout(title=titulo, legend=dict(orientation="h"))
    fig.update_yaxes(title_text="Ingresos", tickprefix="R$ ", secondary_y=False)
    fig.update_yaxes(title_text="% acumulado", ticksuffix="%", range=[0, 105], secondary_y=True)
    fig.update_xaxes(tickangle=45)
    return fig


def _tab_concentracion() -> None:
    c1, c2 = st.columns(2)
    with c1:
        top_n = st.slider("Top N categorías", 2, 20, 5, key="q03_top_n")
    with c2:
        top_m = st.slider("Top M vendedores", 2, 50, 10, key="q03_top_m")

    r = cached_q03(top_n_categorias=top_n, top_m_vendedores=top_m)
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    cat = r["tablas"]["pareto_categorias"]
    vend = r["tablas"]["pareto_vendedores"]
    st.plotly_chart(_pareto_fig(cat, "categoria", "Pareto de ingresos por categoría", top_n, max_barras=80), width="stretch")
    st.plotly_chart(_pareto_fig(vend, "seller_id", "Pareto de ingresos por vendedor", top_m, max_barras=60), width="stretch")
    if len(vend) > 60:
        st.caption(f"Mostrando los 60 vendedores de mayor ingreso de {len(vend)} en total; la curva de % acumulado sí considera el total.")

    bloque_tablas(r["tablas"], "q03")
    bloque_descarga_json(3, r)
    bloque_como_se_calculo(r)


def _tab_vendedores() -> None:
    c1, c2 = st.columns(2)
    with c1:
        min_pedidos = st.slider("Mínimo de pedidos por vendedor", 5, 200, 30, step=5, key="q04_min_pedidos")
        umbral_calificacion = st.slider("Umbral de calificación", 1.0, 5.0, 3.5, step=0.1, key="q04_umbral_calif")
    with c2:
        umbral_tardias = st.slider("Umbral de % entregas tardías", 0.0, 50.0, 15.0, step=1.0, key="q04_umbral_tardias")
        percentil_top = st.slider("Percentil superior de ingresos", 0.05, 0.5, 0.25, step=0.05, key="q04_percentil")

    r = cached_q04(
        min_pedidos=min_pedidos,
        umbral_calificacion=umbral_calificacion,
        umbral_pct_tardias=umbral_tardias,
        percentil_ingresos_top=percentil_top,
    )
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    tabla = r["tablas"]["vendedores"].copy()
    tabla["Estado"] = tabla["vendedor_a_revisar"].map({True: "A revisar", False: "OK"})
    fig = px.scatter(
        tabla, x="ingresos", y="calificacion_promedio", color="Estado",
        size="pct_entregas_tardias", hover_data=["seller_id", "pedidos_totales", "pct_cancelados"],
        color_discrete_map={"A revisar": "#E74C3C", "OK": "#2ECC71"},
        title="Vendedores: ingresos vs calificación (tamaño = % de entregas tardías)",
    )
    fig.update_layout(xaxis_title="Ingresos", yaxis_title="Calificación promedio (1-5)")
    fig.update_xaxes(tickprefix="R$ ")
    st.plotly_chart(fig, width="stretch")

    bloque_tablas(r["tablas"], "q04")
    bloque_descarga_json(4, r)
    bloque_como_se_calculo(r)


def _tab_flete() -> None:
    min_ingresos = st.slider(
        "Ingresos mínimos por categoría (para el top de flete)",
        0, 50000, 5000, step=1000, key="q05_min_ingresos",
    )
    r = cached_q05(min_ingresos_categoria=float(min_ingresos))
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    estados = r["tablas"]["flete_por_estado"].sort_values("pct_flete_sobre_precio", ascending=False)
    fig = px.bar(estados, x="customer_state", y="pct_flete_sobre_precio", title="% de flete sobre precio por estado del cliente")
    fig.update_layout(xaxis_title="Estado", yaxis_title="% flete / precio")
    fig.update_yaxes(ticksuffix="%")
    st.plotly_chart(fig, width="stretch")

    categorias = r["tablas"]["top_10_categorias_flete"]
    fig2 = px.bar(
        categorias, x="categoria", y="pct_flete_sobre_precio",
        title=f"Top categorías por % de flete (ingresos ≥ R$ {min_ingresos:,.0f})",
    )
    fig2.update_layout(xaxis_title="Categoría", yaxis_title="% flete / precio")
    fig2.update_yaxes(ticksuffix="%")
    fig2.update_xaxes(tickangle=45)
    st.plotly_chart(fig2, width="stretch")

    bloque_tablas(r["tablas"], "q05")
    bloque_descarga_json(5, r)
    bloque_como_se_calculo(r)


def _tab_pagos() -> None:
    min_pedidos_cat = st.slider(
        "Mínimo de pedidos por categoría (para % pagado a plazos)",
        10, 1000, 100, step=10, key="q06_min_pedidos",
    )
    r = cached_q06(min_pedidos_categoria=min_pedidos_cat)
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    c1, c2 = st.columns(2)
    with c1:
        tipo = r["tablas"]["por_metodo_pago"]
        fig = px.bar(tipo, x="payment_type", y="ticket_promedio", title="Ticket promedio por método de pago")
        fig.update_layout(xaxis_title="Método de pago", yaxis_title="Ticket promedio")
        fig.update_yaxes(tickprefix="R$ ")
        st.plotly_chart(fig, width="stretch")
    with c2:
        cuotas = r["tablas"]["ticket_por_rango_cuotas"].sort_values("orden")
        fig2 = px.bar(cuotas, x="rango_cuotas", y="ticket_promedio", title="Ticket promedio por rango de cuotas")
        fig2.update_layout(xaxis_title="Cuotas", yaxis_title="Ticket promedio")
        fig2.update_yaxes(tickprefix="R$ ")
        st.plotly_chart(fig2, width="stretch")

    bloque_tablas(r["tablas"], "q06")
    bloque_descarga_json(6, r)
    bloque_como_se_calculo(r)


def _tab_estacionalidad() -> None:
    umbral = st.slider(
        "Umbral de bajo volumen (fracción de la mediana mensual de pedidos)",
        0.05, 0.5, 0.2, step=0.05, key="q07_umbral",
    )
    r = cached_q07(pct_umbral_bajo_volumen=umbral)
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    metrica = st.radio("Métrica a graficar", ["ingresos", "pedidos"], horizontal=True, key="q07_metrica")
    meses = r["tablas"]["ingresos_por_mes"].sort_values("mes")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=meses["mes"], y=meses[metrica], mode="lines+markers", name=metrica.capitalize(),
            line=dict(color="#2E86DE"),
            marker=dict(color=["#E74C3C" if excluido else "#2E86DE" for excluido in meses["excluido"]], size=9),
        )
    )
    fig.update_layout(title=f"{metrica.capitalize()} por mes (marcador rojo = mes excluido por incompleto)")
    fig.update_xaxes(title_text="Mes")
    fig.update_yaxes(title_text=metrica.capitalize(), tickprefix="R$ " if metrica == "ingresos" else "")
    st.plotly_chart(fig, width="stretch")

    crecimiento = r["tablas"]["crecimiento_yoy_meses_comparables"]
    if not crecimiento.empty:
        fig2 = px.bar(
            crecimiento.sort_values("mes_num"), x="mes_num", y="crecimiento_ingresos_pct",
            title="Crecimiento de ingresos 2018 vs 2017 por mes comparable",
        )
        fig2.update_layout(xaxis_title="Mes", yaxis_title="Crecimiento interanual")
        fig2.update_yaxes(ticksuffix="%")
        st.plotly_chart(fig2, width="stretch")
    else:
        st.info("No hay meses comparables entre 2017 y 2018 con el umbral actual.")

    bloque_tablas(r["tablas"], "q07")
    bloque_descarga_json(7, r)
    bloque_como_se_calculo(r)


def _tab_insatisfaccion() -> None:
    min_resenas = st.slider("Mínimo de reseñas por categoría", 10, 1000, 100, step=10, key="q08_min_resenas")
    r = cached_q08(min_resenas=min_resenas)
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    tabla = r["tablas"]["insatisfaccion_por_categoria"]
    if tabla.empty:
        st.warning("No hay categorías con suficientes reseñas para este umbral.")
    else:
        cal_global = tabla["calificacion_global"].iloc[0]
        tard_global = tabla["pct_tardios_global"].iloc[0]
        fig = px.scatter(
            tabla, x="pct_tardios", y="calificacion_promedio", color="clasificacion", text="categoria",
            hover_data=["categoria", "num_resenas", "pct_1_estrella"],
            color_discrete_map={
                "problema_de_producto": "#E74C3C",
                "problema_logistico": "#F39C12",
                "otro": "#2ECC71",
            },
            title="Categorías por calificación vs % de entregas tardías",
        )
        fig.update_traces(textposition="top center")
        fig.add_hline(y=cal_global, line_dash="dash", line_color="gray", annotation_text="Calificación global")
        fig.add_vline(x=tard_global, line_dash="dash", line_color="gray", annotation_text="% tardíos global")
        fig.update_layout(xaxis_title="% de entregas tardías", yaxis_title="Calificación promedio")
        fig.update_xaxes(ticksuffix="%")
        st.plotly_chart(fig, width="stretch")

    bloque_tablas(r["tablas"], "q08")
    bloque_descarga_json(8, r)
    bloque_como_se_calculo(r)


def _tab_recompra() -> None:
    r = cached_q09()
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    col_a, col_b = st.columns(2)
    with col_a:
        cat = r["tablas"]["top_10_categorias_audiencia"]
        fig = px.bar(cat, x="categoria", y="clientes", title="Top 10 categorías (clientes de 1 pedido y 5 estrellas)")
        fig.update_layout(xaxis_title="Categoría", yaxis_title="Clientes")
        fig.update_xaxes(tickangle=45)
        st.plotly_chart(fig, width="stretch")
    with col_b:
        edo = r["tablas"]["top_10_estados_audiencia"]
        fig2 = px.bar(edo, x="customer_state", y="clientes", title="Top 10 estados (clientes de 1 pedido y 5 estrellas)")
        fig2.update_layout(xaxis_title="Estado", yaxis_title="Clientes")
        st.plotly_chart(fig2, width="stretch")

    bloque_tablas(r["tablas"], "q09")
    bloque_descarga_json(9, r)
    bloque_como_se_calculo(r)


def _tab_oportunidad() -> None:
    r = cached_q10()
    st.markdown(f"##### {r['pregunta']}")
    bloque_respuesta_clave(r["respuesta_clave"])

    tabla = r["tablas"]["oportunidad_por_estado"].dropna(subset=["clientes_por_vendedor"])
    fig = px.scatter(
        tabla, x="vendedores", y="clientes", size="clientes_por_vendedor", text="estado",
        hover_data=["clientes_por_vendedor", "pct_items_otro_estado", "dias_promedio_entrega", "flete_promedio"],
        title="Clientes vs vendedores por estado (tamaño = clientes por vendedor)",
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(xaxis_title="Vendedores activos", yaxis_title="Clientes")
    st.plotly_chart(fig, width="stretch")

    bloque_tablas(r["tablas"], "q10")
    bloque_descarga_json(10, r)
    bloque_como_se_calculo(r)


tabs = st.tabs(
    [
        "📋 Resumen",
        "1. Retención",
        "2. Retraso vs reseñas",
        "3. Concentración",
        "4. Vendedores problemáticos",
        "5. Flete",
        "6. Pagos",
        "7. Estacionalidad",
        "8. Insatisfacción",
        "9. Recompra",
        "10. Oportunidad geográfica",
    ]
)

with tabs[0]:
    render_seccion("Resumen", _tab_resumen)
with tabs[1]:
    render_seccion("Retención", _tab_retencion)
with tabs[2]:
    render_seccion("Retraso vs reseñas", _tab_retraso)
with tabs[3]:
    render_seccion("Concentración", _tab_concentracion)
with tabs[4]:
    render_seccion("Vendedores problemáticos", _tab_vendedores)
with tabs[5]:
    render_seccion("Flete", _tab_flete)
with tabs[6]:
    render_seccion("Pagos", _tab_pagos)
with tabs[7]:
    render_seccion("Estacionalidad", _tab_estacionalidad)
with tabs[8]:
    render_seccion("Insatisfacción", _tab_insatisfaccion)
with tabs[9]:
    render_seccion("Recompra", _tab_recompra)
with tabs[10]:
    render_seccion("Oportunidad geográfica", _tab_oportunidad)
