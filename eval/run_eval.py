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
from eval.pistas import MODOS, censurar, construir_pista, motivo_generico, valores_de_referencia
from llm.juez import JuezLLM
from llm.ollama_client import OllamaClient
from llm.text_to_sql import (
    MENSAJE_PROBLEMA_TRAS_REINTENTO,
    MENSAJE_RESUMEN_NO_CONFIABLE,
    MENSAJE_SIN_RESULTADOS,
    TIPOS_FALLO,
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


def clasificar_intentos(resultado: Text2SQLResult, correcto: bool) -> tuple[str, list[dict]]:
    """Fase 2. Devuelve (clasificación final de la pregunta, intentos).

    Cada intento trae el `tipo` que le dio el pipeline (llm/text_to_sql.py:
    clasificar_excepcion y la rama de 0 filas). Un intento "ok" del pipeline
    solo significa que el SQL corrió y devolvió filas: si es el último y el
    árbitro lo rechaza, se reclasifica como "semantico" en `tipo_evaluado`."""
    intentos = [dict(d) for d in resultado.intentos_detalle]
    for d in intentos:
        # Con --cadena, un intento que corrió pero el árbitro rechazó (verificado=False) es semántico.
        d["tipo_evaluado"] = "semantico" if d.get("verificado") is False else d["tipo"]
    if correcto:
        return "ok", intentos
    if resultado.sub_consultas:
        # Respondió con varias sub-consultas en lugar de una: corre, pero no es lo pedido.
        # Cada sub-consulta que "corrió bien" tampoco responde la pregunta.
        for d in intentos:
            if d["tipo"] == "ok":
                d["tipo_evaluado"] = "semantico"
        return "semantico", intentos
    if not intentos:
        # Sin ningún intento registrado: el pipeline falló antes de generar SQL.
        return "infra", intentos
    if intentos[-1]["tipo"] == "ok":
        intentos[-1]["tipo_evaluado"] = "semantico"
    return intentos[-1]["tipo_evaluado"], intentos


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
    por_clasificacion = {t: 0 for t in TIPOS_FALLO}
    por_intento = {t: 0 for t in TIPOS_FALLO}
    for r in resultados:
        por_clasificacion[r["clasificacion"]] += 1
        for d in r["intentos_detalle"]:
            por_intento[d["tipo_evaluado"]] += 1
    juez = {"acierto_coinciden": 0, "fallo_coinciden": 0, "falso_acierto": 0, "falso_rechazo": 0, "sin_opinion": 0}
    for r in resultados:
        for o in r.get("opiniones_juez", []):
            if o["juez"] is None:
                juez["sin_opinion"] += 1
            elif o["juez"] and o["arbitro"]:
                juez["acierto_coinciden"] += 1
            elif not o["juez"] and not o["arbitro"]:
                juez["fallo_coinciden"] += 1
            elif o["juez"] and not o["arbitro"]:
                juez["falso_acierto"] += 1  # el juez lo da por bueno; el árbitro no
            else:
                juez["falso_rechazo"] += 1  # el juez lo rechaza; el árbitro lo da por bueno
    return {
        "juez_vs_arbitro": juez if any(juez.values()) else None,
        "total_preguntas": total,
        "correctas": correctas,
        "precision_pct": round(100 * correctas / total, 1) if total else 0.0,
        "textos_respaldados": sum(r["texto_respaldado"] for r in resultados),
        "latencia_media_s": round(sum(latencias) / total, 2) if total else None,
        "latencia_max_s": round(max(latencias), 2) if total else None,
        "por_origen": origenes,
        "clasificacion_final": por_clasificacion,
        "clasificacion_por_intento": por_intento,
    }


def guardar(path: Path, cabecera: dict, resultados: list[dict]) -> None:
    datos = {**cabecera, "resumen": resumen(resultados), "resultados": resultados}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def crear_verificador(
    item: dict, filas_ref: list, modo_feedback: str, juez: JuezLLM | None, registro: dict, opinar: bool = False,
):
    """Verificador de la cadena de intentos (Fases 7, 8 y 9): el árbitro decide;
    si rechaza, se arma la pista (sin valores de la referencia) y, si hay juez,
    se registra su opinión para compararla con el árbitro."""
    valores = valores_de_referencia(filas_ref, item["tipos_columnas"])

    def verificar(sql: str, columnas: list, filas: list):
        v = comparar(filas, filas_ref, item["tipos_columnas"], item.get("orden_importa", False))
        if opinar and juez is not None:
            o = juez.opinar(item["pregunta"], sql, columnas, filas)
            registro["opiniones_juez"].append({"juez": o.valor, "arbitro": v.correcto, "motivo_juez": o.motivo})
        if v.correcto:
            return True, None
        diagnostico = None
        if modo_feedback == "juez" and juez is not None:
            diagnostico = juez.diagnosticar(item["pregunta"], sql, columnas, filas, motivo_generico(v.motivo))
            registro["diagnosticos_juez"].append(diagnostico)
        pista, censuradas = censurar(construir_pista(modo_feedback, v.motivo, diagnostico), valores)
        registro["pistas"].append({"pista": pista, "formas_censuradas": censuradas})
        return False, pista

    return verificar


def main():
    parser = argparse.ArgumentParser(description="Evalúa el pipeline Text-to-SQL contra el oráculo.")
    parser.add_argument("--model", default=None, help="Modelo de Ollama (default: el de llm/ollama_client.py)")
    parser.add_argument("--limit", type=int, default=None, help="Solo correr las primeras N preguntas")
    parser.add_argument("--ids", nargs="+", default=None, help="Solo estas preguntas (ids del oráculo)")
    parser.add_argument("--conjunto", choices=["desarrollo", "prueba", "todos"], default="desarrollo",
                        help="Conjunto del oráculo v3. PRUEBA es held-out: solo para la evaluación final (Paso 5)")
    parser.add_argument("--intentos", type=int, default=2, help="N: intentos TOTALES por pregunta (Fase 6)")
    parser.add_argument("--cadena", action="store_true",
                        help="El árbitro verifica cada intento y la cadena se corta en el primer acierto (Fase 9)")
    parser.add_argument("--feedback", choices=MODOS, default="generico", help="Pista entre intentos con --cadena (Fase 7)")
    parser.add_argument("--juez", action="store_true", help="Registra la opinión del juez-LLM en cada intento verificado (Fase 8)")
    parser.add_argument("--temperature", type=float, default=None, help="Temperatura del generador de SQL")
    parser.add_argument("--sin-plantillas", action="store_true", help="Desactiva plantillas por reglas y fallback sobre vistas")
    parser.add_argument("--output", default=None, help="JSON de resultados (default: eval/eval_results_<timestamp>.json)")
    parser.add_argument("--reanudar", action="store_true", help="Retoma --output: salta las preguntas ya evaluadas")
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH)
    args = parser.parse_args()
    if (args.juez or args.feedback == "juez") and not args.cadena:
        parser.error("--juez y --feedback juez requieren --cadena")

    data = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    preguntas = data["preguntas"]
    if args.conjunto != "todos" and any("conjunto" in q for q in preguntas):
        preguntas = [q for q in preguntas if q.get("conjunto") == args.conjunto]
    preguntas = preguntas[: args.limit] if args.limit else preguntas
    if args.ids:
        preguntas = [q for q in preguntas if q["id"] in set(args.ids)]

    client = OllamaClient(model=args.model) if args.model else OllamaClient()
    if args.temperature is not None:
        client.temperature = args.temperature
    if not client.is_available():
        print(f"⚠ No se pudo conectar a Ollama en {client.host}. Ejecuta 'ollama serve' e intenta de nuevo.")
        sys.exit(1)
    juez = JuezLLM(OllamaClient(model=client.model)) if (args.juez or args.feedback == "juez") else None

    output_path = Path(args.output) if args.output else Path(__file__).resolve().parent / f"eval_results_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    configuracion = {
        "n_intentos": args.intentos,
        "cadena_con_arbitro": args.cadena,
        "feedback": args.feedback if args.cadena else None,
        "juez": bool(juez),
        "usar_plantillas": not args.sin_plantillas,
        "temperature": client.temperature,
        "num_ctx": client.num_ctx,
        "ground_truth": str(args.ground_truth.name),
        "conjunto": args.conjunto,
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
          f"plantillas={'sí' if configuracion['usar_plantillas'] else 'no'} | N={args.intentos} | "
          f"cadena={'sí (' + args.feedback + ')' if args.cadena else 'no'} | juez={'sí' if juez else 'no'} | "
          f"temperature={client.temperature} ===\n")

    for i, item in enumerate(preguntas, start=1):
        if item["id"] in hechas:
            continue
        print(f"[{i}/{len(preguntas)}] {item['id']}: {item['pregunta']}", flush=True)
        _, filas_ref = execute_readonly(item["sql_referencia"], limite_s=None)
        registro = {"opiniones_juez": [], "diagnosticos_juez": [], "pistas": []}
        verificador = crear_verificador(item, filas_ref, args.feedback, juez, registro, opinar=args.juez) if args.cadena else None
        t0 = time.perf_counter()
        try:
            resultado = answer_question(
                item["pregunta"], client=client, n_intentos=args.intentos,
                usar_plantillas=configuracion["usar_plantillas"], verificador=verificador,
            )
        except Exception as exc:  # noqa: BLE001 - una pregunta rota no debe tumbar la corrida
            resultado = Text2SQLResult(pregunta=item["pregunta"], error=f"excepción {type(exc).__name__}: {exc}")
        latencia = time.perf_counter() - t0
        correcto, motivo = calificar(item, resultado, filas_ref)
        clasificacion, intentos_detalle = clasificar_intentos(resultado, correcto)

        print(f"   SQL generado: {resultado.sql}")
        print(f"   Filas modelo: {resultado.filas[:5]}{' …' if len(resultado.filas) > 5 else ''}")
        print(f"   Referencia:   {filas_ref[:5]}{' …' if len(filas_ref) > 5 else ''}")
        print(f"   Respuesta:    {resultado.respuesta or resultado.error}")
        print(f"   Intentos:     {[d['tipo_evaluado'] for d in intentos_detalle]}")
        for k, pz in enumerate(registro["pistas"], start=1):
            print(f"   Pista {k}:      {pz['pista']}" + (f"  [censuradas: {pz['formas_censuradas']}]" if pz["formas_censuradas"] else ""))
        if registro["opiniones_juez"]:
            print(f"   Juez vs árbitro: {[(o['juez'], o['arbitro']) for o in registro['opiniones_juez']]}")
        print(f"   {'✅' if correcto else '❌'} [{clasificacion}] {motivo} | origen={resultado.origen} | intentos={resultado.intentos} | {latencia:.1f} s\n", flush=True)

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
            "clasificacion": clasificacion,
            "motivo": motivo,
            "intentos_detalle": intentos_detalle,
            "texto_respaldado": texto_respaldado(resultado),
            **registro,
        })
        guardar(output_path, cabecera, resultados)

    cabecera["recursos_ollama"] = recursos_ollama(client)
    guardar(output_path, cabecera, resultados)
    r = resumen(resultados)
    print(f"=== RESULTADO FINAL: correctas {r['correctas']}/{r['total_preguntas']} ({r['precision_pct']}%) | "
          f"texto respaldado {r['textos_respaldados']}/{r['total_preguntas']} | latencia media {r['latencia_media_s']} s | "
          f"origen {r['por_origen']} | recursos {cabecera['recursos_ollama']} ===")
    print(f"=== CLASIFICACIÓN FINAL (por pregunta): {r['clasificacion_final']} ===")
    print(f"=== CLASIFICACIÓN POR INTENTO: {r['clasificacion_por_intento']} ===")
    if r["juez_vs_arbitro"]:
        print(f"=== JUEZ vs ÁRBITRO (por intento verificado): {r['juez_vs_arbitro']} ===")
    print(f"Resultados detallados guardados en: {output_path}")


if __name__ == "__main__":
    main()
