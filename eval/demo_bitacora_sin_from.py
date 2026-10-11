"""
Etapa 2, Paso 4: ¿la bitácora evita, con el modelo REAL, que se repita el error
"SELECT principal sin FROM"? Pregunta n01 (DESARROLLO; nunca PRUEBA).

  A) sin bitácora                       (como la evaluación)
  B) bitácora con la entrada select_sin_from, registrada desde OTRA pregunta

K corridas por condición; cada corrida de B parte de una bitácora nueva y
temporal (no la de la app), así ninguna condición "aprende" a mitad del experimento.
Mide: intentos con SELECT sin FROM (diagnosticados con llm.bitacora) y aciertos
según el árbitro (eval.run_eval.calificar).

Uso: python -m eval.demo_bitacora_sin_from --k 6
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from eval.run_eval import calificar
from llm.bitacora import BitacoraEsquema, diagnostico_select_sin_from
from llm.ollama_client import OllamaClient
from llm.text_to_sql import answer_question, execute_readonly

RAIZ = Path(__file__).resolve().parent.parent
QID = "n01_pct_clientes_recurrentes"


def _sin_from(intento: dict) -> bool:
    det = intento.get("detalle") or ""
    if not det.startswith("Error de SQLite"):
        return False
    return diagnostico_select_sin_from(intento.get("sql"), det.split(": ", 1)[1]) is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=6)
    args = ap.parse_args()
    gt = {q["id"]: q for q in json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]}
    item = gt[QID]
    assert item["conjunto"] == "desarrollo"
    _, ref = execute_readonly(item["sql_referencia"], limite_s=None)
    client = OllamaClient()
    salida = {"pregunta": QID, "modelo": client.model, "k": args.k, "condiciones": {}}
    for cond in ("A_sin_bitacora", "B_con_bitacora"):
        corridas = []
        for k in range(args.k):
            with tempfile.TemporaryDirectory() as tmp:
                bitacora = None
                if cond.startswith("B"):
                    bitacora = BitacoraEsquema(Path(tmp) / "b.json")
                    bitacora.registrar([{"tipo": "select_sin_from", "columna": "customer_unique_id"}],
                                       "¿Qué parte de los compradores repitió compra?")
                r = answer_question(item["pregunta"], client=client, usar_plantillas=False, bitacora=bitacora)
            correcto, _ = calificar(item, r, ref)
            n_sin_from = sum(_sin_from(i) for i in r.intentos_detalle)
            corridas.append({"correcto": correcto, "intentos": len(r.intentos_detalle),
                             "intentos_sin_from": n_sin_from,
                             "primer_intento_sin_from": bool(r.intentos_detalle) and _sin_from(r.intentos_detalle[0]),
                             "tipos": [i["tipo"] for i in r.intentos_detalle],
                             "sql_final": (r.sql or "")[:300]})
            print(f"[{cond} {k + 1}/{args.k}] correcto={correcto} tipos={corridas[-1]['tipos']} "
                  f"sin_from={n_sin_from} sql={(r.sql or '')[:110]!r}", flush=True)
        salida["condiciones"][cond] = {
            "corridas": corridas,
            "aciertos": sum(c["correcto"] for c in corridas),
            "corridas_con_sin_from": sum(c["intentos_sin_from"] > 0 for c in corridas),
            "intentos_sin_from": sum(c["intentos_sin_from"] for c in corridas),
            "intentos_totales": sum(c["intentos"] for c in corridas),
        }
    destino = RAIZ / "eval" / "baselines" / "etapa2" / "p4_demo_bitacora_sin_from.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    for cond, d in salida["condiciones"].items():
        print(f"== {cond}: aciertos {d['aciertos']}/{args.k} | corridas con SELECT sin FROM "
              f"{d['corridas_con_sin_from']}/{args.k} | intentos sin FROM {d['intentos_sin_from']}/{d['intentos_totales']}")


if __name__ == "__main__":
    main()
