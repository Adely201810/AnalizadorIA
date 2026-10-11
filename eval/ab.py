"""
A/B con repeticiones sobre DESARROLLO (Etapa 2, Paso 3).

Corre `eval/run_eval.py` K veces con una configuración (variables de entorno +
argumentos) y resume: aciertos por repetición, media, mínimo, máximo, intervalo
de Wilson al 95 % sobre el total de respuestas, aciertos por pregunta (cuántas
de las K repeticiones acertó cada una) y desglose de fallos.

Uso:
    python -m eval.ab --nombre base --repeticiones 3
    python -m eval.ab --nombre sin_clasificador --env TEXT2SQL_CLASIFICADOR=0
    python -m eval.ab --nombre qwen --modelo qwen2.5-coder:7b-instruct-q4_K_M --env TEXT2SQL_CLASIFICADOR=0

Por seguridad este script NO acepta --conjunto prueba_2 ni todos (PRUEBA_2 se evalúa una sola vez al final de la etapa 3).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "eval" / "baselines" / "etapa2"  # --carpeta la cambia (Etapa 3: etapa3)


def wilson(aciertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = aciertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(100 * max(0.0, centro - margen), 1), round(100 * min(1.0, centro + margen), 1))


def resumir(nombre: str, archivos: list[Path]) -> dict:
    corridas = [json.loads(f.read_text(encoding="utf-8")) for f in archivos]
    aciertos = [c["resumen"]["correctas"] for c in corridas]
    n_preg = corridas[0]["resumen"]["total_preguntas"]
    por_pregunta: dict[str, int] = {}
    clasif = {}
    descompuestas = 0
    for c in corridas:
        for r in c["resultados"]:
            por_pregunta[r["id"]] = por_pregunta.get(r["id"], 0) + int(r["correcto"])
            clasif[r["clasificacion"]] = clasif.get(r["clasificacion"], 0) + 1
            descompuestas += int(r["origen"] is None and not r["error_pipeline"])
    total = sum(aciertos)
    return {
        "nombre": nombre, "modelo": corridas[0]["modelo"], "configuracion": corridas[0]["configuracion"],
        "archivos": [str(f.relative_to(RAIZ)) for f in archivos], "preguntas": n_preg, "aciertos": aciertos,
        "media": round(statistics.mean(aciertos), 2), "minimo": min(aciertos), "maximo": max(aciertos),
        "pct_media": round(100 * total / (n_preg * len(aciertos)), 1), "wilson95_pct": wilson(total, n_preg * len(aciertos)),
        "aciertos_por_pregunta": dict(sorted(por_pregunta.items())), "clasificacion_total": clasif,
        "respuestas_descompuestas": descompuestas,
        "latencia_media_s": round(statistics.mean(c["resumen"]["latencia_media_s"] for c in corridas), 2),
        # Etapa 3: tamaño medio del PRIMER prompt al generador de SQL (system + pregunta), en caracteres.
        "prompt_sql_caracteres_medio": _prompt_medio(corridas),
        "wilson95_pct_por_pregunta": _wilson_por_pregunta(por_pregunta, len(aciertos)),
    }


def _prompt_medio(corridas: list[dict]) -> float | None:
    t = [r["prompt_sql_caracteres"][0] for c in corridas for r in c["resultados"] if r.get("prompt_sql_caracteres")]
    return round(statistics.mean(t)) if t else None


def _wilson_por_pregunta(por_pregunta: dict[str, int], k: int) -> dict:
    """Intervalo sobre PREGUNTAS (no sobre respuestas): una pregunta cuenta como acertada
    si acierta en la mayoría de las k repeticiones (Etapa 2: las repeticiones no son independientes)."""
    n = len(por_pregunta)
    mayoria = sum(v * 2 > k for v in por_pregunta.values())
    return {"criterio": f"acierta en > {k // 2} de {k}", "aciertos": mayoria, "preguntas": n, "wilson95_pct": wilson(mayoria, n)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--modelo", default=None)
    ap.add_argument("--env", nargs="*", default=[], help="VAR=valor para el pipeline")
    ap.add_argument("--carpeta", default="etapa2", help="subcarpeta de eval/baselines/ (Etapa 3: etapa3)")
    ap.add_argument("--extra", nargs=argparse.REMAINDER, default=[], help="argumentos extra para run_eval.py")
    args = ap.parse_args()
    global SALIDA
    SALIDA = RAIZ / "eval" / "baselines" / args.carpeta
    if any(c in args.extra for c in ("prueba", "prueba_2", "todos")):
        sys.exit("eval.ab solo evalúa DESARROLLO; PRUEBA_2 se evalúa una sola vez al final de la etapa 3.")
    SALIDA.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    env.update(dict(kv.split("=", 1) for kv in args.env))
    archivos = []
    for k in range(1, args.repeticiones + 1):
        salida = SALIDA / f"{args.nombre}_r{k}.json"
        cmd = [sys.executable, str(RAIZ / "eval" / "run_eval.py"), "--sin-plantillas", "--conjunto", "desarrollo",
               "--output", str(salida), *(["--model", args.modelo] if args.modelo else []), *args.extra]
        log = RAIZ / "logs" / f"e2_{args.nombre}_r{k}.log"
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(cmd, cwd=RAIZ, env=env, stdout=fh, stderr=subprocess.STDOUT)
        final = [l for l in log.read_text(encoding="utf-8").splitlines() if l.startswith("=== RESULTADO")]
        print(f"[{args.nombre} r{k}] exit {proc.returncode} | {final[-1][:160] if final else '(sin resultado)'}", flush=True)
        archivos.append(salida)
    resumen = resumir(args.nombre, archivos)
    (SALIDA / f"{args.nombre}_resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: resumen[k] for k in ("nombre", "modelo", "aciertos", "media", "minimo", "maximo", "pct_media",
                                               "wilson95_pct", "wilson95_pct_por_pregunta", "respuestas_descompuestas",
                                               "clasificacion_total", "latencia_media_s", "prompt_sql_caracteres_medio")},
                     ensure_ascii=False))
    print("aciertos por pregunta (de", args.repeticiones, "):", json.dumps(resumen["aciertos_por_pregunta"]))


if __name__ == "__main__":
    main()
