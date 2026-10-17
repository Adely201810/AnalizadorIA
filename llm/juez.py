"""
Juez-LLM (Fases 6, 8 y 10): un componente SEPARADO del generador de SQL.

Nunca decide si una respuesta es correcta: en la evaluación ese veredicto es
del árbitro determinista (eval/comparador.py). El juez solo:
  - opinar():           da su opinión (¿el SQL responde la pregunta?) para MEDIR
                        cuánto coincide con el árbitro (Fase 8).
  - diagnosticar():     explica qué parte del ENFOQUE parece estar mal, sin
                        conocer la respuesta correcta (pista entre intentos,
                        Fase 7; explicación del fallo, Fase 8).
  - evaluar_sensatez(): en el chat libre, revisa si el SQL tiene sentido para la
                        pregunta (columnas, JOINs, agregación), sin afirmar que
                        la cifra sea correcta (Fase 10).

Nunca recibe valores de la referencia.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from llm.ollama_client import OllamaClient, OllamaError

MAX_FILAS_AL_JUEZ = 10

_SISTEMA_OPINAR = """Eres un revisor experto de consultas SQL sobre una base de datos de e-commerce (Olist, SQLite). \
Recibes una pregunta de negocio en español, la consulta SQL que se ejecutó y una muestra de su resultado. \
Decide si la consulta responde EXACTAMENTE lo que pide la pregunta: la métrica correcta, el filtro correcto, \
el nivel de agregación correcto (por pedido, por cliente, por categoría...) y las columnas pedidas. \
No conoces la respuesta correcta. Responde SOLO con JSON en una línea: \
{"responde": true o false, "motivo": "una frase"}"""

_SISTEMA_DIAGNOSTICAR = """Eres un revisor experto de consultas SQL sobre una base de datos de e-commerce (Olist, SQLite). \
Una verificación automática indica que la consulta NO responde correctamente la pregunta. No conoces la \
respuesta correcta y no debes inventar cifras. En 1 o 2 frases, en español, señala qué parte del ENFOQUE de la \
consulta probablemente está mal (por ejemplo: filtro, tabla o columna usada, JOIN que duplica filas, nivel de \
agregación, promedio de promedios, división mal planteada) y cómo corregir el enfoque. No escribas SQL ni números."""

_SISTEMA_SENSATEZ = """Eres un revisor experto de consultas SQL sobre una base de datos de e-commerce (Olist, SQLite). \
Recibes una pregunta en español y la consulta SQL que se ejecutó. NO juzgues si la cifra es correcta (no la \
conoces); solo si la consulta TIENE SENTIDO para la pregunta: usa columnas y tablas adecuadas, los JOIN unen \
llaves del mismo tipo, agrega al nivel que pide la pregunta y filtra lo que la pregunta menciona. \
Responde SOLO con JSON en una línea: {"tiene_sentido": true o false, "motivo": "una frase"}"""


@dataclass
class OpinionJuez:
    valor: bool | None  # None = el juez no devolvió un JSON interpretable
    motivo: str
    crudo: str


def _muestra(columnas: list, filas: list) -> str:
    if not filas:
        return "(sin filas)"
    lineas = [" | ".join(map(str, columnas))] if columnas else []
    lineas += [" | ".join("NULL" if v is None else str(v) for v in f) for f in filas[:MAX_FILAS_AL_JUEZ]]
    if len(filas) > MAX_FILAS_AL_JUEZ:
        lineas.append(f"... ({len(filas) - MAX_FILAS_AL_JUEZ} filas más)")
    return "\n".join(lineas)


def _leer_json(texto: str, clave: str) -> OpinionJuez:
    m = re.search(r"\{.*\}", texto, re.S)
    if m:
        try:
            datos = json.loads(m.group(0))
            valor = datos.get(clave)
            if isinstance(valor, str):
                valor = {"true": True, "false": False}.get(valor.strip().lower())
            return OpinionJuez(valor if isinstance(valor, bool) else None, str(datos.get("motivo", "")), texto)
        except json.JSONDecodeError:
            pass
    return OpinionJuez(None, "respuesta del juez no interpretable", texto)


class JuezLLM:
    def __init__(self, client: OllamaClient | None = None):
        self.client = client or OllamaClient()

    def _llamar(self, sistema: str, prompt: str, num_predict: int) -> str:
        return self.client.generate(prompt, system=sistema, num_predict=num_predict, temperature=0)

    def opinar(self, pregunta: str, sql: str, columnas: list, filas: list) -> OpinionJuez:
        prompt = f"Pregunta: {pregunta}\n\nSQL ejecutado:\n{sql}\n\nResultado ({len(filas)} fila(s)):\n{_muestra(columnas, filas)}"
        try:
            return _leer_json(self._llamar(_SISTEMA_OPINAR, prompt, 120), "responde")
        except OllamaError as exc:
            return OpinionJuez(None, f"juez no disponible: {exc}", "")

    def diagnosticar(self, pregunta: str, sql: str, columnas: list, filas: list, problema: str) -> str:
        prompt = (
            f"Pregunta: {pregunta}\n\nSQL ejecutado:\n{sql}\n\nResultado ({len(filas)} fila(s)):\n{_muestra(columnas, filas)}"
            f"\n\nProblema detectado por la verificación automática: {problema}"
        )
        try:
            return self._llamar(_SISTEMA_DIAGNOSTICAR, prompt, 150).strip()
        except OllamaError as exc:
            return f"(sin diagnóstico: {exc})"

    def evaluar_sensatez(self, pregunta: str, sql: str) -> OpinionJuez:
        prompt = f"Pregunta: {pregunta}\n\nSQL ejecutado:\n{sql}"
        try:
            return _leer_json(self._llamar(_SISTEMA_SENSATEZ, prompt, 120), "tiene_sentido")
        except OllamaError as exc:
            return OpinionJuez(None, f"juez no disponible: {exc}", "")


def texto_revision(revision: dict | None) -> str | None:
    """La revisión del juez NO es una verificación de la cifra: solo dice si el SQL
    parece coherente con la pregunta. El texto lo deja explícito."""
    if not revision:
        return None
    aviso = "Revisión automática del SQL (un segundo modelo revisó si la consulta tiene sentido para la pregunta; no comprueba que la cifra sea correcta)"
    if revision.get("tiene_sentido") is True:
        return f"🔎 {aviso}: parece coherente. {revision.get('motivo', '')}"
    if revision.get("tiene_sentido") is False:
        return f"⚠️ {aviso}: posible problema. {revision.get('motivo', '')}"
    return f"🔎 {aviso}: no se pudo obtener una revisión."


# =============================================================================
# Juez ITERATIVO con retroalimentación (tarea "juez iterativo", Fases 3-4; D-34).
#
# Solo para evaluar preguntas del catálogo (eval/casos_juez.json): usa la respuesta
# correcta, así que acierto@N NO es comparable con PRUEBA_2. El veredicto es
# DETERMINISTA (criterio_aceptacion del caso); el LLM, si se usa, solo redacta la
# pista. Un filtro determinista (detectar_fuga) impide que la pista revele cifras
# o valores esperados o fragmentos del SQL de referencia. El modelo candidato
# recibe solo: la pregunta, su SQL anterior, un resumen de su resultado y las pistas.
# =============================================================================

import sqlite3
import time
from typing import Any, Callable

from llm.ollama_client import ContextoInsuficienteError

FORMATO_SQL_JSON = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}
NUM_PREDICT_CANDIDATO = 600
NUM_PREDICT_PISTA = 220
MAX_FILAS_RESUMEN = 5
NGRAMA_FUGA_SQL = 6  # tokens seguidos del SQL de referencia que cuentan como fuga
CONCEPTOS_REVISION = (
    "JOIN que multiplica filas (agrega cada tabla de detalle por pedido antes de unir), COUNT frente a "
    "COUNT(DISTINCT), granularidad del GROUP BY, condición en WHERE frente a HAVING, fechas NULL, promedio "
    "de razones frente a razón de sumas, y división entera en SQLite."
)

_SISTEMA_PISTA = """Eres un experto en SQL (SQLite) que ayuda a un analista junior a corregir una consulta \
sobre una base de e-commerce (Olist). Una verificación automática ya determinó que su consulta NO responde \
correctamente la pregunta. Tú sí conoces una consulta de referencia correcta, pero el junior NO debe verla.

