"""
Recalifica una corrida guardada con el árbitro determinista actual
(eval/comparador.py), volviendo a ejecutar EN SOLO LECTURA el SQL que el
modelo generó en esa corrida. Sirve para separar el efecto del evaluador del
efecto de los cambios en el pipeline (docs/FASE_03.md).

Uso:
    python -m eval.recalificar eval/baselines/baseline_00_actual.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from eval.comparador import comparar
from llm.text_to_sql import execute_readonly

GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth_olist.json"
GROUND_TRUTH_V1_PATH = Path(__file__).resolve().parent / "ground_truth_olist_v1.json"


def recalificar(path: Path) -> list[dict]:
    # Las corridas viejas (baseline_00/01) usan ids del oráculo v1.
    gt = {}
    for ruta in (GROUND_TRUTH_V1_PATH, GROUND_TRUTH_PATH):
        gt.update({q["id"]: q for q in json.loads(ruta.read_text(encoding="utf-8"))["preguntas"]})
    corrida = json.loads(path.read_text(encoding="utf-8"))
    filas_out = []
    for r in corrida["resultados"]:
        item = gt[r["id"]]
        _, ref = execute_readonly(item["sql_referencia"], limite_s=None)
        sql = r.get("sql_generado")
        antes = r.get("correcto", r.get("sql_correcto"))
        if not sql:
            ahora, motivo = False, "sin SQL generado"
        elif "\n\n" in sql.strip():
            ahora, motivo = False, "varias sub-consultas (sin resultado único)"
        else:
            try:
                _, filas = execute_readonly(sql)
                v = comparar(filas, ref, item["tipos_columnas"], item.get("orden_importa", False))
                ahora, motivo = v.correcto, v.motivo
            except sqlite3.Error as exc:
                ahora, motivo = False, f"el SQL no ejecuta: {exc}"
        filas_out.append({"id": r["id"], "antes": antes, "ahora": ahora, "motivo": motivo})
    return filas_out


if __name__ == "__main__":
    resultado = recalificar(Path(sys.argv[1]))
    for f in resultado:
        print(f"{f['id']:38s} antes={'✅' if f['antes'] else '❌'}  ahora={'✅' if f['ahora'] else '❌'}  {f['motivo']}")
    print(f"TOTAL antes {sum(f['antes'] for f in resultado)}/{len(resultado)}  ahora {sum(f['ahora'] for f in resultado)}/{len(resultado)}")
