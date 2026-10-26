"""
Few-shot FIJO con el banco de necesidades negativas (mejoras del profesor, fase B; D-43).

- `ejemplos_fijos(n)`: N ejemplos fijos, uno por familia en orden round-robin (el primero de cada
  familia; con N > 5 se toma el segundo de cada familia, etc.). N = TEXT2SQL_FEWSHOT_N (por defecto 3).
- `texto_bloque`: formato "Pregunta -> SQL" y, opcionalmente (TEXT2SQL_FEWSHOT_RESPUESTA=1), la respuesta.
- `ajustar_a_presupuesto`: quita ejemplos del final hasta que system + prompt + bloque + reserva para
  el reintento + num_predict quepan en el 90 % de num_ctx (estimación conservadora de tokens por caracteres).
"""
from __future__ import annotations

import os

from llm.banco_ejemplos import cargar_banco

N_FEWSHOT = int(os.environ.get("TEXT2SQL_FEWSHOT_N", "3"))
CON_RESPUESTA = os.environ.get("TEXT2SQL_FEWSHOT_RESPUESTA", "0") == "1"
# Presupuesto: el esquema compacto mide 12,984 caracteres = 3,333 tokens (3.9 car/token). Se usa 3.0, por exceso.
CARACTERES_POR_TOKEN = 3.0
RESERVA_REINTENTO_TOKENS = 700  # SQL anterior + error + reparación con esquema en el reintento
NUM_PREDICT_SQL = 350
MARGEN = 0.10

ENCABEZADO_FIJO = "Ejemplos de preguntas de negocio ya resueltas y verificadas (pregunta -> SQL):"
ENCABEZADO_RAG = (
    "Preguntas PARECIDAS a la tuya, ya resueltas y verificadas contra la base. NO son tu pregunta: "
    "ADAPTA su lógica (tablas, uniones, filtros, nivel de agregación) a lo que pide tu pregunta y no copies "
    "sus valores, filtros, umbrales ni cifras."
)


def ejemplos_fijos(n: int | None = None) -> list[dict]:
    n = N_FEWSHOT if n is None else n
    banco = cargar_banco()
    familias = list(dict.fromkeys(e["familia"] for e in banco))
    por_familia = {f: [e for e in banco if e["familia"] == f] for f in familias}
    elegidos, ronda = [], 0
    while len(elegidos) < n and any(len(v) > ronda for v in por_familia.values()):
        for f in familias:
            if len(elegidos) < n and len(por_familia[f]) > ronda:
                elegidos.append(por_familia[f][ronda])
        ronda += 1
    return elegidos


def texto_ejemplo(e: dict, i: int, similitud: float | None, con_respuesta: bool) -> str:
    cab = f"Ejemplo {i}" + (f" (similitud {similitud:.2f})" if similitud is not None else "")
    partes = [f"{cab}:", f"Pregunta: {e['pregunta']}", f"SQL:\n{e['sql']}"]
    if con_respuesta:
        partes.append(f"Respuesta: {e['respuesta_nl']}")
    return "\n".join(partes)


def texto_bloque(ejemplos: list[dict], recuperados: bool, con_respuesta: bool | None = None) -> str:
    con_respuesta = CON_RESPUESTA if con_respuesta is None else con_respuesta
    cuerpo = "\n\n".join(texto_ejemplo(x["entrada"], i, x["similitud"], con_respuesta)
                         for i, x in enumerate(ejemplos, 1))
    return f"{ENCABEZADO_RAG if recuperados else ENCABEZADO_FIJO}\n\n{cuerpo}"


def tokens_estimados(*textos: str) -> int:
    return int(sum(len(t) for t in textos) / CARACTERES_POR_TOKEN)


def cabe(system: str, prompt_base: str, bloque: str, num_ctx: int | None = None) -> bool:
    from llm.ollama_client import DEFAULT_NUM_CTX

    num_ctx = num_ctx or DEFAULT_NUM_CTX
    total = tokens_estimados(system, prompt_base, bloque) + RESERVA_REINTENTO_TOKENS + NUM_PREDICT_SQL
    return total <= (1 - MARGEN) * num_ctx


def ajustar_a_presupuesto(ejemplos: list[dict], system: str = "", prompt_base: str = "", recuperados: bool = False,
                          num_ctx: int | None = None) -> list[dict]:
    """Quita ejemplos del final (los menos parecidos, en RAG) hasta que el prompt quepa."""
    if not system:
        from llm.schema_context import get_schema_context
        from llm.text_to_sql import SQL_SYSTEM_PROMPT_TEMPLATE

        system = SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema_context())
    ejemplos = list(ejemplos)
    while ejemplos and not cabe(system, prompt_base, texto_bloque(ejemplos, recuperados), num_ctx):
        ejemplos.pop()
    return ejemplos
