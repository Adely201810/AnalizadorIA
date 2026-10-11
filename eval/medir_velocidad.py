"""
Benchmark fijo de velocidad por modelo (Paso 0 de la segunda etapa).

Mismo prompt, temperature=0, seed fija y num_predict fijo para todos los
modelos. Por modelo: descarga los demás de la VRAM, carga el modelo (se mide
aparte), y hace N llamadas midiendo tokens/s de evaluación del prompt y de
generación (contadores de /api/generate). Al final registra `ollama ps`
(tamaño, VRAM, % en GPU).

Uso:
    python -m eval.medir_velocidad --modelos llama3.1:8b-instruct-q4_K_M qwen2.5-coder:7b-instruct-q4_K_M --num-ctx 4096 8192
"""
from __future__ import annotations

import argparse
import json
import statistics
import time

import requests

HOST = "http://localhost:11434"
PROMPT = ("Explica en un párrafo de unas 120 palabras qué es una base de datos relacional, "
          "qué es una llave primaria y para qué sirve un JOIN.")


def descargar_todo() -> None:
    for m in requests.get(f"{HOST}/api/ps", timeout=10).json().get("models", []):
        requests.post(f"{HOST}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)


def generar(modelo: str, num_ctx: int) -> dict:
    r = requests.post(f"{HOST}/api/generate", json={
        "model": modelo, "prompt": PROMPT, "stream": False,
        "options": {"num_ctx": num_ctx, "num_predict": 160, "temperature": 0, "seed": 42},
    }, timeout=900).json()
    return {
        "carga_s": round(r["load_duration"] / 1e9, 2),
        "prompt_tok_s": round(r["prompt_eval_count"] / (r["prompt_eval_duration"] / 1e9), 1),
        "gen_tokens": r["eval_count"],
        "gen_tok_s": round(r["eval_count"] / (r["eval_duration"] / 1e9), 2),
    }


def ps(modelo: str) -> dict | None:
    for m in requests.get(f"{HOST}/api/ps", timeout=10).json().get("models", []):
        if m["name"] == modelo:
            return {"size_gb": round(m["size"] / 1e9, 2), "vram_gb": round(m["size_vram"] / 1e9, 2),
                    "pct_gpu": round(100 * m["size_vram"] / m["size"], 1), "contexto": m.get("context_length")}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelos", nargs="+", required=True)
    ap.add_argument("--num-ctx", nargs="+", type=int, default=[8192])
    ap.add_argument("--repeticiones", type=int, default=3)
    args = ap.parse_args()
    filas = []
    for modelo in args.modelos:
        for ctx in args.num_ctx:
            descargar_todo()
            t = time.perf_counter()
            primera = generar(modelo, ctx)  # incluye la carga
            carga_total = round(time.perf_counter() - t, 1)
            medidas = [generar(modelo, ctx) for _ in range(args.repeticiones)]
            gen = [m["gen_tok_s"] for m in medidas]
            fila = {"modelo": modelo, "num_ctx": ctx, "carga_s": primera["carga_s"], "primera_llamada_s": carga_total,
                    "gen_tok_s": gen, "gen_tok_s_media": round(statistics.mean(gen), 2),
                    "prompt_tok_s": [m["prompt_tok_s"] for m in medidas], "ollama_ps": ps(modelo)}
            print(json.dumps(fila, ensure_ascii=False), flush=True)
            filas.append(fila)
    print("\n| Modelo | num_ctx | Carga | Generación tok/s (3 rep.) | Media | ollama ps |")
    print("|---|---|---|---|---|---|")
    for f in filas:
        p = f["ollama_ps"] or {}
        print(f"| {f['modelo']} | {f['num_ctx']} | {f['carga_s']} s | {f['gen_tok_s']} | {f['gen_tok_s_media']} | "
              f"{p.get('size_gb')} GB, VRAM {p.get('vram_gb')} GB ({p.get('pct_gpu')} % GPU) |")


if __name__ == "__main__":
    main()
