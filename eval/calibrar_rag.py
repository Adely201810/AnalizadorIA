"""
Calibra el RAG (D-44) SIN usar preguntas de evaluación.

- Consultas POSITIVAS: cada variante de cada necesidad negativa, buscando en el banco SIN su propia
  necesidad (leave-one-out). Acierta la familia si el top-1 es de su misma familia.
- UMBRAL = percentil 5 de la similitud top-1 de las positivas: se inyecta un ejemplo si la pregunta se
  parece al banco al menos tanto como el 95 % de las paráfrasis genuinas del banco.
- Comprobación: preguntas AJENAS a la base (OFF_TOPIC) deben quedar por debajo del umbral.
- Informativo: preguntas genéricas del dominio (10 ejemplos del esquema + 32 del banco E5). NO se usan
  para fijar el umbral: muchas son de pagos, reseñas o flete, es decir, de las mismas familias (primera
  versión de esta calibración, descartada; ver D-44).

Elige el motor con mayor precisión de familia top-1 (empate: más preguntas ajenas bajo el umbral) y
lo guarda en data/indice_rag/umbrales.json.

Uso: python -m eval.calibrar_rag
"""
from __future__ import annotations

import json
import statistics
from collections import Counter

from llm import rag
from llm.banco_ejemplos import cargar_banco
from llm.contexto_e3 import banco as banco_e5
from llm.schema_context import EJEMPLOS_FEW_SHOT


# Preguntas que no tienen nada que ver con la base de Olist (comprobación del umbral).
OFF_TOPIC = [
    "¿Qué tiempo hará mañana en Lima?",
    "Recomiéndame una película de ciencia ficción para el fin de semana.",
    "¿Cómo se prepara un ceviche peruano?",
    "Traduce 'buenos días' al francés.",
    "¿Quién ganó el mundial de fútbol de 2010?",
    "Escribe un poema corto sobre el mar.",
    "¿Cuál es la capital de Australia?",
    "Explícame qué es la fotosíntesis.",
    "¿Cuántos planetas tiene el sistema solar?",
    "Dame un consejo para dormir mejor.",
    "¿Cómo instalo Python en Windows?",
    "¿Qué significa la palabra 'resiliencia'?",
]


def _percentil(valores: list[float], p: float) -> float:
    v = sorted(valores)
    i = (len(v) - 1) * p
    lo, hi = int(i), min(int(i) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def evaluar_motor(motor: str) -> dict:
    banco = cargar_banco()
    familia = {e["id"]: e["familia"] for e in banco}
    pos, top1_ok, top3_ok = [], 0, 0
    for e in banco:
        for v in e["variantes"]:
            p = rag.puntuaciones(v, motor, excluir=frozenset({e["id"]}))
            pos.append(p[0][1])
            top1_ok += familia[p[0][0]] == e["familia"]
            fam3 = Counter(familia[i] for i, _ in p[:3]).most_common(1)[0][0]
            top3_ok += fam3 == e["familia"]
    umbral = _percentil(pos, 0.05)
    ajenas = [rag.puntuaciones(q, motor)[0][1] for q in OFF_TOPIC]
    genericas = [q for q, _ in EJEMPLOS_FEW_SHOT] + [q for q, _ in banco_e5()]
    gen = [rag.puntuaciones(q, motor)[0][1] for q in genericas]
    return {
        "consultas_positivas": len(pos),
        "precision_familia_top1": round(top1_ok / len(pos), 3), "precision_familia_top3_mayoria": round(top3_ok / len(pos), 3),
        "similitud_top1_positivas": {"media": round(statistics.mean(pos), 3), "min": round(min(pos), 3),
                                     "p5": round(umbral, 4)},
        "umbral": round(umbral, 4),
        "ajenas_bajo_umbral": f"{sum(s < umbral for s in ajenas)}/{len(ajenas)}",
        "similitud_top1_ajenas": {"media": round(statistics.mean(ajenas), 3), "max": round(max(ajenas), 3)},
        "genericas_dominio_sobre_umbral (se inyectaria)": f"{sum(s >= umbral for s in gen)}/{len(gen)}",
        "_ajenas_bajo": sum(s < umbral for s in ajenas),
    }


def main() -> int:
    salida = {"descripcion": __doc__.strip().splitlines()[0], "hash_banco": rag.hash_banco(),
              "modelo_embeddings": rag.MODELO_EMBEDDINGS}
    for motor in rag.MOTORES:
        salida[motor] = evaluar_motor(motor)
        print(motor, json.dumps(salida[motor], ensure_ascii=False))
    salida["motor_elegido"] = max(rag.MOTORES, key=lambda m: (salida[m]["precision_familia_top1"],
                                                               salida[m]["_ajenas_bajo"]))
    print("motor elegido:", salida["motor_elegido"])
    rag.DIR_INDICE.mkdir(parents=True, exist_ok=True)
    (rag.DIR_INDICE / "umbrales.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Escrito {rag.DIR_INDICE / 'umbrales.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
