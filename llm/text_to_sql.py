"""
Pipeline Text-to-SQL: pregunta en español -> SQL generado por Ollama -> validación
-> ejecución de solo lectura contra SQLite (db/olist.db) -> respuesta en lenguaje
natural.

Flujo (ver docs/DEPLOY.md para cómo levantarlo):
    0. Antes de cualquier llamada al modelo, `llm/sql_templates.py` detecta por
       REGLAS (palabras clave) los patrones donde el LLM de 8B falla de forma
       sistemática -- concentración/Pareto y series mensuales -- y, si aplica, se
       ejecuta una plantilla SQL fija en vez de generación libre.
    1. `clasificar_pregunta` decide si la pregunta necesita una sola consulta
       (la mayoría de los casos) o si conviene descomponerla en 2-4
       sub-preguntas simples (preguntas "abiertas" tipo panorama/comparación).
    2. Por cada (sub-)pregunta: la pregunta + el esquema compacto
       (llm/schema_context.py) se inyectan en un prompt de sistema que le pide
       al modelo generar SOLO SQL.
    3. El SQL generado se valida en dos niveles (llm/sql_guard.py):
       - Seguridad (`validate_select_only`): solo SELECT, una sola sentencia,
         sin palabras clave destructivas. Si falla, se rechaza de inmediato,
         SIN reintento.
       - Calidad (`check_literales_placeholder`, `check_tablas_conocidas`,
         `check_columnas_existentes`, `check_dominios_join`): literales
         inventados, tablas/vistas o columnas inexistentes, joins entre llaves
         de dominios distintos. Antes de estos checks se renombran los alias
         que son palabras reservadas de SQLite (`sanitizar_alias_reservados`).
         Si tras el reintento el SQL sigue roto, se intenta una plantilla de
         respaldo sobre vistas precalculadas (`plantilla_fallback`). Junto con errores
         de ejecución de SQLite y con "0 filas", comparten UN solo reintento:
         si el problema persiste tras ese reintento, se responde con un
         mensaje fijo (nunca se afirma que el dato "no existe").
    4. Se ejecuta contra la base de datos en una conexión SQLite abierta en
       modo solo-lectura (file:...?mode=ro), como defensa adicional.
    5. Con el resultado (truncado) se le pide al modelo una síntesis breve en
       español (o una síntesis integradora si hubo varias sub-preguntas); si
       ese paso falla, se devuelve una respuesta tabular simple en su lugar.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)

from db.olist_database import DATABASE_URL
from llm.ollama_client import OllamaClient, OllamaError
from llm.schema_context import get_esquema_real, get_known_names, get_schema_context
from llm.sql_guard import (
    SQLQualityError,
    SQLValidationError,
    check_columnas_existentes,
    check_dominios_join,
    check_literales_placeholder,
    check_tablas_conocidas,
    sanitizar_alias_reservados,
    validate_select_only,
)
from llm.sql_templates import Plantilla, detectar_plantillas, plantilla_fallback

MAX_FILAS_EJECUTADAS = 500  # límite duro de filas leídas de la base de datos
# Límite de tiempo de ejecución del SQL generado. La consulta de referencia más
# lenta del oráculo tarda ~10 s; 60 s deja margen (docs/FASE_03.md).
LIMITE_EJECUCION_S = float(os.environ.get("TEXT2SQL_LIMITE_EJECUCION_S", "60"))
MAX_FILAS_PARA_SINTESIS = 50  # filas mostradas al modelo al sintetizar una consulta simple
MAX_FILAS_POR_SUBCONSULTA = 15  # filas por sub-tabla en la síntesis integradora (pregunta abierta)

SQL_SYSTEM_PROMPT_TEMPLATE = """Eres un generador de consultas SQL para SQLite. \
Tu única tarea es traducir la pregunta del usuario (en español) a UNA consulta SQL de \
solo lectura (SELECT) usando exclusivamente las tablas y columnas del siguiente esquema.

{schema}

