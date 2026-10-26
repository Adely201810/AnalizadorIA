"""
RAG sobre el banco de necesidades negativas (mejoras del profesor, fase C; D-44).

Documentos: la pregunta y cada variante de cada necesidad (la puntuación de una necesidad es la
mejor de sus documentos). Dos motores:

  embeddings  nomic-embed-text vía Ollama (/api/embed), similitud coseno. Prefijos "search_document:" y
              "search_query:", que es como se entrenó el modelo.
  tfidf       sin dependencias: minúsculas, sin acentos, sin palabras vacías, raíz ligera (quita plurales
              y algunos sufijos), unigramas + bigramas, tf sublineal, coseno.

El índice se guarda en data/indice_rag/<motor>.json con el hash del banco. Si el banco no cambió, se
recarga sin recalcular; si cambió, se reconstruye.

`recuperar(pregunta, k)` devuelve [(necesidad, similitud)] de los k más parecidos POR ENCIMA del umbral
del motor. Si ninguno lo supera, devuelve [] y no se inyecta nada (mejor sin ejemplo que con uno engañoso).
Motor: TEXT2SQL_RAG_MOTOR (por defecto, el elegido en la calibración; D-44). k: TEXT2SQL_RAG_K (3).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter
from functools import lru_cache

import requests

from llm.banco_ejemplos import RAIZ, cargar_banco

DIR_INDICE = RAIZ / "data" / "indice_rag"
MODELO_EMBEDDINGS = os.environ.get("TEXT2SQL_RAG_MODELO_EMBEDDINGS", "nomic-embed-text")
MOTORES = ("embeddings", "tfidf")
K_POR_DEFECTO = int(os.environ.get("TEXT2SQL_RAG_K", "3"))
# Umbrales y motor elegido: eval/calibrar_rag.py, SOLO con el banco (consultas = variantes, dejando fuera su
# propia necesidad) y preguntas genéricas no relacionadas (ejemplos genéricos del esquema y del banco E5). D-44.
_UMBRALES_PATH = DIR_INDICE / "umbrales.json"
UMBRALES_SIN_CALIBRAR = {"embeddings": 0.0, "tfidf": 0.0}


def _calibracion() -> dict:
    return json.loads(_UMBRALES_PATH.read_text(encoding="utf-8")) if _UMBRALES_PATH.exists() else {}


MOTOR_POR_DEFECTO = os.environ.get("TEXT2SQL_RAG_MOTOR") or _calibracion().get("motor_elegido", "tfidf")

# ----------------------------------------------------------------- normalización (motor tfidf)
_VACIAS = set("""
a al algo algun alguna ante como con cual cuales cuanto cuantos cuanta cuantas de del desde donde e el ella ellos en
entre era es esa ese eso esta este esto estos hay la las le les lo los mas me mi mis muy ni no o otra otro para pero
por que se segun ser si sin sobre su sus tiene tienen un una uno unos unas y ya dame
""".split())


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _raiz(p: str) -> str:
    for suf in ("aciones", "acion", "mente", "idades", "idad", "es", "s"):
        if len(p) > len(suf) + 3 and p.endswith(suf):
            return p[: -len(suf)]
    return p


def terminos(texto: str) -> list[str]:
    palabras = [_raiz(w) for w in re.findall(r"[a-z0-9_]+", normalizar(texto)) if w not in _VACIAS and len(w) > 1]
    return palabras + [f"{a}_{b}" for a, b in zip(palabras, palabras[1:])]


# ----------------------------------------------------------------- documentos e índice
def _documentos() -> list[tuple[str, str]]:
    """[(id de la necesidad, texto)] con la pregunta y cada variante."""
    return [(e["id"], t) for e in cargar_banco() for t in [e["pregunta"], *e.get("variantes", [])]]


def hash_banco() -> str:
    return hashlib.sha256(json.dumps(_documentos(), ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _embed(textos: list[str], host: str | None = None) -> list[list[float]]:
    from llm.ollama_client import OLLAMA_HOST

    r = requests.post(f"{host or OLLAMA_HOST}/api/embed", json={"model": MODELO_EMBEDDINGS, "input": textos},
                      timeout=120)
    r.raise_for_status()
    return r.json()["embeddings"]


def _unitario(v: dict[str, float] | list[float]):
    if isinstance(v, dict):
        n = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {k: x / n for k, x in v.items()}
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _construir(motor: str) -> dict:
    docs = _documentos()
    if motor == "embeddings":
        vectores = _embed([f"search_document: {t}" for _, t in docs])
        return {"motor": motor, "modelo": MODELO_EMBEDDINGS, "hash_banco": hash_banco(),
                "ids": [i for i, _ in docs], "vectores": [_unitario(v) for v in vectores]}
    tfs = [Counter(terminos(t)) for _, t in docs]
    df = Counter(w for tf in tfs for w in tf)
    n = len(docs)
    idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}
    vectores = [_unitario({w: (1 + math.log(c)) * idf[w] for w, c in tf.items()}) for tf in tfs]
    return {"motor": motor, "hash_banco": hash_banco(), "ids": [i for i, _ in docs], "idf": idf, "vectores": vectores}


@lru_cache(maxsize=4)
def indice(motor: str = MOTOR_POR_DEFECTO) -> dict:
    """Carga el índice de disco si corresponde al banco actual; si no, lo construye y lo guarda."""
    if motor not in MOTORES:
        raise ValueError(f"motor RAG desconocido: {motor!r}; usa uno de {MOTORES}")
    ruta = DIR_INDICE / f"{motor}.json"
    if ruta.exists():
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        vigente = datos.get("hash_banco") == hash_banco()
        if motor == "embeddings":
            vigente = vigente and datos.get("modelo") == MODELO_EMBEDDINGS
        if vigente:
            return datos
    datos = _construir(motor)
    DIR_INDICE.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


def umbral(motor: str) -> float:
    cal = _calibracion()
    return float(cal[motor]["umbral"]) if motor in cal else UMBRALES_SIN_CALIBRAR[motor]


@lru_cache(maxsize=512)
def _vector_consulta(pregunta: str, motor: str) -> tuple:
    if motor == "embeddings":
        return tuple(_unitario(_embed([f"search_query: {pregunta}"])[0]))
    idf = indice(motor)["idf"]
    tf = Counter(terminos(pregunta))
    return tuple(sorted(_unitario({w: (1 + math.log(c)) * idf[w] for w, c in tf.items() if w in idf}).items()))


def puntuaciones(pregunta: str, motor: str = MOTOR_POR_DEFECTO, excluir: frozenset = frozenset()) -> list[tuple[str, float]]:
    """[(id de necesidad, similitud)] de TODAS las necesidades, de mayor a menor."""
    ind = indice(motor)
    q = _vector_consulta(pregunta, motor)
    mejor: dict[str, float] = {}
    if motor == "embeddings":
        for i, v in zip(ind["ids"], ind["vectores"]):
            if i not in excluir:
                mejor[i] = max(mejor.get(i, -1.0), sum(a * b for a, b in zip(q, v)))
    else:
        qd = dict(q)
        for i, v in zip(ind["ids"], ind["vectores"]):
            if i not in excluir:
                mejor[i] = max(mejor.get(i, -1.0), sum(qd.get(w, 0.0) * x for w, x in v.items()))
    return sorted(mejor.items(), key=lambda x: (-x[1], x[0]))


def recuperar(pregunta: str, k: int | None = None, motor: str | None = None) -> list[tuple[dict, float]]:
    """Los k ejemplos más parecidos por encima del umbral del motor. Si el motor de embeddings no
    responde (Ollama caído o modelo sin descargar), se usa el de TF-IDF y se avisa en el log."""
    k = K_POR_DEFECTO if k is None else k
    motor = motor or MOTOR_POR_DEFECTO
    try:
        resultado = puntuaciones(pregunta, motor)
    except requests.RequestException as exc:
        if motor != "embeddings":
            raise
        import logging

        logging.getLogger(__name__).warning("RAG: embeddings no disponibles (%s); se usa tfidf", exc)
        motor, resultado = "tfidf", puntuaciones(pregunta, "tfidf")
    por_id = {e["id"]: e for e in cargar_banco()}
    u = umbral(motor)
    return [(por_id[i], s) for i, s in resultado[:k] if s >= u]
