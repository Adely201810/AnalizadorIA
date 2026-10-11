"""
A/B acumulativo del Paso 3 (Etapa 2) con la regla D-23.

Parte de una configuración ya medida (por defecto `a_sin_clasificador`) y prueba
cada mejora ENCIMA de la última conservada. Se conserva si
    media(nueva) >= media(actual) + 1   y   mínimo(nueva) >= media(actual).
Solo DESARROLLO (usa eval/ab.py, que rechaza PRUEBA).

Uso:
    python -m eval.ab_acumulativo
Escribe el registro de decisiones en eval/baselines/etapa2/acumulativo.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "eval" / "baselines" / "etapa2"

INICIO = ("a_sin_clasificador", {"TEXT2SQL_CLASIFICADOR": "0"})
MEJORAS = [
    ("b_vista_validos", {"TEXT2SQL_VISTA_VALIDOS": "1"}),
    ("c_regla_denominador", {"TEXT2SQL_REGLA_DENOMINADOR": "1"}),
    ("d1_vistas_doc", {"TEXT2SQL_VISTAS_DOC": "1"}),
    ("d2_vistas_ocultas", {"TEXT2SQL_VISTAS_OCULTAS": "vw_ingresos_por_vendedor,vw_ingresos_por_categoria,vw_clientes_recurrentes"}),
    ("d3_regla_multiplicidad", {"TEXT2SQL_REGLA_MULTIPLICIDAD": "1"}),
]


def conservar(nueva: dict, actual: dict) -> bool:
    return nueva["media"] >= actual["media"] + 1 and nueva["minimo"] >= actual["media"]


def main():
    nombre, env = INICIO
    actual = json.loads((SALIDA / f"{nombre}_resumen.json").read_text(encoding="utf-8"))
    registro = [{"paso": nombre, "env": env, "aciertos": actual["aciertos"], "media": actual["media"], "decision": "punto de partida"}]
    for mejora, extra in MEJORAS:
        prueba_env = {**env, **extra}
        cmd = [sys.executable, "-m", "eval.ab", "--nombre", mejora, "--repeticiones", "3",
               "--env", *[f"{k}={v}" for k, v in prueba_env.items()]]
        print(f"### {mejora}: {prueba_env}", flush=True)
        subprocess.run(cmd, cwd=RAIZ, check=True)
        nueva = json.loads((SALIDA / f"{mejora}_resumen.json").read_text(encoding="utf-8"))
        ok = conservar(nueva, actual)
        registro.append({"paso": mejora, "env": prueba_env, "aciertos": nueva["aciertos"], "media": nueva["media"],
                         "minimo": nueva["minimo"], "wilson95_pct": nueva["wilson95_pct"],
                         "comparado_con": nombre, "media_anterior": actual["media"],
                         "decision": "CONSERVADA" if ok else "REVERTIDA"})
        print(f"### {mejora}: {nueva['aciertos']} media {nueva['media']} vs {actual['media']} -> "
              f"{'CONSERVADA' if ok else 'REVERTIDA'}", flush=True)
        if ok:
            nombre, env, actual = mejora, prueba_env, nueva
        (SALIDA / "acumulativo.json").write_text(json.dumps({"final": {"nombre": nombre, "env": env}, "registro": registro},
                                                             ensure_ascii=False, indent=2), encoding="utf-8")
    print("### FINAL:", nombre, env, flush=True)


if __name__ == "__main__":
    main()
