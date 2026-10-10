"""
Corre el oráculo (eval/ground_truth_olist.json) contra el pipeline Text-to-SQL
real (llm/text_to_sql.py + Ollama) y mide la precisión con un árbitro
DETERMINISTA (eval/comparador.py).

Para cada pregunta:
  1. Se ejecuta el pipeline completo (genera SQL, valida, ejecuta, sintetiza).
  2. Se ejecuta el SQL de referencia del oráculo sobre la misma base (solo lectura).
  3. Se comparan las FILAS del modelo contra las de la referencia: mismo número
     de filas, cada columna marcada en `tipos_columnas` debe coincidir con
     alguna columna del modelo dentro de la tolerancia de su tipo, y en orden
     si `orden_importa`. El texto en lenguaje natural NO decide el veredicto.

Se registra por pregunta: origen del SQL (llm / plantilla / fallback_vista),
intentos, latencia, motivo del veredicto y si la síntesis está respaldada por
los datos (métrica secundaria). El JSON de salida se reescribe tras CADA
pregunta, así que una corrida cortada se puede retomar con --reanudar.

Uso:
    python eval/run_eval.py                                   # oráculo Olist, todo activado
    python eval/run_eval.py --sin-plantillas                  # solo LLM (evaluación del modelo)
    python eval/run_eval.py --model qwen2.5-coder:7b --output eval/baselines/x.json
    python eval/run_eval.py --output x.json --reanudar        # retoma una corrida cortada
    python eval/run_eval.py --limit 3                         # solo las primeras N
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from eval.comparador import comparar
from llm.ollama_client import OllamaClient
from llm.text_to_sql import (
    MENSAJE_PROBLEMA_TRAS_REINTENTO,
    MENSAJE_RESUMEN_NO_CONFIABLE,
    MENSAJE_SIN_RESULTADOS,
    Text2SQLResult,
    _respuesta_respaldada_por_datos,
    answer_question,
    execute_readonly,
)

DEFAULT_GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth_olist.json"
MENSAJES_FIJOS = {MENSAJE_PROBLEMA_TRAS_REINTENTO, MENSAJE_RESUMEN_NO_CONFIABLE, MENSAJE_SIN_RESULTADOS}
MAX_FILAS_GUARDADAS = 10


def calificar(item: dict, resultado: Text2SQLResult, filas_referencia: list[tuple]) -> tuple[bool, str]:
    """Veredicto del árbitro determinista: (correcto, motivo)."""
    if resultado.error:
        return False, f"pipeline: {resultado.error}"
    if resultado.sub_consultas:
        return False, "pipeline: la pregunta se descompuso en sub-consultas (no hay un resultado único que comparar)"
    v = comparar(resultado.filas, filas_referencia, item["tipos_columnas"], item.get("orden_importa", False))
    return v.correcto, v.motivo


def texto_respaldado(resultado: Text2SQLResult) -> bool:
    """Métrica secundaria: la síntesis cita solo cifras presentes en las filas
    y no es un mensaje fijo de error/descartado."""
    if not resultado.respuesta or resultado.respuesta in MENSAJES_FIJOS:
        return False
    return _respuesta_respaldada_por_datos(resultado.respuesta, resultado.filas)


def recursos_ollama(client: OllamaClient) -> dict | None:
    """`ollama ps` vía API: tamaño total y en VRAM del modelo cargado."""
    try:
        modelos = requests.get(f"{client.host}/api/ps", timeout=5).json().get("models", [])
    except requests.RequestException:
        return None
    for m in modelos:
        if m.get("name") == client.model or m.get("model") == client.model:
            size, vram = m.get("size", 0), m.get("size_vram", 0)
            return {
                "size_bytes": size,
                "size_vram_bytes": vram,
                "pct_gpu": round(100 * vram / size, 1) if size else None,
                "context_length": m.get("context_length"),
            }
    return None


def resumen(resultados: list[dict]) -> dict:
    total = len(resultados)
    correctas = sum(r["correcto"] for r in resultados)
    origenes: dict[str, int] = {}
    for r in resultados:
        clave = (r["origen"] or "sin_origen").split(":")[0]
        origenes[clave] = origenes.get(clave, 0) + 1
    latencias = [r["latencia_s"] for r in resultados]
    return {
        "total_preguntas": total,
        "correctas": correctas,
        "precision_pct": round(100 * correctas / total, 1) if total else 0.0,
        "textos_respaldados": sum(r["texto_respaldado"] for r in resultados),
        "latencia_media_s": round(sum(latencias) / total, 2) if total else None,
        "latencia_max_s": round(max(latencias), 2) if total else None,
        "por_origen": origenes,
    }


def guardar(path: Path, cabecera: dict, resultados: list[dict]) -> None:
    datos = {**cabecera, "resumen": resumen(resultados), "resultados": resultados}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description="Evalúa el pipeline Text-to-SQL contra el oráculo.")
    parser.add_argument("--model", default=None, help="Modelo de Ollama (default: el de llm/ollama_client.py)")
    parser.add_argument("--limit", type=int, default=None, help="Solo correr las primeras N preguntas")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--sin-plantillas", action="store_true", help="Desactiva plantillas por reglas y fallback sobre vistas")
    parser.add_argument("--output", default=None, help="JSON de resultados (default: eval/eval_results_<timestamp>.json)")
    parser.add_argument("--reanudar", action="store_true", help="Retoma --output: salta las preguntas ya evaluadas")
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    args = parser.parse_args()

    data = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    preguntas = data["preguntas"][: args.limit] if args.limit else data["preguntas"]

    client = OllamaClient(model=args.model) if args.model else OllamaClient()
    if not client.is_available():
        print(f"⚠ No se pudo conectar a Ollama en {client.host}. Ejecuta 'ollama serve' e intenta de nuevo.")
        sys.exit(1)

    output_path = Path(args.output) if args.output else Path(__file__).resolve().parent / f"eval_results_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    configuracion = {
        "max_retries": args.max_retries,
        "usar_plantillas": not args.sin_plantillas,
        "temperature": client.temperature,
        "num_ctx": client.num_ctx,
        "ground_truth": str(args.ground_truth.name),
    }
    cabecera = {"modelo": client.model, "fecha": dt.datetime.now().isoformat(timespec="seconds"), "configuracion": configuracion}
    resultados: list[dict] = []
    if args.reanudar and output_path.exists():
        previo = json.loads(output_path.read_text(encoding="utf-8"))
        if previo.get("modelo") != client.model or previo.get("configuracion") != configuracion:
            print("⚠ --reanudar: el archivo existente es de otro modelo o configuración; no se mezcla.")
            sys.exit(1)
        cabecera["fecha"] = previo["fecha"]
        resultados = previo["resultados"]
        print(f"Reanudando: {len(resultados)} pregunta(s) ya evaluadas en {output_path}")
    hechas = {r["id"] for r in resultados}

    print(f"=== Evaluación Text-to-SQL | modelo={client.model} | {len(preguntas)} preguntas | "
          f"plantillas={'sí' if configuracion['usar_plantillas'] else 'no'} | max_retries={args.max_retries} ===\n")

    for i, item in enumerate(preguntas, start=1):
        if item["id"] in hechas:
            continue
        print(f"[{i}/{len(preguntas)}] {item['id']}: {item['pregunta']}", flush=True)
        _, filas_ref = execute_readonly(item["sql_referencia"], limite_s=None)
        t0 = time.perf_counter()
        try:
            resultado = answer_question(
                item["pregunta"], client=client, max_retries=args.max_retries,
                usar_plantillas=configuracion["usar_plantillas"],
            )
        except Exception as exc:  # noqa: BLE001 - una pregunta rota no debe tumbar la corrida
            resultado = Text2SQLResult(pregunta=item["pregunta"], error=f"excepción {type(exc).__name__}: {exc}")
        latencia = time.perf_counter() - t0
        correcto, motivo = calificar(item, resultado, filas_ref)

        print(f"   SQL generado: {resultado.sql}")
        print(f"   Filas modelo: {resultado.filas[:5]}{' …' if len(resultado.filas) > 5 else ''}")
        print(f"   Referencia:   {filas_ref[:5]}{' …' if len(filas_ref) > 5 else ''}")
        print(f"   Respuesta:    {resultado.respuesta or resultado.error}")
        print(f"   {'✅' if correcto else '❌'} {motivo} | origen={resultado.origen} | intentos={resultado.intentos} | {latencia:.1f} s\n", flush=True)

        resultados.append({
            "id": item["id"],
            "pregunta": item["pregunta"],
            "sql_generado": resultado.sql,
            "sql_referencia": item["sql_referencia"],
            "filas_modelo": [list(f) for f in resultado.filas[:MAX_FILAS_GUARDADAS]],
            "total_filas_modelo": len(resultado.filas),
            "filas_referencia": [list(f) for f in filas_ref[:MAX_FILAS_GUARDADAS]],
            "respuesta_modelo": resultado.respuesta,
            "error_pipeline": resultado.error,
            "detalle_error": resultado.detalle_error,
            "origen": resultado.origen,
            "intentos": resultado.intentos,
            "latencia_s": round(latencia, 2),
            "correcto": correcto,
            "motivo": motivo,
            "texto_respaldado": texto_respaldado(resultado),
        })
        guardar(output_path, cabecera, resultados)

    cabecera["recursos_ollama"] = recursos_ollama(client)
    guardar(output_path, cabecera, resultados)
    r = resumen(resultados)
    print(f"=== RESULTADO FINAL: correctas {r['correctas']}/{r['total_preguntas']} ({r['precision_pct']}%) | "
          f"texto respaldado {r['textos_respaldados']}/{r['total_preguntas']} | latencia media {r['latencia_media_s']} s | "
          f"origen {r['por_origen']} | recursos {cabecera['recursos_ollama']} ===")
    print(f"Resultados detallados guardados en: {output_path}")


if __name__ == "__main__":
    main()