Reglas estrictas:
- Responde ÚNICAMENTE con la consulta SQL dentro de un bloque ```sql ... ```. Nada de explicaciones.
- Usa solo tablas/columnas que existan en el esquema de arriba. No inventes nombres.
- Nunca uses valores de ejemplo/placeholder inventados (ej. 'categoria1'); usa datos reales o revisa las notas.
- Nunca generes INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA ni ninguna sentencia que no sea SELECT.
- Si la pregunta es ambigua, elige la interpretación más razonable y genera igual una consulta.
"""

SYNTHESIS_SYSTEM_PROMPT = """Eres un analista de datos que le habla directamente al dueño de un \
negocio de e-commerce (Olist). Se te da una pregunta en español, la consulta SQL que se ejecutó \
(uso interno, no la menciones) y el resultado obtenido. Responde la pregunta en español siguiendo \
TODAS estas reglas:
- Tono cercano y natural, como si le hablaras a la persona dueña del negocio, no a un técnico.
- Nunca menciones SQL, consultas, tablas ni nombres de columnas. Habla solo del negocio.
- Formatea los números: miles con coma (ej. 12,450), montos en moneda como R$1,234.56, porcentajes con "%".
- Máximo 4-5 oraciones.
- Empieza por la conclusión/respuesta directa, y después el dato concreto que la respalda.
- Si el resultado está vacío, dilo explícitamente y con naturalidad, sin inventar una cifra.
- Prohibido citar cualquier cifra que no esté en el resultado que se te dio.
- Prohibido hacer operaciones aritméticas (sumas, promedios, restas, etc.) con las cifras del resultado; cita únicamente los valores tal cual aparecen en la tabla.
- Nunca traduzcas, parafrasees o generalices nombres de categoría u otros valores de texto que aparecen en el resultado -- usa el texto EXACTO tal cual viene en la tabla, letra por letra.
- Si el resultado tiene varias filas (hasta ~15), NO las repitas ni las listes una por una -- ya se muestran en una tabla aparte. Da solo una conclusión de 1-2 frases (ej. cuál es el top, el rango de valores, o el patrón general).
- No inventes explicaciones causales (el "por qué") que no estén sustentadas por los datos mostrados; repórtalo, no lo expliques."""

CLASIFICADOR_SYSTEM_PROMPT = """Analizas si una pregunta de negocio sobre una tienda en línea (Olist) \
se puede responder con UNA sola consulta SQL simple, o si en realidad tiene varias partes sobre TEMAS \
DE NEGOCIO CLARAMENTE DISTINTOS que conviene resolver por separado (ej. "compara ingresos con \
desempeño de entregas", o "dame un panorama de ventas Y de entregas Y de satisfacción de clientes").

La MAYORÍA de las preguntas se responden con una sola consulta, INCLUSO si mencionan dos datos (ej. \
"¿qué vendedor tiene más pedidos y cuántos?" es UNA sola consulta: una columna trae el vendedor, otra el \
número de pedidos -- es el mismo tema). Solo divide cuando son temas de negocio distintos que normalmente saldrían \
de tablas o vistas distintas. Si tienes duda, NO dividas.

Si la pregunta es simple (una sola consulta basta), tu respuesta completa debe ser EXACTAMENTE la \
palabra UNA, sin nada más, ni siquiera puntuación.

Si la pregunta tiene 2 a 4 partes sobre temas claramente distintos, responde solo con cada sub-pregunta \
simple en su propia línea (sin numerarlas, sin la palabra UNA, sin explicaciones). Máximo 4 líneas.

Ejemplo de pregunta simple (menciona dos datos, pero es un solo tema -> NO se divide):
Pregunta: ¿Qué vendedor tiene más pedidos y cuántos?
Respuesta:
UNA

Ejemplo de pregunta simple (compara dos grupos DENTRO DEL MISMO tema -> NO se divide, se resuelve \
agrupando/con CASE en una sola consulta):
Pregunta: ¿Los pedidos pagados en varias cuotas tienen un valor más alto que los pagados en una sola?
Respuesta:
UNA

Ejemplo de pregunta simple (busca un umbral/punto de quiebre, pero es UN solo tema -> NO se divide):
Pregunta: ¿Desde cuántos días de demora empiezan a bajar las reseñas?
Respuesta:
UNA

