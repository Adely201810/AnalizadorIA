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
from typing import Callable

_logger = logging.getLogger(__name__)

from db.olist_database import DATABASE_URL
from llm import contexto_e3
from llm.bitacora import BitacoraEsquema, detalles_de_error
from llm.juez import JuezLLM
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
# Intentos totales por pregunta en el chat (Fase 6). 2 = un reintento, como el
# comportamiento efectivo anterior; configurable con TEXT2SQL_N_INTENTOS.
N_INTENTOS_POR_DEFECTO = int(os.environ.get("TEXT2SQL_N_INTENTOS", "2"))
# Etapa 2, Paso 3 (a): el clasificador puede partir en sub-consultas preguntas que se
# resuelven con una sola. Apagado por defecto desde el A/B (3/3/3 -> 5/5/5, D-25);
# TEXT2SQL_CLASIFICADOR=1 lo vuelve a encender.
USAR_CLASIFICADOR_POR_DEFECTO = os.environ.get("TEXT2SQL_CLASIFICADOR", "0") == "1"
# Límite de tiempo de ejecución del SQL generado. La consulta de referencia más
# lenta del oráculo tarda ~10 s; 60 s deja margen (docs/FASE_03.md).
LIMITE_EJECUCION_S = float(os.environ.get("TEXT2SQL_LIMITE_EJECUCION_S", "60"))
# Cierre del juez (D-40). Apagados por defecto hasta el A/B con la regla D-23:
#   TEXT2SQL_REPARAR_ESQUEMA=1  el reintento recibe, además del error, las columnas REALES del objeto
#                               implicado y la ruta por tablas base (llm.juez.reparar_con_esquema; sin oráculo).
#   TEXT2SQL_TEXTO_UMBRALES=1   el chequeo de "texto confiable" acepta los números que ya vienen en la pregunta.
USAR_REPARAR_ESQUEMA = os.environ.get("TEXT2SQL_REPARAR_ESQUEMA", "0") == "1"
USAR_TEXTO_UMBRALES = os.environ.get("TEXT2SQL_TEXTO_UMBRALES", "0") == "1"
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

PREFIJO_NEGATIVA_MODELO = "El modelo no generó una consulta SQL; respondió con texto: "
# Texto que ve el usuario del chat según `Text2SQLResult.tipo_error` (Etapa 2, Paso 4).
MENSAJES_ERROR_CHAT = {
    "seguridad": ("Rechacé la consulta que generó el modelo porque no era una lectura segura "
                  "(solo se permiten consultas SELECT). No se ejecutó nada en la base de datos."),
    "negativa_modelo": ("El modelo no generó una consulta SQL para esta pregunta (respondió con texto). "
                        "No se ejecutó nada. ¿Puedes reformularla, por ejemplo nombrando la métrica que buscas?"),
    "infra": "No pude conectar con el modelo de lenguaje (Ollama). Revisa que el servidor esté en marcha.",
}
MENSAJE_ERROR_CHAT_GENERICO = "No pude generar una consulta válida para responder eso. ¿Puedes reformular la pregunta?"


def _resumen_texto_modelo(texto: str | None, limite: int = 200) -> str:
    """Primeros caracteres de la respuesta no-SQL del modelo, en una línea, entre comillas."""
    t = " ".join((texto or "").split())
    return f"«{t[:limite]}{'…' if len(t) > limite else ''}»"


MENSAJE_RESUMEN_NO_CONFIABLE = "No pude redactar un resumen confiable; revisa la tabla de resultados."

PISTA_CERO_FILAS = (
    "La consulta se ejecutó sin errores pero no devolvió ninguna fila. Revisa si "
    "el JOIN o el filtro está mal planteado (por ejemplo, saltarte la tabla orders "
    "al relacionar customers con order_items); si aplica, usa directamente una de "
    "las vistas del esquema. Recuerda también que los datos de Olist solo cubren "
    "2016-2018. Genera una consulta corregida."
)

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


