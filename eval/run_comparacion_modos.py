"""
Comparación Base | Few-shot | RAG | Harness (mejoras del profesor, fase F; D-46).

Matriz: modos × modelos × conjuntos (los 6 casos del juez y DESARROLLO 30) × repeticiones. Todas las
configuraciones usan el pipeline real (`answer_question`), sin plantillas (como los A/B desde la etapa 2),
la temperatura de evaluación (0.3, D-28) y las MISMAS semillas por repetición (rep k -> seed 42 + k - 1,
igual en todos los modos y modelos).

Veredicto (determinista, sin LLM):
  - desarrollo: el árbitro de siempre (eval/run_eval.calificar -> eval/comparador.py);
  - casos_juez: el criterio de cada caso (llm/juez.veredicto_caso).

Intentos: base/fewshot/rag = 2 (el chat); harness = 5 con verificador sin oráculo (llm/harness.py).

Salida en eval/resultados_modos/:
  corridas/<modelo>__<modo>__<conjunto>__r<k>.json   un JSON por corrida (una pregunta por registro)
  resumen.json / resumen.csv / resumen.md            con --resumir

Uso:
  python -m eval.run_comparacion_modos --modelos qwen2.5-coder:7b-instruct-q4_K_M --modos base fewshot rag harness --conjuntos casos_juez
  python -m eval.run_comparacion_modos --resumir
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "eval" / "resultados_modos"
CORRIDAS = SALIDA / "corridas"
MODOS = ("base", "fewshot", "rag", "harness")
CONJUNTOS = ("casos_juez", "desarrollo")
TEMPERATURA = 0.3
SEED_BASE = 42


def _slug(modelo: str) -> str:
    return modelo.split(":")[0].replace(".", "_")


def _preguntas(conjunto: str) -> list[dict]:
    if conjunto == "casos_juez":
        casos = json.loads((RAIZ / "eval" / "casos_juez.json").read_text(encoding="utf-8"))["casos"]
        return [{"id": c["id"], "pregunta": c["pregunta"], "caso": c} for c in casos]
    gt = json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]
    return [q for q in gt if q["conjunto"] == "desarrollo"]


def correr(modelo: str, modo: str, conjunto: str, rep: int, num_ctx: int) -> dict:
    from eval.run_eval import calificar
    from llm.harness import ClienteMedido, registro_por_intento
    from llm.juez import veredicto_caso
    from llm.ollama_client import OllamaClient
    from llm.text_to_sql import Text2SQLResult, answer_question, execute_readonly

    seed = SEED_BASE + rep - 1
    base = OllamaClient(model=modelo, num_ctx=num_ctx)
    base.temperature = TEMPERATURA
    registros = []
    t_total = time.perf_counter()
    for i, item in enumerate(_preguntas(conjunto), 1):
        medido = ClienteMedido(base, seed=seed)
        t0 = time.perf_counter()
        try:
            r = answer_question(item["pregunta"], client=medido, usar_plantillas=False, modo=modo)
        except Exception as exc:  # noqa: BLE001 - una pregunta rota no tumba la corrida
            r = Text2SQLResult(pregunta=item["pregunta"], error=f"excepción {type(exc).__name__}: {exc}", modo=modo)
        seg = time.perf_counter() - t0
        if "caso" in item:
            ok = (not r.error and not r.sub_consultas) and veredicto_caso(item["caso"], [list(f) for f in r.filas])["correcto"]
            motivo = "criterio del caso" if ok else (r.error or "no cumple el criterio del caso")
        else:
            _, filas_ref = execute_readonly(item["sql_referencia"], limite_s=None)
            ok, motivo = calificar(item, r, filas_ref)
        registros.append({
            "id": item["id"], "correcto": bool(ok), "motivo": motivo, "sql": r.sql, "intentos": r.intentos,
            "error": r.error, "filas_modelo": [list(f) for f in r.filas[:5]], "segundos": round(seg, 2),
            "ejemplos_usados": r.ejemplos_usados, "tokens": medido.resumen(),
            "registro_por_intento": registro_por_intento(r, medido),
        })
        print(f"[{_slug(modelo)} {modo} {conjunto} r{rep}] {i:2d} {item['id'][:38]:38s} {'✔' if ok else '✘'} "
              f"int={r.intentos} tok_sql={medido.resumen()['tokens_prompt_sql']} {seg:.1f}s", flush=True)
    aciertos = sum(x["correcto"] for x in registros)
    return {
        "modelo": modelo, "modo": modo, "conjunto": conjunto, "repeticion": rep, "seed": seed,
        "temperatura": TEMPERATURA, "num_ctx": num_ctx, "fecha": datetime.now().isoformat(timespec="seconds"),
        "aciertos": aciertos, "preguntas": len(registros), "segundos_totales": round(time.perf_counter() - t_total, 1),
        "resultados": registros,
    }


def resumir() -> dict:
    filas = []
    corridas = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(CORRIDAS.glob("*.json"))]
    grupos: dict[tuple, list[dict]] = {}
    for c in corridas:
        grupos.setdefault((c["modelo"], c["conjunto"], c["modo"]), []).append(c)
    for (modelo, conjunto, modo), cs in sorted(grupos.items(), key=lambda kv: (kv[0][0], kv[0][1], MODOS.index(kv[0][2]))):
        cs = sorted(cs, key=lambda c: c["repeticion"])
        res = [r for c in cs for r in c["resultados"]]
        aciertos = [c["aciertos"] for c in cs]
        filas.append({
            "modelo": modelo, "conjunto": conjunto, "modo": modo, "repeticiones": len(cs), "preguntas": cs[0]["preguntas"],
            "aciertos": aciertos, "media": round(statistics.mean(aciertos), 2), "minimo": min(aciertos),
            "tokens_prompt_sql_por_pregunta": round(statistics.mean(r["tokens"]["tokens_prompt_sql"] for r in res), 1),
            "caracteres_prompt_sql_max_medio": round(statistics.mean(r["tokens"]["caracteres_prompt_sql_max"] for r in res), 1),
            "segundos_por_pregunta": round(statistics.mean(r["segundos"] for r in res), 2),
            "intentos_medios": round(statistics.mean(r["intentos"] or 0 for r in res), 2),
            "preguntas_con_ejemplos": round(statistics.mean(bool(r["ejemplos_usados"]) for r in res) * 100, 1),
            "por_pregunta": {pid: sum(r["correcto"] for r in res if r["id"] == pid) for pid in dict.fromkeys(r["id"] for r in res)},
        })
    # Regla D-23 frente a base (mismo modelo y conjunto).
    for f in filas:
        b = next((x for x in filas if x["modelo"] == f["modelo"] and x["conjunto"] == f["conjunto"] and x["modo"] == "base"), None)
        if b and f["modo"] != "base" and b["repeticiones"] >= 3 and f["repeticiones"] >= 3:
            f["d23_vs_base"] = f["media"] >= b["media"] + 1 and f["minimo"] >= b["media"]
        else:
            f["d23_vs_base"] = None
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "resumen.json").write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
    campos = ["modelo", "conjunto", "modo", "repeticiones", "preguntas", "aciertos", "media", "minimo", "d23_vs_base",
              "tokens_prompt_sql_por_pregunta", "caracteres_prompt_sql_max_medio", "segundos_por_pregunta",
              "intentos_medios", "preguntas_con_ejemplos"]
    with (SALIDA / "resumen.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for f in filas:
            w.writerow({**f, "aciertos": " ".join(map(str, f["aciertos"]))})
    lineas = ["| Modelo | Conjunto | Modo | Aciertos (por repetición) | Media | Mínimo | ¿Mejora D-23 vs Base? | "
              "Tokens de prompt SQL por pregunta | s/pregunta | Intentos medios | % preguntas con ejemplos |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in filas:
        d23 = {True: "sí", False: "no", None: "—"}[f["d23_vs_base"]]
        lineas.append(f"| {f['modelo'].split(':')[0]} | {f['conjunto']} | {f['modo']} | {', '.join(map(str, f['aciertos']))} "
                      f"(de {f['preguntas']}) | {f['media']} | {f['minimo']} | {d23} | {f['tokens_prompt_sql_por_pregunta']} | "
                      f"{f['segundos_por_pregunta']} | {f['intentos_medios']} | {f['preguntas_con_ejemplos']} |")
    (SALIDA / "resumen.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))
    return {"filas": filas}


def main() -> int:
    from llm.ollama_client import DEFAULT_MODEL

    ap = argparse.ArgumentParser()
    ap.add_argument("--modelos", nargs="+", default=[DEFAULT_MODEL])
    ap.add_argument("--modos", nargs="+", default=list(MODOS), choices=MODOS)
    ap.add_argument("--conjuntos", nargs="+", default=list(CONJUNTOS), choices=CONJUNTOS)
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--resumir", action="store_true")
    a = ap.parse_args()
    if a.resumir:
        resumir()
        return 0
    CORRIDAS.mkdir(parents=True, exist_ok=True)
    for modelo in a.modelos:
        for conjunto in a.conjuntos:
            for modo in a.modos:
                for rep in range(1, a.repeticiones + 1):
                    destino = CORRIDAS / f"{_slug(modelo)}__{modo}__{conjunto}__r{rep}.json"
                    if destino.exists():
                        print(f"ya existe {destino.name}; se salta", flush=True)
                        continue
                    datos = correr(modelo, modo, conjunto, rep, a.num_ctx)
                    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
                    print(f"== {destino.name}: {datos['aciertos']}/{datos['preguntas']} en {datos['segundos_totales']} s",
                          flush=True)
    resumir()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