Ejemplo de pregunta que sí se divide (dos temas de negocio distintos):
Pregunta: Compara los ingresos por categoría con el desempeño de entregas
Respuesta:
¿Cuáles son los ingresos por categoría de producto?
¿Cómo es el desempeño de entregas (retrasos y calificación)?"""

MENSAJE_SIN_RESULTADOS = (
    "Ejecuté la consulta correctamente, pero no encontré registros para ese filtro. Los datos de "
    "Olist cubren pedidos de 2016 a 2018 -- si preguntaste por otro periodo o un valor fuera de ese "
    "rango, por eso no aparece nada. ¿Quieres intentar con otro filtro o periodo?"
)

MENSAJE_PROBLEMA_TRAS_REINTENTO = (
    "No logré armar una consulta que funcionara bien para responder eso; puede que la lógica no "
    "haya sido la correcta. ¿Podrías reformular la pregunta?"
)

MENSAJE_RESUMEN_NO_CONFIABLE = "No pude redactar un resumen confiable; revisa la tabla de resultados."

_NUMERO_RESPUESTA_RE = re.compile(r"-?\d[\d.,]*\d|-?\d")


def _extraer_numeros_respuesta(respuesta: str) -> list[tuple[float, int]]:
    """Extrae los números que escribió el modelo, junto con la cantidad de
    decimales CON LA QUE LOS ESCRIBIÓ (para comparar contra los datos
    redondeando a esa misma precisión, no con tolerancia porcentual)."""
    resultados = []
    for m in _NUMERO_RESPUESTA_RE.finditer(respuesta):
        crudo = m.group(0)
        limpio = crudo
        if "," in limpio and "." in limpio:
            if limpio.rfind(",") > limpio.rfind("."):
                limpio = limpio.replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
            else:
                limpio = limpio.replace(",", "")  # 1,234.56 -> 1234.56
        elif "," in limpio:
            partes = limpio.split(",")
            if len(partes[-1]) == 3:
                limpio = limpio.replace(",", "")  # 1,234 -> 1234 (miles)
            else:
                limpio = limpio.replace(",", ".")  # 12,5 -> 12.5 (decimal)
        try:
            valor = float(limpio)
        except ValueError:
            continue
        decimales = len(limpio.split(".", 1)[1]) if "." in limpio else 0
        resultados.append((valor, decimales))
    return resultados


def _numeros_de_filas(filas: list[tuple]) -> list[float]:
    """Números presentes en las celdas del resultado -- incluye también los
    que vienen embebidos en celdas de texto (ej. la etiqueta '8-14' de
    vw_retraso_por_rango.rango_retraso contiene los números 8 y 14, que son
    datos reales tan válidos como los de una columna numérica)."""
    numeros = []
    for fila in filas:
        for v in fila:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                numeros.append(float(v))
            elif isinstance(v, str):
                numeros.extend(float(m.group(0)) for m in re.finditer(r"\d+(?:\.\d+)?", v))
    return numeros


def _numero_respaldado(numero: float, decimales: int, numeros_datos: list[float]) -> bool:
    objetivo = f"{numero:.{decimales}f}"
    for dato in numeros_datos:
        if f"{dato:.{decimales}f}" == objetivo:
            return True
        if f"{dato * 100:.{decimales}f}" == objetivo:  # forma porcentual de una fracción (0.7694 -> 76.94)
            return True
    return False


def _respuesta_respaldada_por_datos(respuesta: str, filas: list[tuple]) -> bool:
    """Todo número con decimales, y todo entero >= 10, debe corresponder
    (redondeando a la misma precisión con la que se escribió) a un valor real
    en `filas`. Los enteros < 10 se ignoran -- casi siempre son estructurales
    (rankings, "1-2 frases", etc.), no cifras de negocio."""
    numeros_datos = _numeros_de_filas(filas)
    for numero, decimales in _extraer_numeros_respuesta(respuesta):
        if decimales == 0 and abs(numero) < 10:
            continue
        if not _numero_respaldado(numero, decimales, numeros_datos):
            return False
    return True


def _log_resumen_no_confiable(pregunta: str, respuesta: str, filas: list[tuple]) -> None:
    _logger.warning(
        "MENSAJE_RESUMEN_NO_CONFIABLE disparado | pregunta=%r | respuesta_descartada=%r | filas=%r",
        pregunta, respuesta, filas[:20],
    )


@dataclass
class Text2SQLResult:
    pregunta: str
    sql: str | None = None
    columnas: list[str] = field(default_factory=list)
    filas: list[tuple] = field(default_factory=list)
    total_filas: int = 0
    respuesta: str | None = None
    error: str | None = None
    intentos: int = 0
    sub_consultas: list[dict] = field(default_factory=list)  # solo si la pregunta se descompuso
    origen: str | None = None  # "llm", "plantilla:<nombre>" o "fallback_vista:<nombre>" (consulta simple)
    detalle_error: str | None = None  # por qué se descartó el SQL del LLM (aunque luego se respondiera con un fallback)
    # Un dict por intento: {"intento", "sql", "tipo", "detalle"}; tipo en TIPOS_FALLO (ver clasificar_excepcion).
    intentos_detalle: list[dict] = field(default_factory=list)


# Clasificación de cada intento (Fase 2). "ok" = el SQL corrió y devolvió filas;
# si además es correcto lo decide el árbitro de la evaluación, que puede
# reclasificar un "ok" como "semantico".
TIPOS_FALLO = ("ok", "ejecucion", "semantico", "seguridad", "infra")


def clasificar_excepcion(exc: Exception) -> str:
    """ejecucion = el SQL no corre (o no correría); semantico = corre pero
    responde otra cosa; seguridad = no es una lectura permitida; infra = el
    modelo/servidor no respondió."""
    if isinstance(exc, OllamaError):
        return "infra"
    if isinstance(exc, SQLValidationError):
        # Texto en lugar de SQL (p. ej. una negativa del modelo) no es un intento inseguro.
        return "ejecucion" if exc.motivo == "no_es_sql" else "seguridad"
    if isinstance(exc, SQLQualityError):
        return "ejecucion" if exc.motivo in ("tabla_inexistente", "columna_inexistente") else "semantico"
    if isinstance(exc, sqlite3.Error):
        return "ejecucion"
    raise TypeError(f"excepción no clasificable: {type(exc).__name__}")


def _sqlite_path_from_url(database_url: str) -> str:
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError(
            "El ejecutor de solo-lectura actual soporta SQLite. Para PostgreSQL, "
            "adapta execute_readonly() en llm/text_to_sql.py usando 'SET TRANSACTION READ ONLY'."
        )
    return database_url.replace("sqlite:///", "", 1)


def execute_readonly(
    sql: str,
    database_url: str = DATABASE_URL,
    max_rows: int = MAX_FILAS_EJECUTADAS,
    limite_s: float | None = LIMITE_EJECUCION_S,
):
    """Ejecuta `sql` (ya validado como SELECT) contra SQLite en modo estrictamente solo-lectura.

    `limite_s` corta la consulta desde dentro de SQLite (progress handler) si
    tarda más de esos segundos: un JOIN sin condición generado por el modelo
    puede correr indefinidamente. `None` = sin límite (SQL de referencia)."""
    db_path = _sqlite_path_from_url(database_url)
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    if limite_s:
        fin = time.monotonic() + limite_s
        conn.set_progress_handler(lambda: 1 if time.monotonic() > fin else 0, 100_000)
    try:
        cursor = conn.execute(sql)
        columnas = [d[0] for d in cursor.description] if cursor.description else []
        filas = cursor.fetchmany(max_rows)
        return columnas, filas
    except sqlite3.OperationalError as exc:
        if limite_s and "interrupted" in str(exc):
            raise sqlite3.OperationalError(
                f"la consulta superó el límite de {limite_s:g} s de ejecución "
                "(revisa si hay un JOIN sin condición o un producto cartesiano)"
            ) from exc
        raise
    finally:
        conn.close()


def extract_sql(texto_modelo: str) -> str:
    """Extrae el SQL de un bloque ```sql ... ``` (o ``` ... ```). Si el modelo
    dejó el bloque sin cerrar (pasa con modelos pequeños al truncarse la
    generación), igual limpia las marcas de fence sueltas en vez de fallar."""
    texto = texto_modelo.strip()
    match = re.search(r"```(?:sql)?\s*(.*?)```", texto, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Fence sin cerrar: quita '```sql' / '```' inicial y '```' final si existen.
    texto = re.sub(r"^```(?:sql)?\s*", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"```\s*$", "", texto)
    return texto.strip()


def _formatear_filas_para_prompt(columnas: list[str], filas: list[tuple], limite: int = MAX_FILAS_PARA_SINTESIS) -> str:
    if not filas:
        return "(sin filas)"
    encabezado = " | ".join(columnas)
    lineas = [encabezado, "-" * len(encabezado)]
    for fila in filas[:limite]:
        lineas.append(" | ".join("NULL" if v is None else str(v) for v in fila))
    if len(filas) > limite:
        lineas.append(f"... ({len(filas) - limite} filas adicionales no mostradas)")
    return "\n".join(lineas)


def generar_sql(
    client: OllamaClient,
    pregunta: str,
    schema_context: str,
    error_previo: str | None = None,
    sql_previo: str | None = None,
) -> str:
    system_prompt = SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=schema_context)
    prompt = f"Pregunta: {pregunta}"
    if error_previo and sql_previo:
        prompt += (
            f"\n\nYa intentaste responder con esta consulta:\n```sql\n{sql_previo}\n```"
            f"\nPero falló con este error: {error_previo}"
            f"\nGenera una nueva consulta SQL corregida que resuelva el problema."
        )
    respuesta = client.generate(prompt, system=system_prompt, num_predict=350)
    return extract_sql(respuesta)


def sintetizar_respuesta(
    client: OllamaClient, pregunta: str, sql: str, columnas: list[str], filas: list[tuple], total_filas: int,
    limite_filas: int | None = None,
) -> str:
    tabla = _formatear_filas_para_prompt(columnas, filas, limite=limite_filas or MAX_FILAS_PARA_SINTESIS)
    prompt = (
        f"Pregunta: {pregunta}\n\n"
        f"SQL ejecutado:\n{sql}\n\n"
        f"Resultado ({total_filas} fila(s) en total):\n{tabla}\n\n"
        f"Responde la pregunta en español basándote solo en estos datos."
    )
    try:
        return client.generate(prompt, system=SYNTHESIS_SYSTEM_PROMPT, num_predict=250).strip()
    except OllamaError:
        # Si el paso de síntesis falla (ej. timeout), no perdemos el resultado ya obtenido.
        return f"No se pudo generar una síntesis en lenguaje natural, pero aquí está el resultado:\n{tabla}"


def sintetizar_respuesta_integradora(client: OllamaClient, pregunta: str, sub_consultas: list[dict]) -> str:
    """Integra los resultados de varias sub-consultas (pregunta 'abierta') en
    una sola respuesta, con las mismas reglas de SYNTHESIS_SYSTEM_PROMPT."""
    bloques = []
    for i, sc in enumerate(sub_consultas, start=1):
        if sc.get("sql") is None:
            tabla = "(no se pudo obtener este dato)"
        else:
            tabla = _formatear_filas_para_prompt(
                sc["columnas"], sc["filas"], limite=sc.get("limite_sintesis") or MAX_FILAS_POR_SUBCONSULTA
            )
        bloques.append(f"Sub-pregunta {i}: {sc['pregunta']}\nResultado:\n{tabla}")

    prompt = (
        f"Pregunta original: {pregunta}\n\n"
        "Para responderla se dividió en varias partes. Estos son los resultados de cada parte:\n\n"
        + "\n\n".join(bloques)
        + "\n\nIntegra todo en una sola respuesta en español, basándote ÚNICAMENTE en estos datos. "
        "Si alguna parte aparece como '(no se pudo obtener este dato)', dilo con esa frase o una muy "
        "similar en tu respuesta -- nunca digas 'no puedo proporcionar información' ni otra negativa "
        "genérica -- en vez de omitir ese tema por completo."
    )
    try:
        return client.generate(prompt, system=SYNTHESIS_SYSTEM_PROMPT, num_predict=300).strip()
    except OllamaError:
        return "No se pudo generar una síntesis en lenguaje natural, pero se obtuvieron los datos de cada parte (ver detalle)."


def clasificar_pregunta(client: OllamaClient, pregunta: str) -> list[str] | None:
    """Decide si `pregunta` necesita descomponerse en 2-4 sub-preguntas
    simples. Devuelve `None` (caso mayoritario) si basta una sola consulta."""
    try:
        respuesta = client.generate(
            f"Pregunta: {pregunta}",
            system=CLASIFICADOR_SYSTEM_PROMPT,
            num_predict=150,
            temperature=0,
        )
    except OllamaError:
        return None  # si falla la clasificación, se trata como pregunta simple (más barato y seguro)

    lineas = [l.strip() for l in respuesta.strip().splitlines() if l.strip()]
    if not lineas or lineas[0].strip().upper() == "UNA":
        return None
    # Si el modelo mezcló los dos formatos (ej. "Compara X: UNA" en vez de una
    # sub-pregunta limpia), el resultado no es confiable -- por seguridad se
    # trata como pregunta simple en vez de pasar sub-preguntas mal formadas.
    if any("UNA" in l.upper() for l in lineas):
        return None
    return lineas[:4]


@dataclass
class _ResolucionSQL:
    sql: str | None = None
    columnas: list[str] = field(default_factory=list)
    filas: list[tuple] = field(default_factory=list)
    intentos: int = 0
    error_seguridad: str | None = None
    error_infra: str | None = None
    mensaje_fijo: str | None = None  # MENSAJE_SIN_RESULTADOS o MENSAJE_PROBLEMA_TRAS_REINTENTO
    origen: str = "llm"  # "llm", "plantilla:<nombre>" o "fallback_vista:<nombre>"
    error_detalle: str | None = None  # último problema del SQL del LLM (visible aunque no haya "error" de infraestructura)
    limite_sintesis: int | None = None  # filas que se le muestran al modelo al sintetizar (None = default)
    intentos_detalle: list[dict] = field(default_factory=list)  # ver Text2SQLResult.intentos_detalle


def _generar_y_ejecutar_llm(
    client: OllamaClient,
    pregunta: str,
    schema_context: str,
    nombres_conocidos: set[str],
    max_retries: int,
) -> _ResolucionSQL:
    """Corre generar_sql -> validar seguridad -> validar calidad -> ejecutar.

    La validación de SEGURIDAD (`validate_select_only`) se rechaza de
    inmediato, SIN reintento. `SQLQualityError` (literales placeholder o
    tabla/vista inexistente), `sqlite3.Error` (falla de ejecución), "0 filas",
    SQL vacío (el modelo no devolvió nada) y `OllamaError` al generar (timeout,
    conexión caída) comparten UN solo reintento unificado (`ya_reintento_por_problema`): la
    primera vez que ocurre cualquiera de las tres, se reintenta; la segunda,
    se corta con `mensaje_fijo` (que depende de qué pasó en ese último
    intento, no del historial).
    """
    resultado = _ResolucionSQL()
    esquema_real = get_esquema_real()
    sql_generado: str | None = None
    error_actual: str | None = None
    ya_reintento_por_problema = False

    def registrar(tipo: str, sql: str | None, detalle: str | None) -> None:
        resultado.intentos_detalle.append(
            {"intento": resultado.intentos, "sql": sql, "tipo": tipo, "detalle": detalle}
        )

    for intento in range(max_retries + 1):
        resultado.intentos = intento + 1
        try:
            sql_generado = generar_sql(
                client, pregunta, schema_context,
                error_previo=error_actual, sql_previo=sql_generado,
            )
        except OllamaError as exc:
            registrar(clasificar_excepcion(exc), None, str(exc))
            if not ya_reintento_por_problema and intento < max_retries:
                ya_reintento_por_problema = True
                error_actual = None  # no hay SQL previo que corregir: se repite el mismo prompt
                sql_generado = None
                continue
            resultado.error_infra = str(exc)
            resultado.error_detalle = str(exc)
            resultado.mensaje_fijo = MENSAJE_PROBLEMA_TRAS_REINTENTO
            return resultado

        if not sql_generado.strip():
            registrar("ejecucion", None, "El modelo no devolvió ninguna consulta SQL.")
            if not ya_reintento_por_problema and intento < max_retries:
                ya_reintento_por_problema = True
                error_actual = None
                sql_generado = None
                continue
            resultado.error_detalle = "El modelo no devolvió ninguna consulta SQL."
            resultado.mensaje_fijo = MENSAJE_PROBLEMA_TRAS_REINTENTO
            return resultado

        try:
            sql_validado = validate_select_only(sql_generado)
        except SQLValidationError as exc:
            registrar(clasificar_excepcion(exc), sql_generado, str(exc))
            resultado.sql = sql_generado
            resultado.error_seguridad = str(exc)
            return resultado

        # Alias reservados (ej. `order_reviews or`): se renombran ANTES de validar/ejecutar.
        sql_validado, renombres = sanitizar_alias_reservados(sql_validado)
        if renombres:
            _logger.info("Alias reservados renombrados en el SQL del LLM: %s", renombres)

        try:
            check_literales_placeholder(sql_validado)
            check_tablas_conocidas(sql_validado, nombres_conocidos)
            check_columnas_existentes(sql_validado, esquema_real)
            check_dominios_join(sql_validado)
            columnas, filas = execute_readonly(sql_validado)
        except (SQLQualityError, sqlite3.Error) as exc:
            error_actual = str(exc) if isinstance(exc, SQLQualityError) else f"Error de SQLite al ejecutar la consulta: {exc}"
            registrar(clasificar_excepcion(exc), sql_validado, error_actual)
            if not ya_reintento_por_problema and intento < max_retries:
                ya_reintento_por_problema = True
                sql_generado = sql_validado
                continue
            resultado.sql = sql_validado
            resultado.error_detalle = error_actual
            resultado.mensaje_fijo = MENSAJE_PROBLEMA_TRAS_REINTENTO
            return resultado

        if not filas:
            # Corre pero no devuelve nada: sospecha semántica (filtro o JOIN mal planteado).
            registrar("semantico", sql_validado, "La consulta se ejecutó sin errores pero no devolvió ninguna fila.")
            if not ya_reintento_por_problema and intento < max_retries:
                ya_reintento_por_problema = True
                error_actual = (
                    "La consulta se ejecutó sin errores pero no devolvió ninguna fila. Revisa si "
                    "el JOIN o el filtro está mal planteado (por ejemplo, saltarte la tabla orders "
                    "al relacionar customers con order_items); si aplica, usa directamente una de "
                    "las vistas del esquema. Recuerda también que los datos de Olist solo cubren "
                    "2016-2018. Genera una consulta corregida."
                )
                sql_generado = sql_validado
                continue
            resultado.sql = sql_validado
            resultado.columnas = columnas
            resultado.filas = filas
            resultado.mensaje_fijo = MENSAJE_SIN_RESULTADOS
            return resultado

        registrar("ok", sql_validado, None)
        resultado.sql = sql_validado
        resultado.columnas = columnas
        resultado.filas = filas
        return resultado

    return resultado


def _ejecutar_plantilla(plantilla: Plantilla, tipo: str) -> _ResolucionSQL | None:
    """Ejecuta una plantilla fija con los mismos validadores y la misma conexión
    solo-lectura que el SQL generado por el modelo. Devuelve None si la plantilla
    misma falla (bug de la plantilla, no del usuario): el pipeline sigue entonces
    con generación libre en vez de romperse."""
    try:
        sql = validate_select_only(plantilla.sql)
        check_tablas_conocidas(sql, get_known_names())
        check_columnas_existentes(sql, get_esquema_real())
        columnas, filas = execute_readonly(sql)
    except (SQLValidationError, SQLQualityError, sqlite3.Error) as exc:
        _logger.error("La plantilla %r falló y se ignora: %s", plantilla.nombre, exc)
        return None
    resultado = _ResolucionSQL(
        sql=sql, columnas=columnas, filas=filas, intentos=0,
        origen=f"{tipo}:{plantilla.nombre}", limite_sintesis=plantilla.limite_sintesis,
        intentos_detalle=[{"intento": 0, "sql": sql, "tipo": "ok" if filas else "semantico",
                           "detalle": f"{tipo}:{plantilla.nombre}"}],
    )
    if not filas:
        resultado.mensaje_fijo = MENSAJE_SIN_RESULTADOS
    return resultado


def _generar_y_ejecutar(
    client: OllamaClient,
    pregunta: str,
    schema_context: str,
    nombres_conocidos: set[str],
    max_retries: int,
    plantilla: Plantilla | None = None,
    usar_plantillas: bool = True,
) -> _ResolucionSQL:
    """Orden de resolución de una (sub-)pregunta:
    1. Plantilla fija si una regla reconoce el patrón (no se consulta al modelo).
    2. SQL generado por el LLM, con sanitización de alias + validación semántica.
    3. Si el LLM falló tras el reintento, plantilla de respaldo sobre vistas
       precalculadas (solo para preguntas de vendedores). Un rechazo de SEGURIDAD
       nunca cae a fallback.

    Con `usar_plantillas=False` se saltan los pasos 1 y 3 (solo LLM), para
    evaluar al modelo sin la ayuda de reglas fijas."""
    if not usar_plantillas:
        return _generar_y_ejecutar_llm(client, pregunta, schema_context, nombres_conocidos, max_retries)
    if plantilla is None:
        detectadas = detectar_plantillas(pregunta)
        plantilla = detectadas[0] if detectadas else None
    if plantilla is not None:
        resuelto = _ejecutar_plantilla(plantilla, "plantilla")
        if resuelto is not None:
            return resuelto

    resultado = _generar_y_ejecutar_llm(client, pregunta, schema_context, nombres_conocidos, max_retries)
    if resultado.mensaje_fijo == MENSAJE_PROBLEMA_TRAS_REINTENTO and not resultado.error_infra:
        respaldo = plantilla_fallback(pregunta)
        if respaldo is not None:
            _logger.warning(
                "SQL del LLM descartado (%s); se usa el respaldo %r. Pregunta=%r",
                resultado.error_detalle, respaldo.nombre, pregunta,
            )
            resuelto = _ejecutar_plantilla(respaldo, "fallback_vista")
            if resuelto is not None and resuelto.filas:
                resuelto.intentos = resultado.intentos
                resuelto.error_detalle = resultado.error_detalle
                resuelto.intentos_detalle = resultado.intentos_detalle + resuelto.intentos_detalle
                return resuelto
    return resultado


def _answer_open_question(
    pregunta: str,
    sub_preguntas: list[str],
    client: OllamaClient,
    schema_context: str,
    nombres_conocidos: set[str],
    max_retries: int,
    plantillas: list[Plantilla] | None = None,
    usar_plantillas: bool = True,
) -> Text2SQLResult:
    """`plantillas` (opcional, mismo largo que `sub_preguntas`): plantilla ya
    decidida por reglas para cada sub-pregunta (pregunta compuesta detectada
    sin ayuda del modelo)."""
    resultado = Text2SQLResult(pregunta=pregunta)
    sub_consultas: list[dict] = []
    sqls: list[str] = []
    intentos_totales = 0

    for i, sub_pregunta in enumerate(sub_preguntas):
        plantilla = plantillas[i] if plantillas else None
        r = _generar_y_ejecutar(
            client, sub_pregunta, schema_context, nombres_conocidos, max_retries,
            plantilla=plantilla, usar_plantillas=usar_plantillas,
        )
        intentos_totales += r.intentos
        if r.sql:
            sqls.append(r.sql)
        sub_consultas.append({
            "pregunta": sub_pregunta,
            "sql": r.sql,
            "columnas": r.columnas,
            "filas": r.filas,
            # El motivo del fallo se expone también cuando el resultado quedó vacío
            # (antes se perdía y el JSON mostraba error=null con 0 filas).
            "error": r.error_infra or r.error_seguridad or (None if r.filas else r.error_detalle),
            "origen": r.origen,
            "rechazo_llm": r.error_detalle if r.origen != "llm" else None,
            "limite_sintesis": r.limite_sintesis,
            "intentos_detalle": r.intentos_detalle,
        })

    resultado.intentos = intentos_totales
    resultado.sub_consultas = sub_consultas
    resultado.intentos_detalle = [
        {**d, "subpregunta": sc["pregunta"]} for sc in sub_consultas for d in sc["intentos_detalle"]
    ]
    resultado.sql = "\n\n".join(sqls) if sqls else None
    resultado.total_filas = sum(len(sc["filas"]) for sc in sub_consultas)

    respuesta = sintetizar_respuesta_integradora(client, pregunta, sub_consultas)
    todas_las_filas = [fila for sc in sub_consultas for fila in sc["filas"]]
    if not _respuesta_respaldada_por_datos(respuesta, todas_las_filas):
        _log_resumen_no_confiable(pregunta, respuesta, todas_las_filas)
        respuesta = MENSAJE_RESUMEN_NO_CONFIABLE

    sub_preguntas_fallidas = [sc["pregunta"] for sc in sub_consultas if not sc["filas"]]
    if sub_preguntas_fallidas:
        notas = "\n".join(f"Nota: no se pudo obtener el dato de: {p}" for p in sub_preguntas_fallidas)
        respuesta = f"{respuesta}\n\n{notas}"

    resultado.respuesta = respuesta
    return resultado


def answer_question(
    pregunta: str,
    client: OllamaClient | None = None,
    max_retries: int = 2,
    usar_plantillas: bool = True,
) -> Text2SQLResult:
    """Orquesta el flujo completo. `max_retries` controla cuántas veces se le
    permite al modelo corregir su propia consulta tras un error de calidad o
    ejecución (no de seguridad, que se rechaza siempre de inmediato).
    `usar_plantillas=False` desactiva plantillas por reglas y fallback sobre
    vistas (el SQL sale siempre del LLM); lo usa la evaluación del modelo."""
    client = client or OllamaClient()
    schema_context = get_schema_context()
    nombres_conocidos = get_known_names()

    # Patrones conocidos: las reglas deciden, sin gastar una llamada al clasificador.
    plantillas = detectar_plantillas(pregunta) if usar_plantillas else []
    if len(plantillas) > 1:
        return _answer_open_question(
            pregunta, [p.subpregunta for p in plantillas], client, schema_context, nombres_conocidos,
            max_retries, plantillas=plantillas,
        )

    sub_preguntas = None if plantillas else clasificar_pregunta(client, pregunta)
    if sub_preguntas:
        return _answer_open_question(
            pregunta, sub_preguntas, client, schema_context, nombres_conocidos, max_retries,
            usar_plantillas=usar_plantillas,
        )

    resultado = Text2SQLResult(pregunta=pregunta)
    r = _generar_y_ejecutar(
        client, pregunta, schema_context, nombres_conocidos, max_retries,
        plantilla=plantillas[0] if plantillas else None, usar_plantillas=usar_plantillas,
    )
    resultado.intentos = r.intentos
    resultado.sql = r.sql
    resultado.origen = r.origen
    resultado.detalle_error = r.error_detalle
    resultado.intentos_detalle = r.intentos_detalle

    if r.error_infra:
        resultado.error = r.error_infra
        return resultado
    if r.error_seguridad:
        resultado.error = f"La consulta generada no es una lectura segura y fue rechazada: {r.error_seguridad}"
        return resultado

    resultado.columnas = r.columnas
    resultado.filas = r.filas
    resultado.total_filas = len(r.filas)

    if r.mensaje_fijo:
        resultado.respuesta = r.mensaje_fijo
    else:
        respuesta = sintetizar_respuesta(client, pregunta, r.sql, r.columnas, r.filas, len(r.filas), r.limite_sintesis)
        if _respuesta_respaldada_por_datos(respuesta, r.filas):
            resultado.respuesta = respuesta
        else:
            _log_resumen_no_confiable(pregunta, respuesta, r.filas)
            resultado.respuesta = MENSAJE_RESUMEN_NO_CONFIABLE
    return resultado


def exportar_resultado_json(resultado: Text2SQLResult, pregunta: str, modelo: str) -> dict:
    """Arma el dict exportable (mismo esquema que dashboard/export_json.py) a
    partir de un `Text2SQLResult` YA calculado -- no vuelve a llamar al modelo.

    Si la pregunta se descompuso, `resultado` queda en [] y el detalle va en
    `sub_consultas` ([{pregunta, sql, columnas, resultado}]); `sql` es entonces
    una lista con el SQL de cada sub-consulta que se pudo generar."""
    from datetime import datetime

    def _filas_a_dicts(columnas: list[str], filas: list) -> list[dict]:
        return [dict(zip(columnas, fila)) for fila in filas]

    if resultado.sub_consultas:
        sql = [sc["sql"] for sc in resultado.sub_consultas if sc.get("sql")]
        columnas: list[str] = []
        filas_dicts: list[dict] = []
        sub_consultas = [
            {
                "pregunta": sc["pregunta"],
                "sql": sc.get("sql"),
                "columnas": list(sc.get("columnas") or []),
                "error": sc.get("error"),
                "origen": sc.get("origen"),
                "rechazo_llm": sc.get("rechazo_llm"),
                "resultado": _filas_a_dicts(sc.get("columnas") or [], sc.get("filas") or []),
            }
            for sc in resultado.sub_consultas
        ]
    else:
        sql = resultado.sql
        columnas = list(resultado.columnas)
        filas_dicts = _filas_a_dicts(resultado.columnas, resultado.filas)
        sub_consultas = []

    return {
        "pregunta": pregunta,
        "respuesta_clave": resultado.respuesta,
        "sql": sql,
        "columnas": columnas,
        "resultado": filas_dicts,
        "sub_consultas": sub_consultas,
        "error": resultado.error or (None if resultado.filas else resultado.detalle_error),
        "origen": resultado.origen,
        "rechazo_llm": resultado.detalle_error if resultado.origen not in (None, "llm") else None,
        "fuente": "llm_local",
        "modelo": modelo,
        "generado_en": datetime.now().isoformat(timespec="seconds"),
    }