def _respuesta_respaldada_por_datos(respuesta: str, filas: list[tuple], numeros_extra: list[float] | None = None) -> bool:
    """Todo número con decimales, y todo entero >= 10, debe corresponder
    (redondeando a la misma precisión con la que se escribió) a un valor real
    en `filas`. Los enteros < 10 se ignoran -- casi siempre son estructurales
    (rankings, "1-2 frases", etc.), no cifras de negocio.

    `numeros_extra` (juez, ronda 2, D-37; el chat no lo pasa): números que también
    cuentan como respaldados, p. ej. los umbrales que ya vienen en la pregunta."""
    numeros_datos = _numeros_de_filas(filas) + list(numeros_extra or [])
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
    # Chat libre (Fase 10): {"tiene_sentido": bool|None, "motivo": str} del juez-LLM.
    # Revisa si el SQL TIENE SENTIDO para la pregunta; NO verifica que la cifra sea correcta.
    revision_sensatez: dict | None = None
    # Etapa 2, Paso 4: por qué no hubo respuesta, para que el chat no confunda casos:
    # "seguridad" (el SQL del modelo no era una lectura permitida), "negativa_modelo"
    # (el modelo respondió con texto en vez de SQL) o "infra" (Ollama no respondió).
    tipo_error: str | None = None


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
    notas: str | None = None,
) -> str:
    if contexto_e3.depende_de_la_pregunta():  # Etapa 3: E2 / E5
        schema_context = contexto_e3.esquema_para(pregunta)
    system_prompt = SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=schema_context)
    num_predict = 350
    if contexto_e3.USAR_PLAN:  # Etapa 3: E6
        system_prompt = system_prompt.replace(contexto_e3.REGLA_SOLO_SQL, contexto_e3.REGLA_PLAN)
        num_predict = contexto_e3.NUM_PREDICT_CON_PLAN
    prompt = f"Pregunta: {pregunta}"
    extra = contexto_e3.contexto_usuario(pregunta)  # Etapa 3: E1 / E5
    if extra:
        prompt += f"\n\n{extra}"
    if notas:
        # Va en el prompt de USUARIO: si fuera en el system, cada cambio de la
        # bitácora invalidaría la caché del prefijo del esquema (docs/FASE_04.md).
        prompt += f"\n\n{notas}"
    if error_previo and sql_previo:
        prompt += (
            f"\n\nYa intentaste responder con esta consulta:\n```sql\n{sql_previo}\n```"
            f"\nPero tuvo este problema: {error_previo}"
            f"\nGenera una nueva consulta SQL corregida que resuelva el problema."
        )
    respuesta = client.generate(prompt, system=system_prompt, num_predict=num_predict)
    return extract_sql(respuesta)


def _firma_resultado(filas: list[tuple]) -> tuple:
    """Resultado comparable entre candidatos: números redondeados a 2 decimales, filas en orden."""
    def norm(v):
        return round(v, 2) if isinstance(v, float) else v
    return tuple(sorted((tuple(norm(v) for v in f) for f in filas[:50]), key=repr))


def _elegir_por_autoconsistencia(client, pregunta, schema_context, notas, k, nombres_conocidos, esquema_real):
    """Etapa 3, E7: genera k SQL, ejecuta los que pasan las validaciones y devuelve el SQL cuyo
    resultado es el más frecuente (empate: el primero en aparecer). No usa la referencia, así
    que también sirve en el chat. Si ninguno corre con filas, devuelve el primer SQL generado
    para que el flujo normal (error -> reintento) siga igual que sin E7."""
    candidatos, primero = [], None
    for _ in range(k):
        sql = generar_sql(client, pregunta, schema_context, notas=notas)
        primero = primero if primero is not None else sql
        try:
            limpio, _ = sanitizar_alias_reservados(validate_select_only(sql))
            check_literales_placeholder(limpio)
            check_tablas_conocidas(limpio, nombres_conocidos)
            check_columnas_existentes(limpio, esquema_real)
            check_dominios_join(limpio)
            _, filas = execute_readonly(limpio)
        except (SQLValidationError, SQLQualityError, sqlite3.Error):
            continue
        if filas:
            candidatos.append((sql, _firma_resultado(filas)))
    info = {"k": k, "ejecutables_con_filas": len(candidatos), "resultados_distintos": len({f for _, f in candidatos})}
    if not candidatos:
        return primero or "", {**info, "votos_ganador": 0}
    conteo = {}
    for _, f in candidatos:
        conteo[f] = conteo.get(f, 0) + 1
    ganador = max(conteo.values())
    sql = next(s for s, f in candidatos if conteo[f] == ganador)
    return sql, {**info, "votos_ganador": ganador}


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
    rechazo_modelo: str | None = None  # el modelo contestó con texto, no con SQL (no es un tema de seguridad)
    error_infra: str | None = None
    mensaje_fijo: str | None = None  # MENSAJE_SIN_RESULTADOS o MENSAJE_PROBLEMA_TRAS_REINTENTO
    origen: str = "llm"  # "llm", "plantilla:<nombre>" o "fallback_vista:<nombre>"
    error_detalle: str | None = None  # último problema del SQL del LLM (visible aunque no haya "error" de infraestructura)
    limite_sintesis: int | None = None  # filas que se le muestran al modelo al sintetizar (None = default)
    intentos_detalle: list[dict] = field(default_factory=list)  # ver Text2SQLResult.intentos_detalle


