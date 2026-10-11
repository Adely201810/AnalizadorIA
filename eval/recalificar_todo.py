"""
Recalifica OFFLINE (sin llamar al modelo) todas las corridas de eval/baselines/
con el árbitro actual: reejecuta en solo lectura el SQL final que generó el
modelo en cada pregunta y lo compara con la referencia (eval/recalificar.py).

Limitación: en las corridas con cadena (--cadena), con la tolerancia nueva un
intento antes aceptado podría haberse rechazado y la cadena habría seguido;
eso no se puede simular sin el modelo. Aquí se recalifica la respuesta FINAL.

Uso: python -m eval.recalificar_todo [--salida eval/baselines/recalificacion_tol0006.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.recalificar import recalificar

BASELINES = Path(__file__).resolve().parent / "baselines"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default=str(BASELINES / "recalificacion_tol0006.json"))
    args = ap.parse_args()
    resumen = []
    for f in sorted(BASELINES.glob("*.json")):
        if f.name.startswith(("fase4_resumen", "recalificacion")):
            continue
        filas = recalificar(f)
        antes = sum(bool(x["antes"]) for x in filas)
        ahora = sum(bool(x["ahora"]) for x in filas)
        cambios = [x for x in filas if bool(x["antes"]) != bool(x["ahora"])]
        print(f"{f.name:48s} antes {antes}/{len(filas)}  ahora {ahora}/{len(filas)}  cambios: "
              + (", ".join(f"{x['id']} {'✅→❌' if x['antes'] else '❌→✅'} ({x['motivo'][:60]})" for x in cambios) or "ninguno"),
              flush=True)
        resumen.append({"archivo": f.name, "antes": antes, "ahora": ahora, "total": len(filas), "cambios": cambios})
    Path(args.salida).write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()
