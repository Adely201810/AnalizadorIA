"""
Fase 4: compara varios modelos locales sobre el oráculo (eval/ground_truth_olist.json)
con la MISMA configuración (sin plantillas, temperature y num_ctx del cliente,
max_retries=2), midiendo precisión real, desglose de fallos (Fase 2), latencia
y memoria.

Protocolo por modelo:
  1. Se descargan de la VRAM los demás modelos (keep_alive=0).
  2. Calentamiento: una llamada corta con num_ctx del pipeline (se mide el
     tiempo de carga aparte; no cuenta en la latencia de las preguntas).
  3. Desglose de latencia de la llamada que genera SQL (eval/medir_latencia.py).
  4. N repeticiones de eval/run_eval.py (subproceso). Durante cada corrida un
     hilo muestrea cada 5 s `ollama ps` (/api/ps: tamaño y VRAM) y la RAM del
     proceso llama-server.exe (tasklist), y se guarda el pico.

Uso:
    python -m eval.benchmark_modelos --modelos llama3.1:8b-instruct-q4_K_M qwen2.5-coder:7b-instruct-q4_K_M
    python -m eval.benchmark_modelos --modelos ... --repeticiones 2
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

from eval.medir_latencia import PREGUNTAS, llamada
from llm.ollama_client import OllamaClient
from llm.schema_context import get_schema_context
from llm.text_to_sql import SQL_SYSTEM_PROMPT_TEMPLATE

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "eval" / "baselines"


def slug(modelo: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", modelo.lower()).strip("_")


def descargar_de_vram(host: str) -> None:
    for m in requests.get(f"{host}/api/ps", timeout=10).json().get("models", []):
        requests.post(f"{host}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)


def ram_llama_server_mb() -> float:
    salida = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True,
    ).stdout
    total = 0.0
    for fila in csv.reader(io.StringIO(salida)):
        if len(fila) >= 5 and fila[0].lower() == "llama-server.exe":
            total += float(re.sub(r"[^\d]", "", fila[4]) or 0) / 1024  # "1.234.567 K" -> MB
    return round(total, 1)


class Muestreador(threading.Thread):
    def __init__(self, host: str, modelo: str):
        super().__init__(daemon=True)
        self.host, self.modelo = host, modelo
        self.parar = threading.Event()
        self.pico = {"size_gb": 0.0, "vram_gb": 0.0, "pct_gpu_min": None, "ram_llama_server_mb": 0.0}

    def run(self):
        while not self.parar.is_set():
            try:
                for m in requests.get(f"{self.host}/api/ps", timeout=5).json().get("models", []):
                    if m.get("name") == self.modelo:
                        size, vram = m.get("size", 0) / 1e9, m.get("size_vram", 0) / 1e9
                        self.pico["size_gb"] = round(max(self.pico["size_gb"], size), 2)
                        self.pico["vram_gb"] = round(max(self.pico["vram_gb"], vram), 2)
                        pct = round(100 * vram / size, 1) if size else None
                        if pct is not None:
                            actual = self.pico["pct_gpu_min"]
                            self.pico["pct_gpu_min"] = pct if actual is None else min(actual, pct)
                self.pico["ram_llama_server_mb"] = max(self.pico["ram_llama_server_mb"], ram_llama_server_mb())
            except Exception:  # noqa: BLE001 - el muestreo nunca debe tumbar el benchmark
                pass
            self.parar.wait(5)


def evaluar_modelo(modelo: str, repeticiones: int) -> dict:
    client = OllamaClient(model=modelo)
    descargar_de_vram(client.host)
    t0 = time.perf_counter()
    client.generate("Responde solo: OK", num_predict=5)
    carga_s = round(time.perf_counter() - t0, 1)
    system = SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema_context())
    latencia_sql = [llamada(client, system, "Pregunta: " + p) for p in PREGUNTAS]
    print(f"\n### {modelo} | carga+calentamiento {carga_s} s | desglose SQL: {json.dumps(latencia_sql, ensure_ascii=False)}", flush=True)

    corridas = []
    for r in range(1, repeticiones + 1):
        salida = SALIDA / f"fase4_{slug(modelo)}_r{r}.json"
        muestreador = Muestreador(client.host, modelo)
        muestreador.start()
        t = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(RAIZ / "eval" / "run_eval.py"), "--model", modelo, "--sin-plantillas", "--output", str(salida)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        duracion = round(time.perf_counter() - t, 1)
        muestreador.parar.set()
        muestreador.join()
        final = [l for l in proc.stdout.splitlines() if l.startswith("===")]
        print(f"  repetición {r}: exit {proc.returncode} en {duracion} s | " + " | ".join(final[-3:]), flush=True)
        datos = json.loads(salida.read_text(encoding="utf-8"))
        corridas.append({
            "archivo": str(salida.relative_to(RAIZ)),
            "duracion_s": duracion,
            "resumen": datos["resumen"],
            "aciertos": [r_["id"] for r_ in datos["resultados"] if r_["correcto"]],
            "memoria_pico": muestreador.pico,
        })
    return {"modelo": modelo, "carga_s": carga_s, "latencia_generacion_sql": latencia_sql, "corridas": corridas}


def tabla(resultados: list[dict]) -> str:
    lineas = [
        "| Modelo | Precisión por repetición | Media | ok / ejec / sem / seg / infra (suma) | Latencia media por pregunta | Gen. tok/s | VRAM pico | % GPU mín | RAM llama-server pico | Carga |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in resultados:
        precs = [c["resumen"]["correctas"] for c in r["corridas"]]
        n = r["corridas"][0]["resumen"]["total_preguntas"]
        suma = {k: sum(c["resumen"]["clasificacion_final"][k] for c in r["corridas"]) for k in ("ok", "ejecucion", "semantico", "seguridad", "infra")}
        lat = sum(c["resumen"]["latencia_media_s"] for c in r["corridas"]) / len(r["corridas"])
        toks = [x["tok_s_generacion"] for x in r["latencia_generacion_sql"]]
        mem = [c["memoria_pico"] for c in r["corridas"]]
        lineas.append(
            f"| {r['modelo']} | {', '.join(f'{p}/{n}' for p in precs)} | {100 * sum(precs) / (n * len(precs)):.0f} % | "
            f"{suma['ok']} / {suma['ejecucion']} / {suma['semantico']} / {suma['seguridad']} / {suma['infra']} | {lat:.1f} s | "
            f"{sum(toks) / len(toks):.1f} | {max(m['vram_gb'] for m in mem):.2f} GB | {min((m['pct_gpu_min'] or 0) for m in mem):.0f} % | "
            f"{max(m['ram_llama_server_mb'] for m in mem):.0f} MB | {r['carga_s']} s |"
        )
    return "\n".join(lineas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelos", nargs="+", required=True)
    ap.add_argument("--repeticiones", type=int, default=2)
    ap.add_argument("--resumen", default=str(SALIDA / "fase4_resumen.json"))
    args = ap.parse_args()
    resultados = []
    for m in args.modelos:
        resultados.append(evaluar_modelo(m, args.repeticiones))
        Path(args.resumen).write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + tabla(resultados))


if __name__ == "__main__":
    main()
