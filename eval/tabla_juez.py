"""
Tablas en Markdown para docs/INFORME_JUEZ.md. Recalcula las métricas con eval.run_juez.resumir a
partir de los JSON por caso (casos/*.json), agrupando por configuración: así se pueden unir
corridas partidas (p. ej. la de qwen-llm, interrumpida por un reinicio, y su n08 por separado).

Uso: python -m eval.tabla_juez eval/baselines/juez/barrido eval/baselines/juez/ciclo_* ...
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from eval.run_juez import resumir


def cargar(directorios: list[str]) -> dict[str, list[dict]]:
    grupos: dict[str, list[dict]] = defaultdict(list)
    for d in directorios:
        for f in sorted(Path(d).glob("casos/*.json")):
            config = re.split(r"__s\d+__", f.name)[0]
            grupos[config].append(json.loads(f.read_text(encoding="utf-8")))
    return grupos


def ronda2(directorios: list[str]) -> None:
    """Tabla compacta de la ronda 2 (D-37): repetición, remuestreos y tipo de resultado por intento."""
    print("| configuración | acierto@1 | acierto@N | reintentos | con SQL repetido | remuestreos | "
          "tipo de resultado por intento | latencia/intento (s) | fugas bloqueadas |")
    print("|---|---|---|---|---|---|---|---|---|")
    for config, regs in cargar(directorios).items():
        r = resumir(regs)
        etapas = ", ".join(f"{k} {v}" for k, v in r["etapas"].items())
        print(f"| {config.split('__')[4]} | {r['acierto_1']}/{r['corridas_caso']} | {r['acierto_N']}/{r['corridas_caso']} | "
              f"{r['reintentos']} | {r['reintentos_sql_repetido']} | {r['remuestreos']} | {etapas} | "
              f"{r['latencia_media_por_intento_s']} | {r['fugas_bloqueadas']} |")


def main(directorios: list[str]) -> None:
    print("| modelo | esquema | T | retroalimentación | semillas | acierto@1 | acierto@N | intentos hasta acertar | "
          "latencia/intento (s) | fugas bloqueadas | pistas LLM → plantilla | prompt_eval máx | por caso (@1 → @N) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for config, regs in cargar(directorios).items():
        r = resumir(regs)
        partes = config.split("__")
        semillas = sorted({x["seed"] for x in regs})
        por_caso = " ".join(
            f"{cid.split('_')[0]}:{sum(x['acierto_1'] for x in regs if x['caso'] == cid)}→"
            f"{sum(x['acierto_final'] for x in regs if x['caso'] == cid)}/{len(v)}"
            for cid, v in r["por_caso"].items())
        print(f"| {regs[0]['modelo'].split(':')[0]} | {regs[0]['esquema']} | {regs[0]['temperatura']:g} | {partes[4]} | "
              f"{len(semillas)} | {r['acierto_1']}/{r['corridas_caso']} | {r['acierto_N']}/{r['corridas_caso']} | "
              f"{r['intentos_promedio_hasta_acertar']} | {r['latencia_media_por_intento_s']} | {r['fugas_bloqueadas']} | "
              f"{r['pistas_llm_sustituidas_por_plantilla']} | {r['prompt_eval_count_max']} | {por_caso} |")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--ronda2"]:
        ronda2(sys.argv[2:])
    else:
        main(sys.argv[1:])
