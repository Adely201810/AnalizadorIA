"""
Costo en tokens REALES (tokenizador del modelo vía Ollama, sin caché) del bloque de ejemplos del banco
(D-43) y cuántos caben en num_ctx junto con el system prompt (esquema compacto), la pregunta más larga
de la evaluación, la reserva del reintento y num_predict.

Uso: python -m eval.medir_presupuesto_ejemplos [--modelo qwen2.5-coder:7b-instruct-q4_K_M]
Escribe eval/resultados_modos/presupuesto_tokens_<modelo>.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm import fewshot
from llm.banco_ejemplos.construir import preguntas_evaluacion
from llm.ollama_client import DEFAULT_MODEL, OllamaClient
from llm.schema_context import get_schema_context
from llm.text_to_sql import SQL_SYSTEM_PROMPT_TEMPLATE

RAIZ = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default=DEFAULT_MODEL)
    ap.add_argument("--num-ctx", type=int, default=8192)
    a = ap.parse_args()
    c = OllamaClient(model=a.modelo, num_ctx=a.num_ctx)
    system = SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema_context())
    pregunta = max((q["pregunta"] for q in preguntas_evaluacion()), key=len)
    t_system = c.contar_tokens(system)
    t_preg = c.contar_tokens(f"Pregunta: {pregunta}")
    limite = int((1 - fewshot.MARGEN) * a.num_ctx)
    fijo = t_system + t_preg + fewshot.RESERVA_REINTENTO_TOKENS + fewshot.NUM_PREDICT_SQL
    filas = []
    for con_resp in (False, True):
        for n in range(1, 11):
            ej = [{"entrada": e, "similitud": None} for e in fewshot.ejemplos_fijos(n)]
            t_bloque = c.contar_tokens(fewshot.texto_bloque(ej, recuperados=False, con_respuesta=con_resp))
            total = fijo + t_bloque
            filas.append({"n": n, "con_respuesta": con_resp, "tokens_bloque": t_bloque, "total": total,
                          "cabe": total <= limite})
            print(f"N={n:2d} respuesta={'sí' if con_resp else 'no'} bloque={t_bloque:5d} total={total:5d} "
                  f"{'cabe' if total <= limite else 'NO cabe'} (límite {limite})", flush=True)
    salida = {"modelo": a.modelo, "num_ctx": a.num_ctx, "limite_90pct": limite, "tokens_system": t_system,
              "tokens_pregunta_mas_larga": t_preg, "reserva_reintento": fewshot.RESERVA_REINTENTO_TOKENS,
              "num_predict": fewshot.NUM_PREDICT_SQL, "filas": filas,
              "max_n_sin_respuesta": max((f["n"] for f in filas if not f["con_respuesta"] and f["cabe"]), default=0),
              "max_n_con_respuesta": max((f["n"] for f in filas if f["con_respuesta"] and f["cabe"]), default=0)}
    destino = RAIZ / "eval" / "resultados_modos" / f"presupuesto_tokens_{a.modelo.split(':')[0].replace('.', '_')}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"system={t_system} pregunta={t_preg} | máx N sin respuesta={salida['max_n_sin_respuesta']} "
          f"con respuesta={salida['max_n_con_respuesta']} | {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
