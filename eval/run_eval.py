"""
Corre la suite de evaluación (eval/ground_truth.json) contra el pipeline
Text-to-SQL real (llm/text_to_sql.py + Ollama) y mide precisión objetiva.

Para cada pregunta:
  1. Se ejecuta el pipeline completo (genera SQL, valida, ejecuta, sintetiza).
  2. Se busca el valor numérico o el texto esperado tanto en la respuesta en
     lenguaje natural como en las celdas del resultado SQL crudo (esto último
     hace la calificación más objetiva: aunque el modelo redacte distinto,
     si el dato correcto está en el resultado, cuenta como acierto).
  3. Se compara contra `valor_esperado` con una tolerancia (absoluta o
     porcentual) definida por pregunta.

Esto mide tanto la capacidad del modelo para generar SQL correcto como su
fidelidad al sintetizar la respuesta (no inventar cifras que no están en los datos).

Uso:
    python eval/run_eval.py                          # corre eval/ground_truth_olist.json (default)
    python eval/run_eval.py --ground-truth eval/ground_truth.json  # otra suite (nota: llm/ ahora apunta a olist.db)
    python eval/run_eval.py --model llama3:latest     # usa un modelo distinto
    python eval/run_eval.py --limit 5                 # solo las primeras N (pruebas rápidas)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm.ollama_client import OllamaClient
from llm.text_to_sql import Text2SQLResult, _respuesta_respaldada_por_datos, answer_question

DEFAULT_GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth_olist.json"

_NUMERO_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")


def _extraer_numeros(texto: str) -> list[float]:
    numeros = []
    for m in _NUMERO_RE.findall(texto):
        try:
            numeros.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return numeros


def _espacio_busqueda(resultado: Text2SQLResult) -> str:
    celdas = [str(v) for fila in resultado.filas for v in fila if v is not None]
    return f"{resultado.respuesta or ''} {' '.join(celdas)}"


def _verifica_numero(esperado: float, texto: str, tol_abs: float | None, tol_pct: float | None, tambien_pct: bool) -> tuple[bool, float | None]:
    objetivos = [esperado]
    if tambien_pct:
        objetivos.append(esperado * 100)  # el modelo puede responder 76.94 en vez de 0.7694
    candidatos = _extraer_numeros(texto)
    for objetivo in objetivos:
        factor = 100 if objetivo != esperado else 1
        for c in candidatos:
            if tol_abs is not None and abs(c - objetivo) <= tol_abs * factor:
                return True, c
            if tol_pct is not None and objetivo != 0 and abs(c - objetivo) / abs(objetivo) <= tol_pct:
                return True, c
    return False, None


def _filas_para_verificar(resultado: Text2SQLResult) -> list[tuple]:
    """Filas a usar para chequear que la respuesta esté respaldada por datos
    -- en preguntas abiertas (descompuestas) no hay `resultado.filas` a nivel
    top, se usa la unión de las sub-consultas."""
    if resultado.sub_consultas:
        return [fila for sc in resultado.sub_consultas for fila in sc.get("filas", [])]
    return resultado.filas


def calificar(item: dict, resultado: Text2SQLResult) -> dict:
    texto_confiable = _respuesta_respaldada_por_datos(resultado.respuesta or "", _filas_para_verificar(resultado))

    if resultado.error:
        return {"sql_correcto": False, "texto_confiable": texto_confiable, "detalle": f"Pipeline falló: {resultado.error}"}

    espacio = _espacio_busqueda(resultado)
    tambien_pct = "fracción" in item.get("unidad", "")

    if item["tipo_verificacion"] == "texto":
        espacio_lower = espacio.lower()
        ok_texto = any(s.lower() in espacio_lower for s in item["contiene_cualquiera"])
        detalle = f"texto {'encontrado' if ok_texto else 'NO encontrado'}: {item['contiene_cualquiera']}"
        if "valor_esperado_numero" in item:
            ok_num, encontrado = _verifica_numero(
                item["valor_esperado_numero"], espacio, item.get("tolerancia_abs"), item.get("tolerancia_pct", 0.03), tambien_pct
            )
            detalle += f" | número {'OK' if ok_num else 'no encontrado'} (esperado≈{item['valor_esperado_numero']}, hallado={encontrado})"
        return {"sql_correcto": ok_texto, "texto_confiable": texto_confiable, "detalle": detalle}

    # tipo_verificacion == "numero"
    ok, encontrado = _verifica_numero(
        item["valor_esperado"], espacio, item.get("tolerancia_abs"), item.get("tolerancia_pct"), tambien_pct
    )
    detalle = f"esperado≈{item['valor_esperado']}, hallado={encontrado}"
    return {"sql_correcto": ok, "texto_confiable": texto_confiable, "detalle": detalle}


def main():
    parser = argparse.ArgumentParser(description="Evalúa el pipeline Text-to-SQL contra el ground truth.")
    parser.add_argument("--model", default=None, help="Override del modelo de Ollama a usar")
    parser.add_argument("--limit", type=int, default=None, help="Solo correr las primeras N preguntas")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--output", default=None, help="Ruta del JSON de resultados (default: eval/eval_results_<timestamp>.json)")
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH_PATH, help="Ruta del JSON de ground truth a usar")
    args = parser.parse_args()

    data = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    preguntas = data["preguntas"][: args.limit] if args.limit else data["preguntas"]

    client = OllamaClient(model=args.model) if args.model else OllamaClient()
    if not client.is_available():
        print(f"⚠ No se pudo conectar a Ollama en {client.host}. Ejecuta 'ollama serve' e intenta de nuevo.")
        sys.exit(1)

    print(f"=== Evaluación Text-to-SQL | modelo={client.model} | {len(preguntas)} preguntas ===\n")

    resultados_out = []
    sql_correctas = 0
    textos_confiables = 0
    for i, item in enumerate(preguntas, start=1):
        print(f"[{i}/{len(preguntas)}] {item['id']}: {item['pregunta']}")
        resultado = answer_question(item["pregunta"], client=client, max_retries=args.max_retries)
        calificacion = calificar(item, resultado)
        estado_sql = "✅" if calificacion["sql_correcto"] else "❌"
        estado_texto = "✅" if calificacion["texto_confiable"] else "❌"
        print(f"   SQL generado: {resultado.sql}")
        print(f"   Respuesta:    {resultado.respuesta or resultado.error}")
        print(f"   SQL correcto: {estado_sql}  |  Texto confiable: {estado_texto} — {calificacion['detalle']}\n")

        if calificacion["sql_correcto"]:
            sql_correctas += 1
        if calificacion["texto_confiable"]:
            textos_confiables += 1

        resultados_out.append({
            "id": item["id"],
            "pregunta": item["pregunta"],
            "sql_generado": resultado.sql,
            "sql_referencia": item["sql_referencia"],
            "respuesta_modelo": resultado.respuesta,
            "error_pipeline": resultado.error,
            "intentos": resultado.intentos,
            "sql_correcto": calificacion["sql_correcto"],
            "texto_confiable": calificacion["texto_confiable"],
            "detalle_calificacion": calificacion["detalle"],
        })

    total = len(preguntas)
    precision_sql = round(100 * sql_correctas / total, 1) if total else 0.0
    precision_texto = round(100 * textos_confiables / total, 1) if total else 0.0
    print(f"=== RESULTADO FINAL: SQL correcto {sql_correctas}/{total} ({precision_sql}%)  |  Texto confiable {textos_confiables}/{total} ({precision_texto}%) ===")

    output_path = Path(args.output) if args.output else Path(__file__).resolve().parent / f"eval_results_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(
        json.dumps({
            "modelo": client.model,
            "fecha": dt.datetime.now().isoformat(),
            "total_preguntas": total,
            "sql_correctas": sql_correctas,
            "precision_sql_pct": precision_sql,
            "textos_confiables": textos_confiables,
            "precision_texto_pct": precision_texto,
            "resultados": resultados_out,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Resultados detallados guardados en: {output_path}")


if __name__ == "__main__":
    main()