# Verificador opcional de un resultado ya ejecutado (Fase 9): recibe
# (sql, columnas, filas) y devuelve (es_correcto, pista_para_el_siguiente_intento).
# En la evaluación es el árbitro determinista contra la referencia; en el chat
# no hay verificador y se acepta el primer SQL que corre y devuelve filas.
Verificador = Callable[[str, list, list], "tuple[bool, str | None]"]


def _pista_con_reparacion(error: str, exc: Exception, sql: str) -> str:
    """TEXT2SQL_REPARAR_ESQUEMA (D-40): añade al error real las columnas reales y la ruta por tablas
    base (llm.juez.reparar_con_esquema, que solo lee el esquema de la base; no usa el oráculo)."""
    from llm.juez import reparar_con_esquema

    reparacion = reparar_con_esquema({
        "ok": False, "etapa": "validacion" if isinstance(exc, SQLQualityError) else "ejecucion",
        "error": error, "detalles": getattr(exc, "detalles", []), "sql": sql,
    })
    return f"{error} {reparacion}" if reparacion else error


def _numeros_extra_sintesis(pregunta: str) -> list[float] | None:
    """TEXT2SQL_TEXTO_UMBRALES (D-40): los números de la pregunta (umbrales) cuentan como respaldados."""
    return [n for n, _ in _extraer_numeros_respuesta(pregunta)] if USAR_TEXTO_UMBRALES else None


