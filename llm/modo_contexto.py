"""
Modo de contexto del generador de SQL (mejoras del profesor; D-42):

  base     el pipeline actual, sin ejemplos del banco de necesidades (POR DEFECTO)
  fewshot  + N ejemplos FIJOS del banco (llm/fewshot.py)
  rag      + los k ejemplos del banco más parecidos a la pregunta (llm/rag.py)
  harness  rag + hasta 5 intentos con verificador sin oráculo (llm/harness.py)

Se elige con TEXT2SQL_MODO_CONTEXTO o con `answer_question(modo=...)`. El bloque de ejemplos va en
el prompt de USUARIO, así el system prompt (esquema) sigue siendo idéntico y cacheable.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

MODOS = ("base", "fewshot", "rag", "harness")
MODO_POR_DEFECTO = os.environ.get("TEXT2SQL_MODO_CONTEXTO", "base")
if MODO_POR_DEFECTO not in MODOS:
    raise ValueError(f"TEXT2SQL_MODO_CONTEXTO={MODO_POR_DEFECTO!r}; usa uno de {MODOS}")

_modo: ContextVar[str | None] = ContextVar("modo_contexto", default=None)


def modo_actual() -> str:
    return _modo.get() or MODO_POR_DEFECTO


@contextmanager
def usar_modo(modo: str | None):
    if modo is not None and modo not in MODOS:
        raise ValueError(f"modo desconocido: {modo!r}; usa uno de {MODOS}")
    token = _modo.set(modo)
    try:
        yield
    finally:
        _modo.reset(token)


def bloque_para(pregunta: str, prompt_base: str = "", system: str = "") -> tuple[str | None, list[dict]]:
    """(texto a inyectar en el prompt de usuario o None, ejemplos usados con su similitud).
    El bloque se recorta para que el prompt completo quepa en num_ctx (llm/fewshot.py)."""
    modo = modo_actual()
    if modo == "base":
        return None, []
    from llm import fewshot

    if modo == "fewshot":
        ejemplos = [{"entrada": e, "similitud": None} for e in fewshot.ejemplos_fijos()]
        recuperados = False
    else:
        from llm import rag

        ejemplos = [{"entrada": e, "similitud": s} for e, s in rag.recuperar(pregunta)]
        recuperados = True
    ejemplos = fewshot.ajustar_a_presupuesto(ejemplos, system=system, prompt_base=prompt_base, recuperados=recuperados)
    if not ejemplos:
        return None, []
    usados = [{"id": x["entrada"]["id"], "familia": x["entrada"]["familia"], "pregunta": x["entrada"]["pregunta"],
               "similitud": None if x["similitud"] is None else round(x["similitud"], 3)} for x in ejemplos]
    return fewshot.texto_bloque(ejemplos, recuperados=recuperados), usados
