"""
Experimentos del juez iterativo (Fase 4; D-35).

Ejecuta los casos de eval/casos_juez.json con el ciclo de llm/juez.resolver_con_juez. Acepta
listas de esquemas y temperaturas: corre el producto de ambas (el esquema va por fuera para
aprovechar la caché del prefijo). Con temperatura > 0 repite con semillas fijas seed, seed+1, ...

Salida (en --salida, por defecto eval/baselines/juez/<etiqueta>/):
  - intentos.jsonl          una línea por intento;
  - casos/<config>__<caso>.json   un JSON por caso con todos sus intentos (evidencia: 1 json = 1 necesidad);
  - resumen.json            métricas por configuración (también se imprimen en consola).

Uso:
  python -m eval.run_juez --medir --modelo qwen2.5-coder:7b-instruct-q4_K_M --num-ctx 8192 12288 16384
  python -m eval.run_juez --max-iter 1 --esquema compacto completo --temperatura 0 0.3 0.7 --etiqueta barrido
  python -m eval.run_juez --max-iter 5 --feedback llm --esquema completo --temperatura 0 --etiqueta ciclo_llm

acierto@N con juez NO es comparable con PRUEBA_2: el juez usa la respuesta correcta y solo
existe para preguntas del catálogo.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from llm import juez
from llm.ollama_client import DEFAULT_MODEL, OllamaClient

RAIZ = Path(__file__).resolve().parent.parent
CASOS_PATH = RAIZ / "eval" / "casos_juez.json"
SALIDA_BASE = RAIZ / "eval" / "baselines" / "juez"


def cargar_casos(filtro: list[str] | None = None) -> list[dict]:
    casos = json.loads(CASOS_PATH.read_text(encoding="utf-8"))["casos"]
    if filtro:
        casos = [c for c in casos if any(c["id"].startswith(f) for f in filtro)]
    return casos


def _slug(texto: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in texto).strip("_")


# --- Medición: tokens de cada esquema y VRAM por num_ctx -------------------------------------

def medir(modelos: list[str], num_ctxs: list[int], keep_alive: str) -> dict:
    from llm.schema_context import get_schema_context
    from llm.text_to_sql import SQL_SYSTEM_PROMPT_TEMPLATE

    systems = {v: SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema_context(v)) for v in ("compacto", "completo")}
    out = {"fecha": datetime.now().isoformat(timespec="seconds"), "modelos": {}}
    for modelo in modelos:
        res = {"tokens_system": {}, "caracteres_system": {k: len(s) for k, s in systems.items()}, "num_ctx": {}}
        for num_ctx in num_ctxs:
            c = OllamaClient(model=modelo, num_ctx=num_ctx)
            t0 = time.perf_counter()
            r = c.generate_detallado("Di OK.", num_predict=2, temperature=0, keep_alive=keep_alive)
            carga = time.perf_counter() - t0
            ps = [m for m in c.procesos_cargados() if m.get("name") == modelo or m.get("model") == modelo]
            fila = {"segundos_llamada": round(carga, 2), "load_duration_s": round((r.get("load_duration") or 0) / 1e9, 2)}
            if ps:
                fila.update({"size": ps[0]["size"], "size_vram": ps[0]["size_vram"],
                             "todo_en_vram": ps[0]["size"] == ps[0]["size_vram"],
                             "context_length": ps[0].get("context_length")})
            res["num_ctx"][str(num_ctx)] = fila
            print(f"[{modelo}] num_ctx={num_ctx}: {fila}", flush=True)
        c = OllamaClient(model=modelo, num_ctx=min(num_ctxs))
        for variante, s in systems.items():
            res["tokens_system"][variante] = c.contar_tokens(s, keep_alive=keep_alive)
            print(f"[{modelo}] system prompt '{variante}': {len(s):,} caracteres, "
                  f"{res['tokens_system'][variante]:,} tokens (prompt_eval_count)", flush=True)
        out["modelos"][modelo] = res
    return out


# --- Corridas ---------------------------------------------------------------------------------

def resumir(registros: list[dict]) -> dict:
    n = len(registros)
    aciertos_1 = sum(r["acierto_1"] for r in registros)
    aciertos_n = sum(r["acierto_final"] for r in registros)
    hasta = [r["intentos_usados"] for r in registros if r["acierto_final"]]
    intentos = [i for r in registros for i in r["intentos"]]
    lat = [i["segundos_generacion"] + i["ejecucion"]["segundos"]
           + i.get("retroalimentacion", {}).get("segundos", 0.0) for i in intentos]
    sint = [r["sintesis"] for r in registros if r.get("sintesis")]
    return {
        "corridas_caso": n,
        "acierto_1": aciertos_1, "acierto_N": aciertos_n,
        "pct_acierto_1": round(100 * aciertos_1 / n, 1) if n else None,
        "pct_acierto_N": round(100 * aciertos_n / n, 1) if n else None,
        "intentos_promedio_hasta_acertar": round(statistics.mean(hasta), 2) if hasta else None,
        "intentos_totales": len(intentos),
        "latencia_media_por_intento_s": round(statistics.mean(lat), 2) if lat else None,
        "latencia_mediana_por_intento_s": round(statistics.median(lat), 2) if lat else None,
        "fugas_bloqueadas": sum(r["fugas_bloqueadas"] for r in registros),
        "pistas_llm_sustituidas_por_plantilla": sum(
            1 for i in intentos if i.get("retroalimentacion", {}).get("fallback_plantilla")),
        "prompt_eval_count_max": max((i["tokens"]["prompt_eval_count"] or 0) for i in intentos) if intentos else None,
        "tokens_estimados_max": max((i["tokens"]["estimados"] or 0) for i in intentos) if intentos else None,
        "load_duration_total_s": round(sum(i["load_duration_s"] + i.get("retroalimentacion", {}).get("load_duration_s", 0.0)
                                           for i in intentos), 2),
        "reintentos": sum(1 for i in intentos if i["intento"] > 1),
        # SQL normalizado igual a uno ya probado en el mismo caso (misma métrica para ronda 1 y 2).
        "reintentos_sql_repetido": sum(
            1 for r in registros for k, i in enumerate(r["intentos"])
            if k > 0 and juez.normalizar_sql(i.get("sql") or "") in
            {juez.normalizar_sql(p.get("sql") or "") for p in r["intentos"][:k]}),
        "remuestreos": sum(i.get("remuestreos", 0) for i in intentos),
        "etapas": dict(sorted(Counter(
            "correcto" if i["veredicto"]["correcto"] else (i["ejecucion"]["etapa"] or "resultado_incorrecto")
            for i in intentos).items())),
        "sintesis_texto_confiable": sum(s["texto_confiable"] for s in sint) if sint else None,
        "sintesis_texto_confiable_con_umbrales": sum(s.get("texto_confiable_con_umbrales", False) for s in sint) if sint else None,
        "sintesis_cifras_clave": f"{sum(s['cifras_clave_presentes'] for s in sint)}/{sum(s['cifras_clave'] for s in sint)}" if sint else None,
        "por_caso": {cid: [r["acierto_final"] for r in registros if r["caso"] == cid]
                     for cid in dict.fromkeys(r["caso"] for r in registros)},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default=DEFAULT_MODEL)
    ap.add_argument("--juez-modelo", default=None, help="por defecto, el mismo modelo candidato")
    ap.add_argument("--max-iter", type=int, default=5)
    ap.add_argument("--temperatura", type=float, nargs="+", default=[0.0])
    ap.add_argument("--num-ctx", type=int, nargs="+", default=[8192])
    ap.add_argument("--esquema", nargs="+", default=["compacto"], choices=["compacto", "completo"])
    ap.add_argument("--feedback", default="plantilla", choices=["plantilla", "llm"])
    ap.add_argument("--repeticiones", type=int, default=3, help="repeticiones (semillas) para temperatura > 0")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--casos", nargs="*", default=None, help="prefijos de id de caso (por defecto, todos)")
    ap.add_argument("--sin-sintesis", action="store_true")
    ap.add_argument("--keep-alive", default="30m")
    ap.add_argument("--etiqueta", default=None)
    ap.add_argument("--salida", default=None)
    ap.add_argument("--medir", action="store_true", help="solo mide tokens por esquema y VRAM por num_ctx")
    # Ronda 2 (D-37): todo apagado por defecto.
    ap.add_argument("--reintento-temp", type=float, nargs="?", const=0.5, default=None,
                    help="anti-repetición: temperatura de los reintentos (sin valor: 0.5) y remuestreo si el SQL se repite")
    ap.add_argument("--reparar-esquema", action="store_true", help="pista con columnas reales y ruta por tablas base")
    ap.add_argument("--modo-edicion", action="store_true", help="el reintento pide corregir el SQL anterior")
    ap.add_argument("--pistas-v2", action="store_true", help="diagnóstico determinista primero, sin el nivel 1")
    a = ap.parse_args()

    etiqueta = a.etiqueta or datetime.now().strftime("%Y%m%d_%H%M%S")
    salida = Path(a.salida) if a.salida else SALIDA_BASE / etiqueta
    salida.mkdir(parents=True, exist_ok=True)

    if a.medir:
        modelos = [a.modelo] + ([a.juez_modelo] if a.juez_modelo else [])
        datos = medir(modelos, a.num_ctx, a.keep_alive)
        (salida / "medicion.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Escrito {salida / 'medicion.json'}")
        return 0

    num_ctx = a.num_ctx[0]
    casos = cargar_casos(a.casos)
    candidato = OllamaClient(model=a.modelo, num_ctx=num_ctx)
    juez_client = OllamaClient(model=a.juez_modelo, num_ctx=num_ctx) if a.juez_modelo else candidato
    (salida / "casos").mkdir(exist_ok=True)
    jsonl = (salida / "intentos.jsonl").open("a", encoding="utf-8")
    resumen = {"etiqueta": etiqueta, "inicio": datetime.now().isoformat(timespec="seconds"),
               "argumentos": vars(a), "configuraciones": {}}
    t_total = time.perf_counter()
    try:
        for esquema in a.esquema:
            for temp in a.temperatura:
                semillas = [a.seed] if temp == 0 else [a.seed + i for i in range(a.repeticiones)]
                ronda2 = "".join([f"-rt{a.reintento_temp:g}" if a.reintento_temp is not None else "",
                                  "-rep" if a.reparar_esquema else "", "-edi" if a.modo_edicion else "",
                                  "-pv2" if a.pistas_v2 else ""])
                config = (f"{_slug(a.modelo)}__{esquema}__T{temp:g}__ctx{num_ctx}"
                          f"__{a.feedback if a.max_iter > 1 else 'sinjuez'}{ronda2}__it{a.max_iter}")
                registros = []
                for seed in semillas:
                    for caso in casos:
                        t0 = time.perf_counter()
                        reg = juez.resolver_con_juez(
                            caso, candidato, esquema=esquema, max_iter=a.max_iter, temperatura=temp, seed=seed,
                            feedback=a.feedback, juez_client=juez_client, keep_alive=a.keep_alive,
                            sintetizar=not a.sin_sintesis, reintento_temp=a.reintento_temp,
                            reparar_esquema=a.reparar_esquema, modo_edicion=a.modo_edicion, pistas_v2=a.pistas_v2,
                            al_intento=lambda r: (jsonl.write(json.dumps(r, ensure_ascii=False, default=str) + "\n"),
                                                  jsonl.flush()),
                        )
                        reg["segundos_caso"] = round(time.perf_counter() - t0, 2)
                        registros.append(reg)
                        (salida / "casos" / f"{config}__s{seed}__{caso['id']}.json").write_text(
                            json.dumps(reg, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                        print(f"{config} s{seed} {caso['id']:<36} @1={'✔' if reg['acierto_1'] else '✘'} "
                              f"@N={'✔' if reg['acierto_final'] else '✘'} intentos={reg['intentos_usados']} "
                              f"fugas={reg['fugas_bloqueadas']} {reg['segundos_caso']:.1f}s", flush=True)
                resumen["configuraciones"][config] = {"modelo": a.modelo, "esquema": esquema, "temperatura": temp,
                                                      "semillas": semillas, **resumir(registros)}
    finally:
        jsonl.close()
        resumen["segundos_totales"] = round(time.perf_counter() - t_total, 1)
        (salida / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Resumen ===")
    for config, r in resumen["configuraciones"].items():
        print(f"{config}: acierto@1 {r['acierto_1']}/{r['corridas_caso']} | acierto@N {r['acierto_N']}/{r['corridas_caso']} "
              f"| intentos hasta acertar {r['intentos_promedio_hasta_acertar']} | latencia/intento media "
              f"{r['latencia_media_por_intento_s']} s | fugas bloqueadas {r['fugas_bloqueadas']} "
              f"| prompt_eval_count máx {r['prompt_eval_count_max']}")
    print(f"Tiempo total: {resumen['segundos_totales']} s · salida: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
