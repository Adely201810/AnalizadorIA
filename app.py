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
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from llm.bitacora import BitacoraEsquema
from llm.juez import JuezLLM, resolver_con_juez, texto_revision
from llm.ollama_client import ContextoInsuficienteError, OllamaClient, OllamaError
from llm.text_to_sql import (
    MENSAJE_ERROR_CHAT_GENERICO,
    MENSAJES_ERROR_CHAT,
    Text2SQLResult,
    answer_question,
    exportar_resultado_json,
)

GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "eval" / "ground_truth_olist.json"
CASOS_JUEZ_PATH = Path(__file__).resolve().parent / "eval" / "casos_juez.json"

st.set_page_config(page_title="Olist — Asistente de datos", page_icon="📊", layout="centered")


@st.cache_resource
def get_client() -> OllamaClient:
    return OllamaClient()


@st.cache_resource
def get_bitacora() -> BitacoraEsquema:
    """Bitácora persistente de errores de esquema (runtime/bitacora_esquema.json)."""
    return BitacoraEsquema()


@st.cache_resource
def get_juez() -> JuezLLM | None:
    """Juez de sensatez del SQL (una llamada extra por pregunta). TEXT2SQL_JUEZ_CHAT=0 lo apaga."""
    return None if os.environ.get("TEXT2SQL_JUEZ_CHAT", "1") == "0" else JuezLLM(get_client())


@st.cache_data
def get_preguntas_ejemplo() -> list[str]:
    try:
        data = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
        # Solo las 10 necesidades del dashboard (conjunto de DESARROLLO). Las preguntas de
        # PRUEBA (held-out) no se ofrecen: si se usaran en el chat, sus errores entrarían a la
        # bitácora y de ahí al prompt (docs/E2_PASO_2.md).
        return [item["pregunta"] for item in data["preguntas"] if item.get("pestana_dashboard")]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return []


