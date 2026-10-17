"""
Tablas en Markdown a partir de los resumen.json de eval/run_juez.py (para docs/INFORME_JUEZ.md).

Uso: python -m eval.tabla_juez eval/baselines/juez/barrido [eval/baselines/juez/ciclo_...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def filas(directorio: Path) -> list[str]:
    r = json.loads((directorio / "resumen.json").read_text(encoding="utf-8"))
    salida = []
    for config, c in r["configuraciones"].items():
        partes = config.split("__")
        por_caso = " ".join(f"{k.split('_')[0]}:{sum(v)}/{len(v)}" for k, v in c["por_caso"].items())
        salida.append(
            f"| {partes[0][:14]} | {c['esquema']} | {c['temperatura']:g} | {partes[4]} | {len(c['semillas'])} | "
            f"{c['acierto_1']}/{c['corridas_caso']} | {c['acierto_N']}/{c['corridas_caso']} | "
            f"{c['intentos_promedio_hasta_acertar']} | {c['latencia_media_por_intento_s']} | {c['fugas_bloqueadas']} | "
            f"{c['prompt_eval_count_max']} | {por_caso} |"
        )
    return salida


if __name__ == "__main__":
    print("| modelo | esquema | T | juez | semillas | acierto@1 | acierto@N | intentos hasta acertar | "
          "latencia/intento (s) | fugas bloqueadas | prompt_eval máx | por caso (@N) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for d in sys.argv[1:]:
        print("\n".join(filas(Path(d))))
