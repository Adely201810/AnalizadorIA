"""
Juez-LLM (Fases 6, 8 y 10): un componente SEPARADO del generador de SQL.

Nunca decide si una respuesta es correcta: en la evaluación ese veredicto es
del árbitro determinista (eval/comparador.py). El juez solo:
  - opinar():           da su opinión (¿el SQL responde la pregunta?) para MEDIR
                        cuánto coincide con el árbitro (Fase 8).
  - diagnosticar():     explica qué parte del ENFOQUE parece estar mal, sin
                        conocer la respuesta correcta (pista entre intentos,
                        Fase 7; explicación del fallo, Fase 8).
  - evaluar_sensatez(): en el chat libre, revisa si el SQL tiene sentido para la
                        pregunta (columnas, JOINs, agregación), sin afirmar que
                        la cifra sea correcta (Fase 10).

Nunca recibe valores de la referencia.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from llm.ollama_client import OllamaClient, OllamaError

MAX_FILAS_AL_JUEZ = 10

_SISTEMA_OPINAR = """Eres un revisor experto de consultas SQL sobre una base de datos de e-commerce (Olist, SQLite). \
Recibes una pregunta de negocio en español, la consulta SQL que se ejecutó y una muestra de su resultado. \
Decide si la consulta responde EXACTAMENTE lo que pide la pregunta: la métrica correcta, el filtro correcto, \
el nivel de agregación correcto (por pedido, por cliente, por categoría...) y las columnas pedidas. \
No conoces la respuesta correcta. Responde SOLO con JSON en una línea: \
{"responde": true o false, "motivo": "una frase"}"""

_SISTEMA_DIAGNOSTICAR = """Eres un revisor experto de consultas SQL sobre una base de datos de e-commerce (Olist, SQLite). \
Una verificación automática indica que la consulta NO responde correctamente la pregunta. No conoces la \
respuesta correcta y no debes inventar cifras. En 1 o 2 frases, en español, señala qué parte del ENFOQUE de la \
consulta probablemente está mal (por ejemplo: filtro, tabla o columna usada, JOIN que duplica filas, nivel de \
agregación, promedio de promedios, división mal planteada) y cómo corregir el enfoque. No escribas SQL ni números."""

_SISTEMA_SENSATEZ = """Eres un revisor experto de consultas SQL sobre una base de datos de e-commerce (Olist, SQLite). \
Recibes una pregunta en español y la consulta SQL que se ejecutó. NO juzgues si la cifra es correcta (no la \
conoces); solo si la consulta TIENE SENTIDO para la pregunta: usa columnas y tablas adecuadas, los JOIN unen \
llaves del mismo tipo, agrega al nivel que pide la pregunta y filtra lo que la pregunta menciona. \
Responde SOLO con JSON en una línea: {"tiene_sentido": true o false, "motivo": "una frase"}"""


@dataclass
class OpinionJuez:
    valor: bool | None  # None = el juez no devolvió un JSON interpretable
    motivo: str
    crudo: str


def _muestra(columnas: list, filas: list) -> str:
    if not filas:
        return "(sin filas)"
    lineas = [" | ".join(map(str, columnas))] if columnas else []
    lineas += [" | ".join("NULL" if v is None else str(v) for v in f) for f in filas[:MAX_FILAS_AL_JUEZ]]
    if len(filas) > MAX_FILAS_AL_JUEZ:
        lineas.append(f"... ({len(filas) - MAX_FILAS_AL_JUEZ} filas más)")
    return "\n".join(lineas)


def _leer_json(texto: str, clave: str) -> OpinionJuez:
    m = re.search(r"\{.*\}", texto, re.S)
    if m:
        try:
            datos = json.loads(m.group(0))
            valor = datos.get(clave)
            if isinstance(valor, str):
                valor = {"true": True, "false": False}.get(valor.strip().lower())
            return OpinionJuez(valor if isinstance(valor, bool) else None, str(datos.get("motivo", "")), texto)
        except json.JSONDecodeError:
            pass
    return OpinionJuez(None, "respuesta del juez no interpretable", texto)


class JuezLLM:
    def __init__(self, client: OllamaClient | None = None):
        self.client = client or OllamaClient()

    def _llamar(self, sistema: str, prompt: str, num_predict: int) -> str:
        return self.client.generate(prompt, system=sistema, num_predict=num_predict, temperature=0)

    def opinar(self, pregunta: str, sql: str, columnas: list, filas: list) -> OpinionJuez:
        prompt = f"Pregunta: {pregunta}\n\nSQL ejecutado:\n{sql}\n\nResultado ({len(filas)} fila(s)):\n{_muestra(columnas, filas)}"
        try:
            return _leer_json(self._llamar(_SISTEMA_OPINAR, prompt, 120), "responde")
        except OllamaError as exc:
            return OpinionJuez(None, f"juez no disponible: {exc}", "")

    def diagnosticar(self, pregunta: str, sql: str, columnas: list, filas: list, problema: str) -> str:
        prompt = (
            f"Pregunta: {pregunta}\n\nSQL ejecutado:\n{sql}\n\nResultado ({len(filas)} fila(s)):\n{_muestra(columnas, filas)}"
            f"\n\nProblema detectado por la verificación automática: {problema}"
        )
        try:
            return self._llamar(_SISTEMA_DIAGNOSTICAR, prompt, 150).strip()
        except OllamaError as exc:
            return f"(sin diagnóstico: {exc})"

    def evaluar_sensatez(self, pregunta: str, sql: str) -> OpinionJuez:
        prompt = f"Pregunta: {pregunta}\n\nSQL ejecutado:\n{sql}"
        try:
            return _leer_json(self._llamar(_SISTEMA_SENSATEZ, prompt, 120), "tiene_sentido")
        except OllamaError as exc:
            return OpinionJuez(None, f"juez no disponible: {exc}", "")


def texto_revision(revision: dict | None) -> str | None:
    """La revisión del juez NO es una verificación de la cifra: solo dice si el SQL
    parece coherente con la pregunta. El texto lo deja explícito."""
    if not revision:
        return None
    aviso = "Revisión automática del SQL (un segundo modelo revisó si la consulta tiene sentido para la pregunta; no comprueba que la cifra sea correcta)"
    if revision.get("tiene_sentido") is True:
        return f"🔎 {aviso}: parece coherente. {revision.get('motivo', '')}"
    if revision.get("tiene_sentido") is False:
        return f"⚠️ {aviso}: posible problema. {revision.get('motivo', '')}"
    return f"🔎 {aviso}: no se pudo obtener una revisión."