@st.cache_data
def get_casos_juez() -> list[dict]:
    """Casos del juez iterativo (eval/casos_juez.json). Solo para el modo evaluación."""
    try:
        return json.loads(CASOS_JUEZ_PATH.read_text(encoding="utf-8"))["casos"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return []


def _iniciar_conversacion():
    st.session_state.mensajes = []
    st.session_state.pregunta_pendiente = None


if "mensajes" not in st.session_state:
    _iniciar_conversacion()
if "pregunta_pendiente" not in st.session_state:
    st.session_state.pregunta_pendiente = None
if "caso_juez_pendiente" not in st.session_state:
    st.session_state.caso_juez_pendiente = None


client = get_client()

with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    st.write(f"**Modelo:** `{client.model}`")
    st.write(f"**Ollama:** `{client.host}`")

    if st.button("🔄 Nueva conversación", width='stretch'):
        _iniciar_conversacion()
        st.rerun()

    st.markdown("---")
    # Fase 6 del juez (D-38): desactivado por defecto; no cambia el chat normal.
    modo_juez = st.toggle(
        "🧪 Modo evaluación con juez", value=False,
        help="Para las 6 preguntas del catálogo del juez: muestra cada intento (SQL, error o resultado y pista). "
             "El juez conoce la respuesta correcta; es una demostración, no el chat normal.",
    )
    if modo_juez:
        st.caption("El veredicto lo decide una comparación determinista con la referencia del dashboard. "
                   "El modelo nunca ve la referencia: solo su SQL anterior y las pistas.")
        max_iter_juez = st.slider("Intentos máximos", 1, 5, 5)
        antirrepeticion = st.checkbox("Anti-repetición (reintentos a T=0.5)", value=True)
        reparar = st.checkbox("Reparación con el esquema real", value=True)
        st.markdown("### 🧪 Preguntas del juez")
        for caso in get_casos_juez():
            if st.button(f"{caso['necesidad']}", key=f"juez_{caso['id']}", help=caso["pregunta"], width='stretch'):
                st.session_state.caso_juez_pendiente = {
                    "id": caso["id"], "max_iter": max_iter_juez, "antirrepeticion": antirrepeticion, "reparar": reparar,
                }
                st.rerun()
    else:
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
    """Sección colapsable 'Detalle técnico' (SQL, tabla de resultados, revisión
    del juez y errores). Se usa tanto al repintar el historial como al mostrar
    la respuesta recién generada. Si la pregunta se descompuso en sub-consultas,
    muestra un bloque por cada una. Si hubo un error sin SQL (p. ej. Ollama
    caído), igual se muestra el detalle técnico, abierto."""
    sub_consultas = mensaje.get("sub_consultas")
    tiene_sql = bool(mensaje.get("sql") or sub_consultas)
    if not tiene_sql and not mensaje.get("error_tecnico") and not mensaje.get("revision_sql"):
        return
    with st.expander("Detalle técnico (SQL, datos y diagnóstico)", expanded=not tiene_sql):
        if sub_consultas:
            for i, sc in enumerate(sub_consultas, start=1):
                st.markdown(f"**{i}. {sc['pregunta']}**")
                _render_tabla(sc.get("sql"), sc.get("columnas"), sc.get("filas"))
                if i < len(sub_consultas):
                    st.markdown("---")
        elif mensaje.get("sql"):
            _render_tabla(mensaje["sql"], mensaje.get("columnas"), mensaje.get("filas"))
        if mensaje.get("revision_sql"):
            st.caption(texto_revision(mensaje["revision_sql"]))
        if mensaje.get("error_tecnico"):
            st.markdown("**Error técnico:**")
            st.code(mensaje["error_tecnico"], language="text")


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


def _render_intento_juez(intento: dict, expandido: bool = False):
    """Un intento del modo evaluación con juez: SQL, error o resultado, y la pista que recibió el modelo."""
    correcto = intento["veredicto"]["correcto"]
    titulo = f"Intento {intento['intento']} — {'✅ correcto' if correcto else '❌ incorrecto'}"
    if intento.get("remuestreos"):
        titulo += f" · {intento['remuestreos']} remuestreo(s) por SQL repetido"
    with st.expander(titulo, expanded=expandido):
        if intento.get("sql"):
            st.code(intento["sql"], language="sql")
        ejecucion = intento["ejecucion"]
        if not ejecucion["ok"]:
            st.markdown(f"**Error ({ejecucion['etapa']}):**")
            st.code(ejecucion["error"] or "", language="text")
        elif intento.get("muestra_filas"):
            st.dataframe(pd.DataFrame(intento["muestra_filas"], columns=ejecucion["columnas"]), width='stretch')
            st.caption(f"{intento['filas_obtenidas']} fila(s) en total; se muestran hasta 5.")
        else:
            st.caption("La consulta no devolvió filas.")
        retro = intento.get("retroalimentacion")
        if retro:
            st.markdown("**Pista para el siguiente intento** (filtrada: no revela cifras ni el SQL de referencia):")
            st.info(retro["texto"])


def _render_juez(mensaje: dict):
    for intento in mensaje["registro"]["intentos"]:
        _render_intento_juez(intento)
    with st.expander("Respuesta de referencia (dashboard)"):
        st.markdown(mensaje["referencia"])


for indice, mensaje in enumerate(st.session_state.mensajes):
    with st.chat_message(mensaje["rol"]):
        st.markdown(mensaje["texto"])
        if mensaje.get("tipo") == "juez":
            _render_juez(mensaje)
        elif mensaje["rol"] == "assistant":
            _render_detalle(mensaje)
            _render_descarga_json(mensaje, indice)
    if mensaje["rol"] == "assistant":
        st.divider()  # separa visualmente cada intercambio pregunta/respuesta


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
            mensaje = {
                "rol": "assistant",
                "texto": texto,
                "error_tecnico": f"GET {client.host}/api/tags no respondió (modelo configurado: {client.model}).",
            }
            st.markdown(texto)
            _render_detalle(mensaje)
            st.session_state.mensajes.append(mensaje)
            return

        with st.spinner("Pensando..."):
            resultado: Text2SQLResult = answer_question(
                pregunta, client=client, bitacora=get_bitacora(), juez_sensatez=get_juez(),
            )

        if resultado.error:
            mensaje = {
                "rol": "assistant",
                "texto": MENSAJES_ERROR_CHAT.get(resultado.tipo_error, MENSAJE_ERROR_CHAT_GENERICO),
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
                "revision_sql": resultado.revision_sensatez,
            }

        datos_json = exportar_resultado_json(resultado, pregunta, client.model)
        mensaje["json_export"] = json.dumps(datos_json, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        mensaje["json_nombre"] = f"pregunta_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        indice = len(st.session_state.mensajes)
        st.markdown(mensaje["texto"])
        _render_detalle(mensaje)
        _render_descarga_json(mensaje, indice)
        st.session_state.mensajes.append(mensaje)


def _procesar_caso_juez(pendiente: dict):
    """Modo evaluación con juez (Fase 6, D-38): resuelve un caso del catálogo mostrando cada intento en vivo."""
    caso = next(c for c in get_casos_juez() if c["id"] == pendiente["id"])
    st.session_state.mensajes.append({"rol": "user", "texto": f"🧪 {caso['pregunta']}"})
    with st.chat_message("user"):
        st.markdown(f"🧪 {caso['pregunta']}")

    with st.chat_message("assistant"):
        if not client.is_available():
            st.markdown("No logro conectarme al motor de IA local (Ollama). Verifica que esté corriendo.")
            return
        with st.status("Resolviendo con el juez…", expanded=True) as estado:
            def al_intento(registro: dict):
                estado.update(label=f"Intento {registro['intento']} de {pendiente['max_iter']}…")
                _render_intento_juez(registro, expandido=True)

            try:
                registro = resolver_con_juez(
                    caso, client, max_iter=pendiente["max_iter"], temperatura=0.0, feedback="plantilla",
                    reintento_temp=0.5 if pendiente["antirrepeticion"] else None,
                    reparar_esquema=pendiente["reparar"], pistas_v2=pendiente["reparar"], al_intento=al_intento,
                )
            except (OllamaError, ContextoInsuficienteError) as exc:
                estado.update(label="Error del motor de IA", state="error")
                st.code(str(exc), language="text")
                return
            acierto = registro["acierto_final"]
            estado.update(label=f"{'Correcto' if acierto else 'Sin acierto'} tras {registro['intentos_usados']} intento(s)",
                          state="complete" if acierto else "error", expanded=False)

        if acierto:
            texto = f"✅ Respuesta correcta en el intento {registro['intentos_usados']} de {pendiente['max_iter']}."
            if registro.get("sintesis"):
                texto += f"\n\n{registro['sintesis']['texto']}"
        else:
            texto = f"❌ El modelo no acertó en {registro['intentos_usados']} intento(s)."
        st.markdown(texto)
        mensaje = {"rol": "assistant", "tipo": "juez", "texto": texto, "registro": registro,
                   "referencia": caso["respuesta_nl_referencia"]}
        with st.expander("Respuesta de referencia (dashboard)"):
            st.markdown(mensaje["referencia"])
        st.session_state.mensajes.append(mensaje)


pregunta_nueva = st.chat_input("Escribe tu pregunta sobre el negocio...")

if st.session_state.caso_juez_pendiente:
    pendiente_juez = st.session_state.caso_juez_pendiente
    st.session_state.caso_juez_pendiente = None
    _procesar_caso_juez(pendiente_juez)

if st.session_state.pregunta_pendiente:
    pregunta_nueva = st.session_state.pregunta_pendiente
    st.session_state.pregunta_pendiente = None

if pregunta_nueva:
    _procesar_pregunta(pregunta_nueva)
