"""
Similitud léxica entre textos (preguntas o SQL), para comprobar que los
ejemplos few-shot del prompt (llm/schema_context.py) no repiten preguntas del
oráculo de evaluación (eval/ground_truth_olist.json).

Métrica: índice de Jaccard sobre el conjunto de tokens significativos
(minúsculas, sin acentos, sin palabras vacías). 0 = nada en común, 1 = iguales.

Uso:
    python -m eval.similitud      # matriz few-shot x oráculo (texto y SQL)
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth_olist.json"

_PALABRAS_VACIAS = set("""
a al algo como con cual cuales cuanto cuantos cuantas de del desde donde el ella en entre es esta este
hay la las le les lo los mas me mi mis muy no o para pero por que se si sin sobre su sus tiene tienen
un una uno y ya qué cuál cuáles cuánto cuántos
""".split())
_SQL_IGNORAR = set("select from where and or as on join left group by order desc asc limit not in is null".split())


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn")


def tokens_texto(texto: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", _normalizar(texto)) if t not in _PALABRAS_VACIAS and len(t) > 2}


def tokens_sql(sql: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", sql.lower()) if t not in _SQL_IGNORAR and not t.isdigit()}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def preguntas_oraculo() -> list[dict]:
    return json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))["preguntas"]


def matriz(ejemplos: list[tuple[str, str]]) -> list[dict]:
    """Por cada ejemplo few-shot: la pregunta del oráculo más parecida en texto
    y la más parecida en SQL, con su índice de Jaccard."""
    oraculo = preguntas_oraculo()
    filas = []
    for pregunta, sql in ejemplos:
        tt = tokens_texto(pregunta)
        ts = tokens_sql(sql)
        mejor_texto = max(oraculo, key=lambda q: jaccard(tt, tokens_texto(q["pregunta"])))
        mejor_sql = max(oraculo, key=lambda q: jaccard(ts, tokens_sql(q["sql_referencia"])))
        filas.append({
            "ejemplo": pregunta,
            "oraculo_texto": mejor_texto["id"],
            "jaccard_texto": round(jaccard(tt, tokens_texto(mejor_texto["pregunta"])), 3),
            "oraculo_sql": mejor_sql["id"],
            "jaccard_sql": round(jaccard(ts, tokens_sql(mejor_sql["sql_referencia"])), 3),
        })
    return filas


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from llm.schema_context import EJEMPLOS_FEW_SHOT

    print(f"{'ejemplo few-shot':70s} | {'oráculo + parecido (texto)':38s} | {'oráculo + parecido (SQL)'}")
    for f in matriz(EJEMPLOS_FEW_SHOT):
        print(f"{f['ejemplo'][:70]:70s} | {f['oraculo_texto']:30s} {f['jaccard_texto']:.3f} | {f['oraculo_sql']:30s} {f['jaccard_sql']:.3f}")
