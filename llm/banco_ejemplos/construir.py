"""
Construye y valida data/necesidades_negativas.json a partir de llm/banco_ejemplos/definiciones.py.

Para cada necesidad negativa:
  1. Valida el SQL con los mismos chequeos del chat (llm/sql_guard.py) y lo ejecuta en SOLO LECTURA.
  2. Rechaza: error, 0 filas, columnas todas NULL, porcentajes fuera de [0, 100] o negativos.
  3. Genera `respuesta_nl` con la plantilla rellenada con las filas REALES y comprueba con el chequeo
     de "texto confiable" del chat que toda cifra del texto sale del resultado (o de la pregunta).
  4. Anti-contaminación (D-41) contra TODAS las preguntas de evaluación (oráculo v4: DESARROLLO 30 y
     PRUEBA_2 20; y los 6 casos del juez): Jaccard de texto < UMBRAL_TEXTO, Jaccard de SQL < UMBRAL_SQL,
     SQL normalizado distinto, y que el resultado de la negativa NO sea la respuesta correcta de
     ninguna pregunta de evaluación (copiar el SQL no debe dar el acierto).

Uso:
    python -m llm.banco_ejemplos.construir                # valida y escribe el JSON
    python -m llm.banco_ejemplos.construir --solo-validar
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import date

from llm.banco_ejemplos import BANCO_PATH, RAIZ
from llm.banco_ejemplos.definiciones import NECESIDADES

UMBRAL_TEXTO = 0.35  # Jaccard de tokens de la pregunta (y variantes) frente a cualquier pregunta de evaluación
UMBRAL_SQL = 0.70    # Jaccard de tokens del SQL frente a cualquier SQL de referencia
_RE_PCT = re.compile(r"pct|porc|percent", re.IGNORECASE)


def preguntas_evaluacion() -> list[dict]:
    """[{id, pregunta, sql, origen, resultado, tipos, orden_importa | caso}] de todo lo que se evalúa."""
    oraculo = json.loads((RAIZ / "eval" / "ground_truth_olist.json").read_text(encoding="utf-8"))["preguntas"]
    casos = json.loads((RAIZ / "eval" / "casos_juez.json").read_text(encoding="utf-8"))["casos"]
    salida = [{"id": q["id"], "pregunta": q["pregunta"], "sql": q["sql_referencia"], "origen": q["conjunto"],
               "resultado": q["resultado_esperado"], "tipos": q["tipos_columnas"], "orden_importa": q["orden_importa"]}
              for q in oraculo]
    salida += [{"id": c["id"], "pregunta": c["pregunta"], "sql": c["sql_referencia"], "origen": "casos_juez", "caso": c}
               for c in casos]
    return salida


def _ejecutar(sql: str) -> tuple[list[str], list[list]]:
    from llm.schema_context import get_esquema_real, get_known_names
    from llm.sql_guard import (check_columnas_existentes, check_dominios_join, check_tablas_conocidas,
                               sanitizar_alias_reservados, validate_select_only)
    from llm.text_to_sql import execute_readonly

    limpio, _ = sanitizar_alias_reservados(validate_select_only(sql))
    check_tablas_conocidas(limpio, get_known_names())
    check_columnas_existentes(limpio, get_esquema_real())
    check_dominios_join(limpio)
    columnas, filas = execute_readonly(limpio)
    return columnas, [list(f) for f in filas]


def _problemas_resultado(columnas: list[str], filas: list[list]) -> list[str]:
    if not filas:
        return ["0 filas"]
    problemas = []
    for j, col in enumerate(columnas):
        valores = [f[j] for f in filas]
        if all(v is None for v in valores):
            problemas.append(f"columna {col} toda NULL")
        nums = [v for v in valores if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if _RE_PCT.search(col) and any(v < 0 or v > 100 for v in nums):
            problemas.append(f"porcentaje fuera de [0, 100] en {col}")
    return problemas


def _es_respuesta_correcta(filas: list[list], q: dict) -> bool:
    """¿El resultado de la negativa acertaría la pregunta de evaluación `q`?"""
    if "caso" in q:
        from llm.juez import veredicto_caso

        return veredicto_caso(q["caso"], filas)["correcto"]
    from eval.comparador import comparar

    try:
        return comparar([tuple(f) for f in filas], [tuple(f) for f in q["resultado"]], q["tipos"], q["orden_importa"]).correcto
    except ValueError:
        return False


def contaminacion(entrada: dict, filas: list[list], evaluacion: list[dict]) -> dict:
    """Máximas similitudes frente a la evaluación y lista de violaciones."""
    from eval.similitud import jaccard, tokens_sql, tokens_texto
    from llm.juez import normalizar_sql

    textos = [entrada["pregunta"], *entrada.get("variantes", [])]
    violaciones, max_texto, max_sql = [], (0.0, None), (0.0, None)
    for q in evaluacion:
        jt = max(jaccard(tokens_texto(t), tokens_texto(q["pregunta"])) for t in textos)
        js = jaccard(tokens_sql(entrada["sql"]), tokens_sql(q["sql"]))
        max_texto = max(max_texto, (jt, q["id"]), key=lambda x: x[0])
        max_sql = max(max_sql, (js, q["id"]), key=lambda x: x[0])
        if jt >= UMBRAL_TEXTO:
            violaciones.append(f"texto {jt:.3f} >= {UMBRAL_TEXTO} con {q['id']}")
        if js >= UMBRAL_SQL:
            violaciones.append(f"SQL {js:.3f} >= {UMBRAL_SQL} con {q['id']}")
        if normalizar_sql(entrada["sql"]) == normalizar_sql(q["sql"]):
            violaciones.append(f"SQL idéntico a {q['id']}")
        if _es_respuesta_correcta(filas, q):
            violaciones.append(f"su resultado acierta {q['id']}")
    return {"max_texto": round(max_texto[0], 3), "max_texto_con": max_texto[1],
            "max_sql": round(max_sql[0], 3), "max_sql_con": max_sql[1], "violaciones": violaciones}


def construir(escribir: bool) -> int:
    from llm.juez import _numeros_en
    from llm.text_to_sql import _respuesta_respaldada_por_datos

    evaluacion = preguntas_evaluacion()
    salida, fallos = [], 0
    ids = [e["id"] for e in NECESIDADES]
    if len(ids) != len(set(ids)):
        print("[FALLO] ids repetidos")
        fallos += 1
    for e in NECESIDADES:
        try:
            columnas, filas = _ejecutar(e["sql"])
        except (ValueError, sqlite3.Error) as exc:
            print(f"[FALLO] {e['id']}: {type(exc).__name__}: {exc}")
            fallos += 1
            continue
        problemas = _problemas_resultado(columnas, filas)
        try:
            plantilla = e["respuesta"]
            texto = plantilla(filas, len(filas)) if callable(plantilla) else plantilla.format(f=filas, n=len(filas))
        except (IndexError, TypeError, ValueError) as exc:
            problemas.append(f"plantilla de respuesta: {exc}")
            texto = ""
        if texto and not _respuesta_respaldada_por_datos(texto, [tuple(f) for f in filas], _numeros_en(e["pregunta"])):
            problemas.append("respuesta_nl con cifras que no salen del resultado")
        cont = contaminacion(e, filas, evaluacion)
        problemas += cont["violaciones"]
        estado = "OK" if not problemas else "FALLO"
        print(f"[{estado}] {e['id']}: {len(filas)} fila(s) | texto máx {cont['max_texto']:.3f} ({cont['max_texto_con']}) "
              f"| SQL máx {cont['max_sql']:.3f} ({cont['max_sql_con']})")
        for p in problemas:
            print(f"     - {p}")
        if problemas:
            fallos += 1
            continue
        print(f"     {texto}")
        salida.append({
            "id": e["id"], "familia": e["familia"], "pregunta": e["pregunta"], "variantes": e.get("variantes", []),
            "en_que_se_diferencia": e["en_que_se_diferencia"], "sql": e["sql"],
            "resumen_resultado": {"columnas": columnas, "filas": filas[:5], "total_filas": len(filas)},
            "respuesta_nl": texto, "trampas": e["trampas"],
            "similitud_maxima_evaluacion": {k: cont[k] for k in ("max_texto", "max_texto_con", "max_sql", "max_sql_con")},
        })
    por_familia = {}
    for e in salida:
        por_familia[e["familia"]] = por_familia.get(e["familia"], 0) + 1
    print(f"\nVálidas: {len(salida)}/{len(NECESIDADES)} | por familia: {por_familia} | fallos: {fallos}")
    if escribir and not fallos:
        BANCO_PATH.parent.mkdir(parents=True, exist_ok=True)
        BANCO_PATH.write_text(json.dumps({
            "version": 1, "fecha": date.today().isoformat(),
            "descripcion": "Necesidades negativas (D-41): parecidas a las necesidades 2, 4, 5, 6 y 8 pero distintas. "
                           "SQL ejecutado contra db/olist.db; respuesta_nl generada desde el resultado.",
            "generado_con": "python -m llm.banco_ejemplos.construir",
            "umbrales_anticontaminacion": {"texto_jaccard_max": UMBRAL_TEXTO, "sql_jaccard_max": UMBRAL_SQL,
                                           "sql_normalizado_distinto": True, "resultado_no_acierta_evaluacion": True},
            "necesidades": salida,
        }, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"Escrito {BANCO_PATH.relative_to(RAIZ)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-validar", action="store_true")
    raise SystemExit(construir(escribir=not ap.parse_args().solo_validar))
