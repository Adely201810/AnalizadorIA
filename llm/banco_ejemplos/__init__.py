"""
Banco de necesidades negativas (D-41): preguntas parecidas a las necesidades reales 2, 4, 5, 6 y 8,
ya resueltas y verificadas contra la base. Lo usan el few-shot fijo (llm/fewshot.py) y el RAG
(llm/rag.py). Se genera con `python -m llm.banco_ejemplos.construir` -> data/necesidades_negativas.json.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
BANCO_PATH = RAIZ / "data" / "necesidades_negativas.json"


@lru_cache(maxsize=1)
def cargar_banco() -> list[dict]:
    return json.loads(BANCO_PATH.read_text(encoding="utf-8"))["necesidades"]


def familias() -> list[str]:
    return list(dict.fromkeys(e["familia"] for e in cargar_banco()))
