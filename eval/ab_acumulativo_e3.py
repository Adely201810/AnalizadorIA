"""
A/B acumulativo de la Etapa 3 (experimentos de contexto E1-E7), solo DESARROLLO.

Para cada experimento, en orden: (1) mide sobre la MEJOR configuración vigente cuántos
fallos de DESARROLLO tienen la causa que el experimento ataca (heurística documentada en
CAUSAS); (2) corre 3 repeticiones con el interruptor encendido ENCIMA de lo conservado;
(3) aplica la regla D-23: se conserva si media(nueva) >= media(actual) + 1 y
mínimo(nueva) >= media(actual). E7 se prueba con k=3 y k=5 contra la misma configuración;
si ambas pasan, se queda la de mayor media (empate: k=3, más barata).

Uso: python -m eval.ab_acumulativo_e3   ->  eval/baselines/etapa3/acumulativo.json
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "eval" / "baselines" / "etapa3"

EXPERIMENTOS = [
    ("E1_glosario", {"TEXT2SQL_GLOSARIO": "1"}),
    ("E2_esquema_por_pregunta", {"TEXT2SQL_ESQUEMA_POR_PREGUNTA": "1"}),
    ("E3_desc_columnas", {"TEXT2SQL_DESC_COLUMNAS": "1"}),
    ("E4_vistas_negocio", {"TEXT2SQL_VISTAS_NEGOCIO": "1"}),
    ("E5_fewshot_dinamico", {"TEXT2SQL_FEWSHOT_DINAMICO": "1"}),
    ("E6_plan", {"TEXT2SQL_PLAN": "1"}),
    # E7 se trata aparte (dos variantes contra la misma configuración)
]
E7 = [("E7_autoconsistencia_k3", {"TEXT2SQL_AUTOCONSISTENCIA": "3"}),
      ("E7_autoconsistencia_k5", {"TEXT2SQL_AUTOCONSISTENCIA": "5"})]

DETALLE_ESQUEMA = re.compile(r"no such column|no such table|no existe|no tiene la columna", re.I)
DETALLE = ("E1: fallos semánticos en preguntas que disparan alguna entrada del glosario; "
           "E2: fallos con algún intento que usó una tabla/columna inexistente o mal ubicada; "
           "E3: fallos cuyo SQL final usa alguna columna ambigua (DESCRIPCIONES_COLUMNAS); "
           "E4: fallos cuyo SQL final une 2+ tablas de detalle (order_items/order_payments/order_reviews) o tiene subconsulta/CTE; "
           "E5: todos los fallos (el few-shot no ataca una causa concreta); "
           "E6: fallos semánticos (el SQL corre pero responde otra cosa); "
           "E7: fallos en preguntas cuyo SQL final cambia entre repeticiones.")


def _fallos(archivos: list[Path]) -> list[tuple[int, dict]]:
    out = []
    for k, f in enumerate(archivos):
        for r in json.loads(f.read_text(encoding="utf-8"))["resultados"]:
            if not r["correcto"]:
                out.append((k, r))
    return out


def causa_objetivo(exp: str, archivos: list[Path]) -> int:
    sys.path.insert(0, str(RAIZ))
    from llm import contexto_e3 as ctx
    from llm import schema_context as sc
    fallos = _fallos(archivos)
    if exp.startswith("E1"):
        return sum(r["clasificacion"] == "semantico" and bool(ctx.entradas_glosario(r["pregunta"])) for _, r in fallos)
    if exp.startswith("E2"):
        return sum(any(DETALLE_ESQUEMA.search(i.get("detalle") or "") for i in r.get("intentos_detalle", [])) for _, r in fallos)
    if exp.startswith("E3"):
        cols = {c for _, c in sc.DESCRIPCIONES_COLUMNAS}
        return sum(any(re.search(rf"\b{c}\b", (r.get("sql_generado") or "").lower()) for c in cols) for _, r in fallos)
    if exp.startswith("E4"):
        def multi(s):
            s = (s or "").lower()
            return sum(t in s for t in ("order_items", "order_payments", "order_reviews")) >= 2 or "with " in s or s.count("select") > 1
        return sum(multi(r.get("sql_generado")) for _, r in fallos)
    if exp.startswith("E5"):
        return len(fallos)
    if exp.startswith("E6"):
        return sum(r["clasificacion"] == "semantico" for _, r in fallos)
    if exp.startswith("E7"):
        sqls: dict[str, set] = {}
        for f in archivos:
            for r in json.loads(f.read_text(encoding="utf-8"))["resultados"]:
                sqls.setdefault(r["id"], set()).add(" ".join((r.get("sql_generado") or "").split()))
        inestables = {q for q, s in sqls.items() if len(s) > 1}
        return sum(r["id"] in inestables for _, r in fallos)
    raise ValueError(exp)


def conservar(nueva: dict, actual: dict) -> bool:
    return nueva["media"] >= actual["media"] + 1 and nueva["minimo"] >= actual["media"]


def correr(nombre: str, env: dict) -> dict:
    cmd = [sys.executable, "-m", "eval.ab", "--nombre", nombre, "--carpeta", "etapa3", "--repeticiones", "3",
           "--env", *[f"{k}={v}" for k, v in env.items()]]
    print(f"### {nombre}: {env}", flush=True)
    subprocess.run(cmd, cwd=RAIZ, check=True)
    return json.loads((SALIDA / f"{nombre}_resumen.json").read_text(encoding="utf-8"))


def _fila(nombre, env, res, actual_nombre, actual, objetivo, decision):
    return {"paso": nombre, "env": env, "aciertos": res["aciertos"], "media": res["media"], "minimo": res["minimo"],
            "maximo": res["maximo"], "wilson95_pct": res["wilson95_pct"], "wilson95_por_pregunta": res["wilson95_pct_por_pregunta"],
            "latencia_media_s": res["latencia_media_s"], "prompt_sql_caracteres_medio": res["prompt_sql_caracteres_medio"],
            "comparado_con": actual_nombre, "media_anterior": actual["media"],
            "fallos_con_la_causa_objetivo_antes": objetivo, "decision": decision}


def main():
    nombre, env = "base", {}
    actual = json.loads((SALIDA / "base_resumen.json").read_text(encoding="utf-8"))
    registro = [{"paso": "base", "env": {}, "aciertos": actual["aciertos"], "media": actual["media"],
                 "latencia_media_s": actual["latencia_media_s"], "prompt_sql_caracteres_medio": actual["prompt_sql_caracteres_medio"],
                 "decision": "punto de partida"}]

    def guardar():
        (SALIDA / "acumulativo.json").write_text(json.dumps(
            {"regla": "D-23", "causas_objetivo": DETALLE, "final": {"nombre": nombre, "env": env}, "registro": registro},
            ensure_ascii=False, indent=2), encoding="utf-8")

    for exp, extra in EXPERIMENTOS:
        objetivo = causa_objetivo(exp, [SALIDA / f"{nombre}_r{k}.json" for k in (1, 2, 3)])
        print(f"### {exp}: fallos con la causa objetivo en '{nombre}': {objetivo}", flush=True)
        prueba_env = {**env, **extra}
        res = correr(exp, prueba_env)
        ok = conservar(res, actual)
        registro.append(_fila(exp, prueba_env, res, nombre, actual, objetivo, "CONSERVADO" if ok else "REVERTIDO"))
        print(f"### {exp}: {res['aciertos']} media {res['media']} vs {actual['media']} -> {'CONSERVADO' if ok else 'REVERTIDO'}", flush=True)
        if ok:
            nombre, env, actual = exp, prueba_env, res
        guardar()

    objetivo = causa_objetivo("E7", [SALIDA / f"{nombre}_r{k}.json" for k in (1, 2, 3)])
    print(f"### E7: fallos con la causa objetivo en '{nombre}': {objetivo}", flush=True)
    candidatos = []
    base_nombre, base_env, base_actual = nombre, env, actual
    for exp, extra in E7:
        prueba_env = {**base_env, **extra}
        res = correr(exp, prueba_env)
        ok = conservar(res, base_actual)
        registro.append(_fila(exp, prueba_env, res, base_nombre, base_actual, objetivo, "pasa D-23" if ok else "REVERTIDO"))
        if ok:
            candidatos.append((res["media"], exp, prueba_env, res))
        guardar()
    if candidatos:
        mejor = max(candidatos, key=lambda c: (c[0], c[1] == "E7_autoconsistencia_k3"))
        _, nombre, env, actual = mejor
        for fila in registro:
            if fila["paso"] == nombre:
                fila["decision"] = "CONSERVADO"
    guardar()
    print("### FINAL:", nombre, env, flush=True)


if __name__ == "__main__":
    main()