def _generar_y_ejecutar_llm(
    client: OllamaClient,
    pregunta: str,
    schema_context: str,
    nombres_conocidos: set[str],
    n_intentos: int,
    verificador: Verificador | None = None,
    bitacora: BitacoraEsquema | None = None,
) -> _ResolucionSQL:
    """Hasta `n_intentos` intentos de generar_sql -> validar -> ejecutar (Fase 6).

    Cada problema consume un intento y el siguiente recibe una pista (Fase 7):
    el error real del motor/validador, el aviso de 0 filas o, si hay
    `verificador` y rechaza el resultado, la pista que él devuelve (nunca el
    valor correcto). La cadena se corta en el PRIMER ACIERTO (Fase 9): sin
    verificador, el primer SQL que corre y devuelve filas; con verificador, el
    primero que el verificador acepta. Un rechazo de SEGURIDAD corta siempre,
    sin reintento.
    """
    resultado = _ResolucionSQL()
    esquema_real = get_esquema_real()
    sql_generado: str | None = None
    pista: str | None = None
    notas = bitacora.texto_para_prompt() if bitacora else None

    info_autoconsistencia = None

    def registrar(tipo: str, sql: str | None, detalle: str | None, **extra) -> None:
        if resultado.intentos == 1 and info_autoconsistencia:
            extra["autoconsistencia"] = info_autoconsistencia
        resultado.intentos_detalle.append(
            {"intento": resultado.intentos, "sql": sql, "tipo": tipo, "detalle": detalle, **extra}
        )

    for intento in range(1, n_intentos + 1):
        resultado.intentos = intento
        ultimo = intento == n_intentos
        try:
            if intento == 1 and contexto_e3.K_AUTOCONSISTENCIA > 1:  # Etapa 3: E7
                sql_generado, info_autoconsistencia = _elegir_por_autoconsistencia(
                    client, pregunta, schema_context, notas, contexto_e3.K_AUTOCONSISTENCIA,
                    nombres_conocidos, esquema_real)
            else:
                sql_generado = generar_sql(
                    client, pregunta, schema_context, error_previo=pista, sql_previo=sql_generado, notas=notas,
                )
        except OllamaError as exc:
            registrar(clasificar_excepcion(exc), None, str(exc))
            if not ultimo:
                pista, sql_generado = None, None  # sin SQL previo que corregir: se repite el mismo prompt
                continue
            resultado.error_infra = str(exc)
            resultado.error_detalle = str(exc)
            resultado.mensaje_fijo = MENSAJE_PROBLEMA_TRAS_REINTENTO
            return resultado

        if not sql_generado.strip():
            registrar("ejecucion", None, "El modelo no devolvió ninguna consulta SQL.")
            if not ultimo:
                pista, sql_generado = None, None
                continue
            resultado.error_detalle = "El modelo no devolvió ninguna consulta SQL."
            resultado.mensaje_fijo = MENSAJE_PROBLEMA_TRAS_REINTENTO
            return resultado

        try:
            sql_validado = validate_select_only(sql_generado)
        except SQLValidationError as exc:
            registrar(clasificar_excepcion(exc), sql_generado, str(exc))
            resultado.sql = sql_generado
            if exc.motivo == "no_es_sql":
                resultado.rechazo_modelo = _resumen_texto_modelo(sql_generado)
            else:
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
            error = str(exc) if isinstance(exc, SQLQualityError) else f"Error de SQLite al ejecutar la consulta: {exc}"
            if bitacora is not None:
                bitacora.registrar(detalles_de_error(exc, esquema_real, sql_validado), pregunta)
            pista_error = _pista_con_reparacion(error, exc, sql_validado) if USAR_REPARAR_ESQUEMA else error
            registrar(clasificar_excepcion(exc), sql_validado, error, pista_siguiente=None if ultimo else pista_error)
            sql_generado = sql_validado
            if not ultimo:
                pista = pista_error
                continue
            resultado.sql = sql_validado
            resultado.error_detalle = error
            resultado.mensaje_fijo = MENSAJE_PROBLEMA_TRAS_REINTENTO
            return resultado

        if not filas:
            # Corre pero no devuelve nada: sospecha semántica (filtro o JOIN mal planteado).
            registrar("semantico", sql_validado, "La consulta se ejecutó sin errores pero no devolvió ninguna fila.",
                      pista_siguiente=None if ultimo else PISTA_CERO_FILAS)
            sql_generado = sql_validado
            if not ultimo:
                pista = PISTA_CERO_FILAS
                continue
            resultado.sql = sql_validado
            resultado.columnas = columnas
            resultado.filas = filas
            resultado.mensaje_fijo = MENSAJE_SIN_RESULTADOS
            return resultado

        if verificador is not None:
            correcto, pista_verificador = verificador(sql_validado, columnas, filas)
            registrar("ok", sql_validado, None, verificado=correcto,
                      pista_siguiente=None if (correcto or ultimo) else pista_verificador)
            if not correcto and not ultimo:
                sql_generado, pista = sql_validado, pista_verificador
                continue
        else:
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
    n_intentos: int,
    plantilla: Plantilla | None = None,
    usar_plantillas: bool = True,
    verificador: Verificador | None = None,
    bitacora: BitacoraEsquema | None = None,
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
        return _generar_y_ejecutar_llm(client, pregunta, schema_context, nombres_conocidos, n_intentos, verificador, bitacora)
    if plantilla is None:
        detectadas = detectar_plantillas(pregunta)
        plantilla = detectadas[0] if detectadas else None
    if plantilla is not None:
        resuelto = _ejecutar_plantilla(plantilla, "plantilla")
        if resuelto is not None:
            return resuelto

    resultado = _generar_y_ejecutar_llm(client, pregunta, schema_context, nombres_conocidos, n_intentos, verificador, bitacora)
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
    n_intentos: int,
    plantillas: list[Plantilla] | None = None,
    usar_plantillas: bool = True,
    bitacora: BitacoraEsquema | None = None,
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
            client, sub_pregunta, schema_context, nombres_conocidos, n_intentos,
            plantilla=plantilla, usar_plantillas=usar_plantillas, bitacora=bitacora,
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
            "error": (r.error_infra or r.error_seguridad
                      or (f"{PREFIJO_NEGATIVA_MODELO}{r.rechazo_modelo}" if r.rechazo_modelo else None)
                      or (None if r.filas else r.error_detalle)),
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
    if not _respuesta_respaldada_por_datos(respuesta, todas_las_filas, _numeros_extra_sintesis(pregunta)):
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
    n_intentos: int = N_INTENTOS_POR_DEFECTO,
    usar_plantillas: bool = True,
    verificador: Verificador | None = None,
    bitacora: BitacoraEsquema | None = None,
    juez_sensatez: JuezLLM | None = None,
    usar_clasificador: bool | None = None,
) -> Text2SQLResult:
    """Orquesta el flujo completo.

    `n_intentos` (Fase 6) = número TOTAL de intentos de generar SQL para la
    pregunta (n_intentos=1: sin reintentos). Cada error de ejecución/calidad, 0
    filas o rechazo del `verificador` consume un intento; un rechazo de
    seguridad corta siempre. `usar_plantillas=False` desactiva plantillas por
    reglas y fallback sobre vistas (el SQL sale siempre del LLM).
    `verificador` (Fase 9): ver `Verificador`; sin él, se acepta el primer SQL
    que corre y devuelve filas. No se aplica a preguntas descompuestas.
    `bitacora` (Fase 10): registra errores de esquema y los recuerda en
    preguntas futuras. `juez_sensatez` (Fase 10): el juez-LLM revisa si el SQL
    final tiene sentido para la pregunta (no si la cifra es correcta)."""
    client = client or OllamaClient()
    schema_context = get_schema_context()
    nombres_conocidos = get_known_names()

    # Patrones conocidos: las reglas deciden, sin gastar una llamada al clasificador.
    plantillas = detectar_plantillas(pregunta) if usar_plantillas else []
    if len(plantillas) > 1:
        return _answer_open_question(
            pregunta, [p.subpregunta for p in plantillas], client, schema_context, nombres_conocidos,
            n_intentos, plantillas=plantillas, bitacora=bitacora,
        )

    if usar_clasificador is None:
        usar_clasificador = USAR_CLASIFICADOR_POR_DEFECTO
    sub_preguntas = None if (plantillas or not usar_clasificador) else clasificar_pregunta(client, pregunta)
    if sub_preguntas:
        return _answer_open_question(
            pregunta, sub_preguntas, client, schema_context, nombres_conocidos, n_intentos,
            usar_plantillas=usar_plantillas, bitacora=bitacora,
        )

    resultado = Text2SQLResult(pregunta=pregunta)
    r = _generar_y_ejecutar(
        client, pregunta, schema_context, nombres_conocidos, n_intentos,
        plantilla=plantillas[0] if plantillas else None, usar_plantillas=usar_plantillas,
        verificador=verificador, bitacora=bitacora,
    )
    resultado.intentos = r.intentos
    resultado.sql = r.sql
    resultado.origen = r.origen
    resultado.detalle_error = r.error_detalle
    resultado.intentos_detalle = r.intentos_detalle

    if r.error_infra:
        resultado.error = r.error_infra
        resultado.tipo_error = "infra"
        return resultado
    if r.error_seguridad:
        resultado.error = f"La consulta generada no es una lectura segura y fue rechazada: {r.error_seguridad}"
        resultado.tipo_error = "seguridad"
        return resultado
    if r.rechazo_modelo:
        resultado.error = f"{PREFIJO_NEGATIVA_MODELO}{r.rechazo_modelo}"
        resultado.tipo_error = "negativa_modelo"
        return resultado

    resultado.columnas = r.columnas
    resultado.filas = r.filas
    resultado.total_filas = len(r.filas)

    if juez_sensatez is not None and r.sql and r.filas:
        o = juez_sensatez.evaluar_sensatez(pregunta, r.sql)
        resultado.revision_sensatez = {"tiene_sentido": o.valor, "motivo": o.motivo}

    if r.mensaje_fijo:
        resultado.respuesta = r.mensaje_fijo
    else:
        respuesta = sintetizar_respuesta(client, pregunta, r.sql, r.columnas, r.filas, len(r.filas), r.limite_sintesis)
        if _respuesta_respaldada_por_datos(respuesta, r.filas, _numeros_extra_sintesis(pregunta)):
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
        "revision_sensatez_sql": resultado.revision_sensatez,
        "fuente": "llm_local",
        "modelo": modelo,
        "generado_en": datetime.now().isoformat(timespec="seconds"),
    }