Errores típicos que debes considerar: JOIN en abanico que duplica filas (unir order_items con order_payments u \
order_reviews antes de agregar), COUNT frente a COUNT(DISTINCT), granularidad equivocada del GROUP BY (por \
artículo en vez de por pedido o cliente), condición en WHERE que debía ir en HAVING (o al revés), fechas NULL \
de pedidos no entregados, promedio de razones fila a fila en lugar de SUM/SUM, división entera en SQLite \
(usa 100.0 * a / b), customer_id frente a customer_unique_id, y pedidos cancelados o no disponibles.

Reglas OBLIGATORIAS de tu respuesta:
- Escribe 1 a 3 frases en español, dirigidas al junior.
- NUNCA escribas SQL ni fragmentos de la consulta de referencia.
- NUNCA escribas cifras, valores ni nombres que aparezcan en el resultado correcto. No digas cuál es la respuesta.
- Ajusta el nivel de detalle al que se te indique."""

_INSTRUCCION_NIVEL = {
    1: "Nivel 1: di solo QUÉ TIPO de error es (por ejemplo: de agregación, de filtro, de granularidad, de unión).",
    2: "Nivel 2: señala el CONCEPTO o la columna/tabla implicada en el error, sin dar la solución completa.",
    3: "Nivel 3: explica la TRAMPA concreta en la que cayó la consulta y cómo evitarla, sin escribir SQL ni cifras.",
}


# --- 1. Ejecución del SQL candidato (solo lectura, mismas validaciones que el chat) ---

def ejecutar_sql_candidato(sql: str) -> dict:
    from llm.schema_context import get_esquema_real, get_known_names
    from llm.sql_guard import (
        SQLQualityError, SQLValidationError, check_columnas_existentes, check_dominios_join,
        check_literales_placeholder, check_tablas_conocidas, sanitizar_alias_reservados, validate_select_only,
    )
    from llm.text_to_sql import execute_readonly

    base = {"sql": sql, "ok": False, "etapa": None, "error": None, "columnas": [], "filas": [], "segundos": 0.0,
            "detalles": []}
    if not sql or not sql.strip():
        return {**base, "etapa": "generacion", "error": "el modelo no devolvió ninguna consulta"}
    try:
        limpio, _ = sanitizar_alias_reservados(validate_select_only(sql))
        check_literales_placeholder(limpio)
        check_tablas_conocidas(limpio, get_known_names())
        check_columnas_existentes(limpio, get_esquema_real())
        check_dominios_join(limpio)
    except (SQLValidationError, SQLQualityError) as exc:
        return {**base, "etapa": "validacion", "error": str(exc), "detalles": getattr(exc, "detalles", [])}
    t0 = time.perf_counter()
    try:
        columnas, filas = execute_readonly(limpio)
    except sqlite3.Error as exc:
        return {**base, "etapa": "ejecucion", "error": str(exc), "segundos": time.perf_counter() - t0}
    return {**base, "sql": limpio, "ok": True, "columnas": list(columnas), "filas": [list(f) for f in filas],
            "segundos": time.perf_counter() - t0}


# --- 2. Veredicto determinista (criterio_aceptacion) ---

def _texto(v) -> str:
    return str(v).strip().lower()


def _valor_ok(celda, esperado: dict) -> bool:
    from eval.comparador import valor_coincide

    if celda is None:
        return False
    try:
        return valor_coincide(celda, esperado["valor"], esperado["tipo"])
    except ValueError:
        return False


def _fila_contiene(fila: list, valores: list[dict]) -> bool:
    """Cada valor esperado en una celda DISTINTA de la fila (backtracking)."""
    def asignar(i: int, usadas: frozenset) -> bool:
        if i == len(valores):
            return True
        return any(k not in usadas and _valor_ok(fila[k], valores[i]) and asignar(i + 1, usadas | {k})
                   for k in range(len(fila)))
    return asignar(0, frozenset())


def comprobar(comp: dict, filas: list[list]) -> tuple[bool, str]:
    """Una comprobación del criterio. El motivo NO incluye valores esperados."""
    tipo = comp["comparador"]
    if not filas:
        return False, "sin filas"
    if tipo == "valor_con_tolerancia":
        celdas = filas[0] if comp.get("donde", "primera_fila") == "primera_fila" else [c for f in filas for c in f]
        ok = any(_valor_ok(c, comp) for c in celdas)
        return ok, "valor encontrado" if ok else "el valor clave no aparece (dentro de tolerancia)"
    if tipo == "fila_contiene":
        if comp.get("max_filas") and len(filas) > comp["max_filas"]:
            return False, "devolvió más filas de las admitidas"
        candidatas = filas[:1] if comp.get("fila", "cualquiera") == "primera" else filas
        ok = any(_fila_contiene(f, comp["valores"]) for f in candidatas)
        return ok, "fila encontrada" if ok else "ninguna fila contiene juntas las cifras clave"
    if tipo == "top_k_igual":
        k = comp["k"]
        if len(filas) < k:
            return False, "menos filas que el top pedido"
        esperados = [_texto(v) for v in comp["valores"]]
        for c in range(len(filas[0])):
            obtenidos = [_texto(filas[i][c]) for i in range(k)]
            if (obtenidos == esperados) if comp.get("orden_importa", True) else (sorted(obtenidos) == sorted(esperados)):
                return True, "top coincide"
        return False, "el top no coincide"
    if tipo == "conjunto_igual":
        esperados = {_texto(v) for v in comp["valores"]}
        if len(filas) != len(esperados):
            return False, "la cantidad de filas no coincide con el conjunto esperado"
        for c in range(len(filas[0])):
            if {_texto(f[c]) for f in filas} == esperados:
                return True, "conjunto coincide"
        return False, "el conjunto no coincide"
    raise ValueError(f"comparador desconocido: {tipo!r}")


def veredicto_caso(caso: dict, filas: list[list]) -> dict:
    resultados = []
    for comp in caso["criterio_aceptacion"]["comprobaciones"]:
        ok, motivo = comprobar(comp, filas)
        resultados.append({"comparador": comp["comparador"], "ok": ok, "motivo": motivo})
    return {"correcto": bool(resultados) and all(r["ok"] for r in resultados), "comprobaciones": resultados}


# --- 3. Diagnóstico estructurado (sin revelar valores esperados) ---

_RE_COL_PORCENTAJE = re.compile(r"pct|porc|percent|tasa|proporc|ratio", re.IGNORECASE)


def chequeos_sensatez(columnas: list[str], filas: list[list]) -> list[str]:
    if not filas:
        return ["La consulta no devolvió ninguna fila (0 filas)."]
    avisos = []
    for j, col in enumerate(columnas):
        valores = [f[j] for f in filas]
        nums = [v for v in valores if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if all(v is None for v in valores):
            avisos.append(f"La columna '{col}' es NULL en todas las filas.")
        if any(v < 0 for v in nums):
            avisos.append(f"La columna '{col}' tiene valores negativos: revisa si tiene sentido.")
        if _RE_COL_PORCENTAJE.search(col or ""):
            if any(v > 100 for v in nums):
                avisos.append(f"La columna '{col}' parece un porcentaje y tiene valores mayores que 100.")
            if nums and all(isinstance(v, int) for v in nums) and len(set(nums)) <= 2:
                avisos.append(f"La columna '{col}' parece un porcentaje y solo tiene enteros: posible división entera.")
    return avisos


def _valores_por_fila_requeridos(caso: dict) -> int:
    n = 1
    for comp in caso["criterio_aceptacion"]["comprobaciones"]:
        if comp["comparador"] == "fila_contiene":
            n = max(n, len(comp["valores"]))
    return n


def diagnosticar_intento(caso: dict, ejec: dict) -> dict:
    diag: dict[str, Any] = {"error": None, "forma": [], "patrones": [], "sanidad": []}
    if not ejec["ok"]:
        diag["error"] = f"{ejec['etapa']}: {ejec['error']}"
    else:
        filas, columnas = ejec["filas"], ejec["columnas"]
        n_ref = len(caso["resultado_referencia"]["filas"])
        if n_ref == 1 and len(filas) > 1:
            diag["forma"].append(f"La pregunta pide una sola respuesta (una fila) y la consulta devolvió {len(filas)} filas.")
        elif len(filas) > n_ref:
            diag["forma"].append("La consulta devolvió más filas de las que pide la pregunta.")
        elif 0 < len(filas) < n_ref:
            diag["forma"].append("La consulta devolvió menos filas de las que pide la pregunta.")
        if filas and len(columnas) < _valores_por_fila_requeridos(caso):
            diag["forma"].append("Faltan columnas: la pregunta pide más datos por fila de los que devolvió la consulta.")
        diag["sanidad"] = chequeos_sensatez(columnas, filas)
    sql = ejec.get("sql") or ""
    diag["patrones"] = [p["diagnostico"] for p in caso["patrones_error"] if re.search(p["regex"], sql, re.IGNORECASE)]
    return diag


# --- 4. Retroalimentación: plantilla o LLM, con niveles crecientes ---

def nivel_pista(intento: int) -> int:
    return min(intento, 3)


def retro_plantilla(diag: dict, nivel: int) -> str:
    partes = []
    if diag["error"]:
        partes.append(f"La consulta anterior falló ({diag['error']}). Corrige ese error.")
    else:
        partes.append("La consulta anterior se ejecutó, pero su resultado NO responde correctamente la pregunta.")
    partes += diag["forma"] + diag["sanidad"]
    if nivel >= 2 and diag["patrones"]:
        partes += [f"Posible causa: {p}" for p in diag["patrones"]]
    if nivel >= 3 or (nivel >= 2 and not diag["patrones"]):
        partes.append(f"Revisa con cuidado: {CONCEPTOS_REVISION}")
    return " ".join(partes)


_RE_TOKEN_SQL = re.compile(r"'[^']*'|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|<=|>=|!=|<>|[^\s\w]")


def _tokens_sql(texto: str) -> list[str]:
    return [t.lower() for t in _RE_TOKEN_SQL.findall(texto or "")]


def _ngramas(tokens: list[str], n: int) -> set[tuple]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _numeros_en(texto: str) -> list[float]:
    from llm.text_to_sql import _extraer_numeros_respuesta

    return [n for n, _ in _extraer_numeros_respuesta(texto or "")]


def _numeros_prohibidos(caso: dict) -> list[float]:
    """Cifras del resultado esperado (todas sus celdas, también números dentro de texto) y cifras
    clave. Se permiten las que ya están en la pregunta (umbrales) y los enteros < 10."""
    from llm.text_to_sql import _numeros_de_filas

    nums = _numeros_de_filas([tuple(f) for f in caso["resultado_referencia"]["filas"]])
    nums += [float(c["valor"]) for c in caso.get("cifras_clave_nl", [])]
    for comp in caso["criterio_aceptacion"]["comprobaciones"]:
        for v in comp.get("valores") or []:
            if isinstance(v, dict) and v.get("tipo") != "texto":
                nums.append(float(v["valor"]))
        if comp["comparador"] == "valor_con_tolerancia" and comp.get("tipo") != "texto":
            nums.append(float(comp["valor"]))
    en_pregunta = _numeros_en(caso["pregunta"])
    return sorted({n for n in nums
                   if not (float(n).is_integer() and abs(n) < 10)
                   and not any(abs(n - p) < 1e-9 for p in en_pregunta)})


def _textos_prohibidos(caso: dict) -> list[str]:
    textos = []
    for comp in caso["criterio_aceptacion"]["comprobaciones"]:
        for v in comp.get("valores") or []:
            if isinstance(v, dict):
                if v.get("tipo") == "texto":
                    textos.append(str(v["valor"]))
            else:
                textos.append(str(v))
        if comp["comparador"] == "valor_con_tolerancia" and comp.get("tipo") == "texto":
            textos.append(str(comp["valor"]))
    pregunta = caso["pregunta"].lower()
    return sorted({t for t in textos if t.lower() not in pregunta})


def detectar_fuga(texto: str, caso: dict) -> list[str]:
    """Motivos por los que `texto` revela la respuesta (lista vacía = no hay fuga):
    cifras del resultado esperado (también redondeadas), valores de texto esperados, o
    >= NGRAMA_FUGA_SQL tokens seguidos del SQL de referencia."""
    from llm.text_to_sql import _extraer_numeros_respuesta, _numero_respaldado

    motivos = []
    prohibidos = _numeros_prohibidos(caso)
    for numero, decimales in _extraer_numeros_respuesta(texto or ""):
        if any(_numero_respaldado(numero, decimales, [p]) for p in prohibidos):
            motivos.append(f"cifra del resultado esperado: {numero:g}")
    for t in _textos_prohibidos(caso):
        if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", texto or "", re.IGNORECASE):
            motivos.append(f"valor esperado: {t}")
    comunes = _ngramas(_tokens_sql(texto), NGRAMA_FUGA_SQL) & _ngramas(_tokens_sql(caso["sql_referencia"]), NGRAMA_FUGA_SQL)
    if comunes:
        motivos.append(f"fragmento del SQL de referencia: {' '.join(sorted(comunes)[0])}")
    return motivos


def _resumen_resultado(ejec: dict) -> str:
    if not ejec["ok"]:
        return f"no se pudo ejecutar ({ejec['etapa']}: {ejec['error']})"
    filas = ejec["filas"]
    if not filas:
        return "0 filas"
    lineas = [f"{len(filas)} fila(s); columnas: {', '.join(ejec['columnas'])}"]
    lineas += [" | ".join("NULL" if v is None else str(v) for v in f) for f in filas[:MAX_FILAS_RESUMEN]]
    if len(filas) > MAX_FILAS_RESUMEN:
        lineas.append(f"... ({len(filas) - MAX_FILAS_RESUMEN} filas más)")
    return "\n".join(lineas)


def retro_llm(juez_client: OllamaClient, caso: dict, ejec: dict, diag: dict, nivel: int, seed: int,
              keep_alive: str | None) -> dict:
    """Pista redactada por el modelo juez (temperatura 0). Pasa por detectar_fuga: si la pista
    revela algo se regenera una vez; si vuelve a fallar, se usa la plantilla."""
    base = (
        f"Pregunta: {caso['pregunta']}\n\n"
        f"Consulta del junior:\n{ejec.get('sql') or '(ninguna)'}\n\n"
        f"Resumen de su resultado: {_resumen_resultado(ejec)}\n\n"
        f"Diagnóstico automático: {json.dumps(diag, ensure_ascii=False)}\n\n"
        f"Dificultades conocidas de esta pregunta (para ti): {json.dumps(caso['dificultades'], ensure_ascii=False)}\n\n"
        f"Consulta de referencia correcta (SOLO para ti, no la reveles):\n{caso['sql_referencia']}\n\n"
        f"{_INSTRUCCION_NIVEL[nivel]}"
    )
    registro = {"modo": "llm", "nivel": nivel, "fugas_bloqueadas": 0, "motivos_fuga": [], "fallback_plantilla": False,
                "segundos": 0.0, "load_duration_s": 0.0}
    prompt = base
    for _ in range(2):
        t0 = time.perf_counter()
        r = juez_client.generate_detallado(prompt, system=_SISTEMA_PISTA, num_predict=NUM_PREDICT_PISTA,
                                           temperature=0, seed=seed, keep_alive=keep_alive)
        registro["segundos"] += time.perf_counter() - t0
        registro["load_duration_s"] += (r.get("load_duration") or 0) / 1e9
        texto = r["response"]
        motivos = detectar_fuga(texto, caso)
        if not motivos:
            return {**registro, "texto": texto}
        registro["fugas_bloqueadas"] += 1
        registro["motivos_fuga"].append(motivos)
        prompt = base + ("\n\nTu pista anterior fue RECHAZADA porque revelaba la respuesta. Escribe otra sin "
                         "ninguna cifra, sin valores del resultado y sin fragmentos de SQL.")
    texto = retro_plantilla(diag, nivel)
    return {**registro, "texto": texto, "fallback_plantilla": True}


def retroalimentar(modo: str, caso: dict, ejec: dict, diag: dict, intento: int, juez_client: OllamaClient | None,
                   seed: int, keep_alive: str | None, pistas_v2: bool = False, reparacion: str | None = None) -> dict:
    """`pistas_v2` (ronda 2, D-37): se empieza en el nivel de concepto (sin el nivel 1 vago) y,
    con pistas LLM, el diagnóstico determinista (mensaje real del validador) va siempre primero.
    `reparacion`: texto de reparar_con_esquema(), que se añade y pasa por el mismo filtro."""
    nivel = min(intento + 1, 3) if pistas_v2 else nivel_pista(intento)
    if modo == "llm":
        r = retro_llm(juez_client, caso, ejec, diag, nivel, seed, keep_alive)
        if pistas_v2:
            r["texto"] = f"{retro_plantilla(diag, nivel)} Revisor: {r['texto']}"
    elif modo == "plantilla":
        r = {"modo": "plantilla", "nivel": nivel, "fugas_bloqueadas": 0, "motivos_fuga": [], "fallback_plantilla": False,
             "segundos": 0.0, "load_duration_s": 0.0, "texto": retro_plantilla(diag, nivel)}
    else:
        raise ValueError(f"modo de retroalimentación desconocido: {modo!r}")
    r["reparacion"] = None
    if reparacion:
        if detectar_fuga(reparacion, caso):
            r["fugas_bloqueadas"] += 1
            r["motivos_fuga"].append(detectar_fuga(reparacion, caso))
        else:
            r["texto"] = f"{r['texto']} {reparacion}"
            r["reparacion"] = reparacion
    # Última barrera: NADA que revele la respuesta llega al candidato, venga de donde venga.
    motivos = detectar_fuga(r["texto"], caso)
    if motivos:
        r["fugas_bloqueadas"] += 1
        r["motivos_fuga"].append(motivos)
        r["texto"] = "La consulta anterior no responde correctamente la pregunta. " + f"Revisa con cuidado: {CONCEPTOS_REVISION}"
    return r


# --- Ronda 2 (D-37): anti-repetición y reparación con el esquema REAL (sin oráculo) ---

_NO_ALIAS = {"where", "join", "left", "right", "inner", "outer", "cross", "full", "natural", "on", "using", "group",
             "order", "limit", "having", "union", "except", "intersect", "window"}
_RE_IDENT = re.compile(r"[a-z_][a-z0-9_]*$")


def normalizar_sql(sql: str) -> str:
    """Forma canónica para detectar SQL repetido: minúsculas, sin espacios ni ';' final, alias de
    tabla sustituidos por el nombre de la tabla y alias de columna (AS x) anonimizados."""
    toks = _tokens_sql((sql or "").strip().rstrip(";"))
    alias, quitar = {}, set()
    for i, t in enumerate(toks[:-1]):
        if t in ("from", "join") and _RE_IDENT.match(toks[i + 1]):
            j = i + 2
            con_as = j < len(toks) and toks[j] == "as"
            j += con_as
            if j < len(toks) and _RE_IDENT.match(toks[j]) and toks[j] not in _NO_ALIAS:
                alias[toks[j]] = toks[i + 1]
                quitar |= {j, j - 1} if con_as else {j}
    salida = []
    for k, t in enumerate(toks):
        if k in quitar:
            continue
        if k > 0 and toks[k - 1] == "as" and k - 1 not in quitar and _RE_IDENT.match(t) and t not in alias:
            salida.append("_alias")
        else:
            salida.append(alias.get(t, t))
    return " ".join(salida)


def _objetos_del_sql(sql: str, esquema: dict[str, set[str]]) -> list[str]:
    return list(dict.fromkeys(t.lower() for t in re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)", sql or "", re.I)
                              if t.lower() in esquema))


def _ruta_por_tablas_base(origen: str, columna: str, esquema: dict[str, set[str]]) -> str | None:
    """Camino más corto (BFS por columnas de unión) desde `origen` hasta una TABLA BASE que tiene
    `columna`. Las tablas intermedias son siempre tablas base."""
    from llm.schema_context import COLUMNAS_UNION

    def vecinos(t):
        for otro, cols in esquema.items():
            if otro == t or otro.startswith("vw_"):
                continue
            comunes = [c for c in COLUMNAS_UNION if c in esquema[t] and c in cols]
            if comunes:
                yield otro, comunes[0]

    if origen not in esquema:
        return None
    visitados, cola = {origen}, [(origen, [])]
    while cola:
        nodo, camino = cola.pop(0)
        if camino and columna in esquema[nodo]:
            pasos = [origen] + [f"{t} (por {k})" for t, k in camino]
            return " → ".join(pasos)
        for otro, llave in vecinos(nodo):
            if otro not in visitados:
                visitados.add(otro)
                cola.append((otro, camino + [(otro, llave)]))
    return None


def reparar_con_esquema(ejec: dict) -> str | None:
    """Si el validador o SQLite rechazaron una columna o tabla: mensaje real, columnas REALES
    (PRAGMA de la base) del objeto implicado y ruta por tablas base. No usa el oráculo."""
    from llm.schema_context import get_esquema_real

    if ejec.get("ok") or ejec.get("etapa") not in ("validacion", "ejecucion"):
        return None
    esquema = get_esquema_real()
    error = ejec.get("error") or ""
    faltantes: list[tuple[str | None, str]] = []
    for d in ejec.get("detalles") or []:
        if d.get("tipo") == "columna":
            faltantes.append((d["tabla"], d["columna"]))
    m = re.search(r"no such column: ([\w.]+)", error)
    if m:
        faltantes.append((None, m.group(1).split(".")[-1].lower()))
    tablas_malas = [d["nombre"] for d in ejec.get("detalles") or [] if d.get("tipo") == "tabla"]
    m = re.search(r"no such table: (\w+)", error)
    if m:
        tablas_malas.append(m.group(1).lower())
    if not faltantes and not tablas_malas:
        return None

    partes = ["Reparación con el esquema real:"]
    objetos = _objetos_del_sql(ejec.get("sql"), esquema)
    listados = set()
    for objeto, col in dict.fromkeys(faltantes):
        implicados = [objeto] if objeto else objetos
        for o in implicados:
            if o not in listados:
                listados.add(o)
                partes.append(f"columnas reales de {o}: {', '.join(sorted(esquema[o]))}.")
        bases = sorted(t for t, cols in esquema.items() if col in cols and not t.startswith("vw_"))
        vistas = sorted(t for t, cols in esquema.items() if col in cols and t.startswith("vw_"))
        if bases or vistas:
            partes.append(f"La columna {col} existe en las tablas {', '.join(bases) or '(ninguna)'}"
                          f"{' y en las vistas ' + ', '.join(vistas) if vistas else ''}.")
            for o in implicados:
                ruta = _ruta_por_tablas_base(o, col, esquema)
                if ruta:
                    partes.append(f"Ruta por tablas base para llegar a {col} desde {o}: {ruta}.")
        else:
            partes.append(f"La columna {col} no existe en ninguna tabla ni vista; búscala con otro nombre.")
    for t in dict.fromkeys(tablas_malas):
        partes.append(f"{t} no existe. Tablas y vistas reales: {', '.join(sorted(esquema))}.")
    return " ".join(partes)


# --- 5. Prompt del candidato y ciclo completo ---

def prompt_candidato(pregunta: str, anterior: dict | None, pistas: list[str], modo_edicion: bool = False) -> str:
    """Lo ÚNICO que ve el candidato además del esquema: pregunta, su SQL anterior, el resumen de
    su propio resultado y las pistas acumuladas (ya filtradas). `modo_edicion` (ronda 2, D-37) pide
    corregir el SQL anterior cambiando solo lo necesario en vez de generar uno nuevo."""
    partes = [f"Pregunta: {pregunta}"]
    if anterior is not None and modo_edicion:
        partes.append(f"Este SQL tiene un problema. Corrígelo cambiando SOLO lo necesario:\n```sql\n{anterior.get('sql') or ''}\n```")
        partes.append(f"Qué pasó al ejecutarlo: {_resumen_resultado(anterior)}")
        partes.append("Indicaciones del revisor:\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(pistas, 1)))
        partes.append("Devuelve el SQL corregido completo.")
    elif anterior is not None:
        partes.append(f"Tu consulta anterior:\n```sql\n{anterior.get('sql') or ''}\n```")
        partes.append(f"Resumen de su resultado: {_resumen_resultado(anterior)}")
        partes.append("Retroalimentación de un revisor:\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(pistas, 1)))
        partes.append("Genera una consulta corregida.")
    partes.append('Responde SOLO en JSON con la forma {"sql": "<consulta SQL>"}.')
    return "\n\n".join(partes)


def extraer_sql_json(texto: str) -> str:
    from llm.text_to_sql import extract_sql

    try:
        datos = json.loads(texto)
        sql = datos.get("sql", "") if isinstance(datos, dict) else ""
    except json.JSONDecodeError:
        m = re.search(r'"sql"\s*:\s*"((?:[^"\\]|\\.)*)"', texto or "", re.S)
        sql = json.loads(f'"{m.group(1)}"') if m else texto
    return extract_sql(sql or "")


_TOKENS_SYSTEM: dict[tuple, int] = {}


def tokens_system(client: OllamaClient, system: str, keep_alive: str | None = None) -> int:
    clave = (client.model, client.num_ctx, hash(system))
    if clave not in _TOKENS_SYSTEM:
        _TOKENS_SYSTEM[clave] = client.contar_tokens(system, keep_alive=keep_alive)
    return _TOKENS_SYSTEM[clave]


def evaluar_sintesis(client: OllamaClient, caso: dict, ejec: dict) -> dict:
    """Síntesis en lenguaje natural del último resultado + chequeo de 'texto confiable' existente +
    cifras clave de respuesta_nl_referencia presentes en el texto."""
    from llm.text_to_sql import (
        _extraer_numeros_respuesta, _numero_respaldado, _respuesta_respaldada_por_datos, sintetizar_respuesta,
    )

    filas = [tuple(f) for f in ejec["filas"]]
    t0 = time.perf_counter()
    texto = sintetizar_respuesta(client, caso["pregunta"], ejec["sql"], ejec["columnas"], filas, len(filas))
    escritos = _extraer_numeros_respuesta(texto)
    presentes = [c for c in caso.get("cifras_clave_nl", [])
                 if any(_numero_respaldado(n, d, [float(c["valor"])]) for n, d in escritos)]
    return {"texto": texto, "texto_confiable": _respuesta_respaldada_por_datos(texto, filas),
            # Ronda 2 (lección 5): los umbrales que ya vienen en la pregunta no son cifras inventadas.
            "texto_confiable_con_umbrales": _respuesta_respaldada_por_datos(
                texto, filas, numeros_extra=_numeros_en(caso["pregunta"])),
            "cifras_clave": len(caso.get("cifras_clave_nl", [])), "cifras_clave_presentes": len(presentes),
            "segundos": time.perf_counter() - t0}


def resolver_con_juez(
    caso: dict,
    candidato: OllamaClient,
    *,
    esquema: str = "compacto",
    max_iter: int = 5,
    temperatura: float = 0.0,
    seed: int = 42,
    feedback: str = "plantilla",
    juez_client: OllamaClient | None = None,
    keep_alive: str | None = "30m",
    sintetizar: bool = True,
    al_intento: Callable[[dict], None] | None = None,
    reintento_temp: float | None = None,
    max_remuestreos: int = 3,
    reparar_esquema: bool = False,
    modo_edicion: bool = False,
    pistas_v2: bool = False,
) -> dict:
    """Ciclo generar -> ejecutar -> veredicto determinista -> diagnóstico -> pista, hasta acertar o
    agotar max_iter. Devuelve el registro completo del caso (un dict por intento).

    Ronda 2 (D-37), todo apagado por defecto (con los valores por defecto el ciclo es el de la ronda 1):
      - reintento_temp: los intentos 2+ usan esa temperatura y la semilla seed + intento - 1; si el SQL
        normalizado ya se probó en este caso, se vuelve a muestrear (hasta max_remuestreos) sin gastar intento.
      - reparar_esquema: añade a la pista las columnas reales y la ruta por tablas base (reparar_con_esquema).
      - modo_edicion: el reintento pide corregir el SQL anterior en vez de generar uno nuevo.
      - pistas_v2: empieza en el nivel de concepto, con el diagnóstico determinista primero."""
    from llm.schema_context import get_schema_context
    from llm.text_to_sql import SQL_SYSTEM_PROMPT_TEMPLATE

    system = SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema_context(esquema))
    tok_system = tokens_system(candidato, system, keep_alive)
    juez_client = juez_client or candidato
    intentos, pistas, anterior, probados = [], [], None, set()
    for n in range(1, max_iter + 1):
        prompt = prompt_candidato(caso["pregunta"], anterior, pistas, modo_edicion=modo_edicion)
        antirrepeticion = reintento_temp is not None and n > 1
        temp_n = reintento_temp if antirrepeticion else temperatura
        seed_n = seed + n - 1 if antirrepeticion else seed
        t0 = time.perf_counter()
        try:
            remuestreos = 0
            while True:
                r = candidato.generate_detallado(prompt, system=system, num_predict=NUM_PREDICT_CANDIDATO,
                                                 temperature=temp_n, seed=seed_n + 1000 * remuestreos,
                                                 formato=FORMATO_SQL_JSON, keep_alive=keep_alive,
                                                 tokens_system=tok_system)
                normal = normalizar_sql(extraer_sql_json(r["response"]))
                if not antirrepeticion or normal not in probados or remuestreos >= max_remuestreos:
                    break
                remuestreos += 1
        except ContextoInsuficienteError as exc:
            # No se sigue con un prompt que Ollama recortaría: el caso termina aquí como fallo.
            registro = {"caso": caso["id"], "intento": n, "modelo": candidato.model, "esquema": esquema,
                        "error_contexto": str(exc), "veredicto": {"correcto": False, "comprobaciones": []},
                        "segundos_generacion": time.perf_counter() - t0,
                        "ejecucion": {"ok": False, "etapa": "contexto", "error": str(exc), "columnas": [], "segundos": 0.0},
                        "tokens": {"system": tok_system, "prompt_eval_count": None, "eval_count": None, "estimados": None},
                        "load_duration_s": 0.0}
            intentos.append(registro)
            if al_intento:
                al_intento(registro)
            break
        seg_gen = time.perf_counter() - t0
        sql = extraer_sql_json(r["response"])
        ejec = ejecutar_sql_candidato(sql)
        ver = veredicto_caso(caso, ejec["filas"]) if ejec["ok"] else {"correcto": False, "comprobaciones": []}
        registro = {
            "caso": caso["id"], "intento": n, "modelo": candidato.model, "esquema": esquema, "temperatura": temperatura,
            "seed": seed, "num_ctx": candidato.num_ctx, "feedback": feedback if max_iter > 1 else None,
            "prompt_candidato": prompt, "respuesta_cruda": r["response"], "sql": ejec["sql"],
            "ejecucion": {k: ejec[k] for k in ("ok", "etapa", "error", "columnas", "segundos")},
            "filas_obtenidas": len(ejec["filas"]), "muestra_filas": ejec["filas"][:MAX_FILAS_RESUMEN],
            "veredicto": ver, "segundos_generacion": seg_gen,
            "tokens": {"system": tok_system, "prompt_eval_count": r.get("prompt_eval_count"),
                       "eval_count": r.get("eval_count"), "estimados": r.get("tokens_prompt_estimados")},
            "load_duration_s": (r.get("load_duration") or 0) / 1e9,
            "temperatura_usada": temp_n, "seed_usada": seed_n, "remuestreos": remuestreos,
            "sql_repetido": n > 1 and normal in probados,
        }
        probados.add(normal)
        if not ver["correcto"] and n < max_iter:
            diag = diagnosticar_intento(caso, ejec)
            reparacion = reparar_con_esquema(ejec) if reparar_esquema else None
            retro = retroalimentar(feedback, caso, ejec, diag, n, juez_client, seed, keep_alive,
                                   pistas_v2=pistas_v2, reparacion=reparacion)
            registro["diagnostico"] = diag
            registro["retroalimentacion"] = retro
            pistas.append(retro["texto"])
        intentos.append(registro)
        if al_intento:
            al_intento(registro)
        anterior = ejec
        if ver["correcto"]:
            break
    ultimo = intentos[-1]
    sintesis = None
    if sintetizar and anterior is not None and anterior["ok"] and anterior["filas"]:
        sintesis = evaluar_sintesis(candidato, caso, anterior)
    return {
        "caso": caso["id"], "necesidad": caso["necesidad"], "pregunta": caso["pregunta"],
        "modelo": candidato.model, "juez_modelo": juez_client.model if feedback == "llm" else None,
        "esquema": esquema, "temperatura": temperatura, "seed": seed, "num_ctx": candidato.num_ctx,
        "feedback": feedback, "max_iter": max_iter,
        "ronda2": {"reintento_temp": reintento_temp, "reparar_esquema": reparar_esquema,
                   "modo_edicion": modo_edicion, "pistas_v2": pistas_v2},
        "acierto_1": intentos[0]["veredicto"]["correcto"], "acierto_final": ultimo["veredicto"]["correcto"],
        "intentos_usados": len(intentos),
        "fugas_bloqueadas": sum(i.get("retroalimentacion", {}).get("fugas_bloqueadas", 0) for i in intentos),
        "sintesis": sintesis, "intentos": intentos,
    }
