"""
Interfaz gráfica (Streamlit) para el pipeline Text-to-SQL de llm/text_to_sql.py.

Es una capa de UI encima del mismo pipeline que usa llm/cli.py -- no duplica
ninguna lógica de generación/validación/ejecución de SQL, solo la orquesta con
componentes de chat y maneja los estados de la UI (historial, "pensando...",
errores amigables).

Uso:
    streamlit run app.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from llm.ollama_client import OllamaClient
from llm.text_to_sql import Text2SQLResult, answer_question, exportar_resultado_json

GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "eval" / "ground_truth_olist.json"

st.set_page_config(page_title="Olist — Asistente de datos", page_icon="📊", layout="centered")


@st.cache_resource
def get_client() -> OllamaClient:
    return OllamaClient()


@st.cache_data
def get_preguntas_ejemplo() -> list[str]:
    try:
        data = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
        return [item["pregunta"] for item in data["preguntas"]]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return []


def _iniciar_conversacion():
    st.session_state.mensajes = []
    st.session_state.pregunta_pendiente = None


if "mensajes" not in st.session_state:
    _iniciar_conversacion()
if "pregunta_pendiente" not in st.session_state:
    st.session_state.pregunta_pendiente = None


client = get_client()

with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    st.write(f"**Modelo:** `{client.model}`")
    st.write(f"**Ollama:** `{client.host}`")

    if st.button("🔄 Nueva conversación", width='stretch'):
        _iniciar_conversacion()
        st.rerun()

    st.markdown("---")
    st.markdown("### 💡 Preguntas de ejemplo")
    for pregunta in get_preguntas_ejemplo():
        if st.button(pregunta, key=f"ejemplo_{pregunta}", width='stretch'):
            st.session_state.pregunta_pendiente = pregunta
            st.rerun()

st.title("📊 Asistente de datos — Olist")
st.caption("Pregunta en español sobre pedidos, clientes, ventas y entregas del marketplace Olist.")

def _render_tabla(sql: str | None, columnas: list, filas: list):
    if not sql:
        st.caption("No se pudo obtener este dato.")
        return
    st.code(sql, language="sql")
    if filas:
        df = pd.DataFrame(filas, columns=columnas)
        st.dataframe(df, width='stretch')
    else:
        st.caption("La consulta no devolvió filas.")


def _render_detalle(mensaje: dict):
    """Expander 'Ver detalle' con el SQL y la tabla de resultados. Se usa tanto
    al repintar el historial como al mostrar la respuesta recién generada, para
    no duplicar la lógica de render. Si la pregunta se descompuso en
    sub-consultas (pregunta abierta), muestra un bloque por cada una."""
    sub_consultas = mensaje.get("sub_consultas")
    if not mensaje.get("sql") and not sub_consultas:
        return
    with st.expander("Ver detalle"):
        if sub_consultas:
            for i, sc in enumerate(sub_consultas, start=1):
                st.markdown(f"**{i}. {sc['pregunta']}**")
                _render_tabla(sc.get("sql"), sc.get("columnas"), sc.get("filas"))
                if i < len(sub_consultas):
                    st.markdown("---")
        else:
            _render_tabla(mensaje["sql"], mensaje.get("columnas"), mensaje.get("filas"))
        if mensaje.get("error_tecnico"):
            st.caption(f"Detalle técnico: {mensaje['error_tecnico']}")


def _render_descarga_json(mensaje: dict, indice: int):
    """Botón para descargar el JSON de la respuesta. El JSON ya viene armado en
    el mensaje (no se vuelve a llamar al modelo)."""
    if not mensaje.get("json_export"):
        return
    st.download_button(
        "Descargar JSON de esta respuesta",
        data=mensaje["json_export"],
        file_name=mensaje["json_nombre"],
        mime="application/json",
        key=f"descarga_json_{indice}",
    )


for indice, mensaje in enumerate(st.session_state.mensajes):
    with st.chat_message(mensaje["rol"]):
        st.markdown(mensaje["texto"])
        if mensaje["rol"] == "assistant":
            _render_detalle(mensaje)
            _render_descarga_json(mensaje, indice)


def _procesar_pregunta(pregunta: str):
    st.session_state.mensajes.append({"rol": "user", "texto": pregunta})
    with st.chat_message("user"):
        st.markdown(pregunta)

    with st.chat_message("assistant"):
        if not client.is_available():
            texto = (
                "No logro conectarme al motor de IA local (Ollama). "
                "Verifica que esté corriendo (`ollama serve`) e intenta de nuevo."
            )
            st.markdown(texto)
            st.session_state.mensajes.append({"rol": "assistant", "texto": texto})
            return

        with st.spinner("Pensando..."):
            resultado: Text2SQLResult = answer_question(pregunta, client=client)

        if resultado.error:
            mensaje = {
                "rol": "assistant",
                "texto": "No pude generar una consulta válida para responder eso. ¿Puedes reformular la pregunta?",
                "sql": resultado.sql,
                "columnas": resultado.columnas,
                "filas": resultado.filas,
                "sub_consultas": resultado.sub_consultas,
                "error_tecnico": resultado.error,
            }
        else:
            mensaje = {
                "rol": "assistant",
                "texto": resultado.respuesta,
                "sql": resultado.sql,
                "columnas": resultado.columnas,
                "filas": resultado.filas,
                "sub_consultas": resultado.sub_consultas,
            }

        datos_json = exportar_resultado_json(resultado, pregunta, client.model)
        mensaje["json_export"] = json.dumps(datos_json, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        mensaje["json_nombre"] = f"pregunta_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        indice = len(st.session_state.mensajes)
        st.markdown(mensaje["texto"])
        _render_detalle(mensaje)
        _render_descarga_json(mensaje, indice)
        st.session_state.mensajes.append(mensaje)


pregunta_nueva = st.chat_input("Escribe tu pregunta sobre el negocio...")

if st.session_state.pregunta_pendiente:
    pregunta_nueva = st.session_state.pregunta_pendiente
    st.session_state.pregunta_pendiente = None

if pregunta_nueva:
    _procesar_pregunta(pregunta_nueva)
