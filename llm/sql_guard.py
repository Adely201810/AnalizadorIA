"""
Validación de SQL generado por el LLM: seguridad + calidad.

Regla dura de SEGURIDAD: SOLO se permite una sentencia SELECT (o WITH ...
SELECT) de lectura. Cualquier otra cosa (`validate_select_only`) se rechaza
antes de tocar la base de datos, SIN reintento -- es defensa en profundidad
además de la conexión SQLite en modo solo-lectura que usa llm/text_to_sql.py.

Aparte hay checks de CALIDAD (`check_literales_placeholder`,
`check_tablas_conocidas`) que no son un riesgo de seguridad sino síntomas de
que el modelo alucinó un valor o un nombre de tabla/vista -- por eso lanzan un
tipo de error distinto (`SQLQualityError`), para que llm/text_to_sql.py les dé
un tratamiento distinto (un reintento, no rechazo inmediato).
"""
from __future__ import annotations

import re

# Palabras con las que empieza una sentencia SQL (no SELECT): si la respuesta
# del modelo empieza con otra cosa, no es SQL sino texto.
_PALABRAS_DE_SENTENCIA = {
    "insert", "update", "delete", "drop", "alter", "create", "replace", "truncate", "attach",
    "detach", "pragma", "vacuum", "reindex", "grant", "revoke", "begin", "commit", "rollback",
    "savepoint", "explain", "analyze", "values", "upsert", "merge", "release", "end",
}

FORBIDDEN_KEYWORDS = [
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "truncate", "attach", "detach", "pragma", "vacuum", "reindex",
    "grant", "revoke", "begin", "commit", "rollback", "savepoint",
]

_COMMENT_RE = re.compile(r"--.*?$|/\*.*?\*/", re.MULTILINE | re.DOTALL)
_STRING_LITERAL_RE = re.compile(r"'((?:[^']|'')*)'")
_PLACEHOLDER_RE = re.compile(r"^[A-Za-z_]+[0-9]+$")
_FROM_JOIN_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(\()?", re.IGNORECASE)
_CTE_NAME_RE = re.compile(r"\bWITH\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(|,\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", re.IGNORECASE)


class SQLValidationError(ValueError):
    """La consulta generada no pasó la validación de SEGURIDAD (no es un
    SELECT de solo lectura, o intenta colar una segunda sentencia).

    `motivo`: "prohibida" (sentencia o palabra clave no permitida, varias
    sentencias) o "no_es_sql" (el modelo respondió texto, p. ej. una negativa,
    en lugar de SQL). La clasificación de fallos (Fase 2) trata "no_es_sql"
    como ejecución, no como seguridad."""

    def __init__(self, mensaje: str, motivo: str = "prohibida"):
        super().__init__(mensaje)
        self.motivo = motivo


class SQLQualityError(ValueError):
    """La consulta es un SELECT válido pero tiene un síntoma de alucinación
    del modelo (literal inventado o tabla/vista inexistente).

    `motivo` dice qué check falló: "tabla_inexistente" / "columna_inexistente"
    (el SQL no correría) o "placeholder" / "dominio_join" (correría, pero
    respondería otra cosa). Lo usa la clasificación de fallos (Fase 2)."""

    def __init__(self, mensaje: str, motivo: str = "otro", detalles: list[dict] | None = None):
        super().__init__(mensaje)
        self.motivo = motivo
        # Para errores de esquema: [{"tipo": "columna", "tabla", "columna", "existe_en"}]
        # o [{"tipo": "tabla", "nombre"}]. Los usa la bitácora (llm/bitacora.py).
        self.detalles = detalles or []


def _strip_comments_and_strings_for_keyword_scan(sql: str) -> str:
    """Quita comentarios (para no que una palabra prohibida 'escondida' en un
    comentario dispare un falso positivo no es el riesgo real; el riesgo real
    es lo opuesto, así que igual la dejamos fuera del scan de statements)."""
    return _COMMENT_RE.sub(" ", sql)


def validate_select_only(sql: str) -> str:
    """
    Lanza SQLValidationError si `sql` no es una única sentencia SELECT/WITH de
    solo lectura. Si pasa, devuelve el SQL limpio (sin comentarios, sin ';' final).
    """
    if not sql or not sql.strip():
        raise SQLValidationError("El modelo no generó ninguna consulta SQL.", motivo="no_es_sql")

    cleaned = _strip_comments_and_strings_for_keyword_scan(sql).strip()

    # Solo se permite UNA sentencia: se rechazan ';' internos (aparte de uno
    # final opcional), que es la vía clásica para colar una segunda sentencia.
    sin_punto_final = cleaned[:-1] if cleaned.endswith(";") else cleaned
    if ";" in sin_punto_final:
        raise SQLValidationError(
            "La consulta contiene múltiples sentencias (';' interno), lo cual no está permitido."
        )

    primera_palabra = re.match(r"\s*([A-Za-z]+)", sin_punto_final)
    primera_palabra = primera_palabra.group(1).lower() if primera_palabra else ""
    if primera_palabra not in ("select", "with"):
        raise SQLValidationError(
            f"Solo se permiten consultas SELECT. La consulta generada empieza con '{primera_palabra}'.",
            motivo="prohibida" if primera_palabra in _PALABRAS_DE_SENTENCIA else "no_es_sql",
        )

    tokens = re.findall(r"[A-Za-z_]+", sin_punto_final.lower())
    for kw in FORBIDDEN_KEYWORDS:
        if kw in tokens:
            raise SQLValidationError(
                f"La consulta contiene la palabra clave no permitida '{kw.upper()}'. Solo se permite SELECT."
            )

    return sin_punto_final.strip()


def check_literales_placeholder(sql: str) -> None:
    """Rechaza literales de texto tipo 'categoria1', 'producto2' -- el patrón
    letra(s)+dígito(s) pegados es típico de un valor inventado por el modelo
    (placeholder), no de un dato real de Olist (categorías, estados, tipos de
    pago, etc. no siguen ese patrón)."""
    sospechosos = [
        m.group(1) for m in _STRING_LITERAL_RE.finditer(sql)
        if _PLACEHOLDER_RE.match(m.group(1))
    ]
    if sospechosos:
        raise SQLQualityError(
            f"La consulta usa literal(es) que parecen inventados (placeholder), no datos reales: "
            f"{', '.join(repr(s) for s in sospechosos)}. Usa valores reales del esquema o de las notas.",
            motivo="placeholder",
        )


def check_tablas_conocidas(sql: str, nombres_conocidos: set[str]) -> None:
    """Rechaza referencias a tablas/vistas que no existen en el esquema.
    Ignora subconsultas (identificador seguido de '(') y nombres definidos por
    el propio SQL en cláusulas WITH (CTEs), que no son tablas reales pero son
    válidos dentro de esa consulta."""
    cte_names = {
        (g1 or g2).lower()
        for g1, g2 in _CTE_NAME_RE.findall(sql)
    }
    conocidos_lower = {n.lower() for n in nombres_conocidos} | cte_names

    desconocidos = []
    for nombre, es_subconsulta in _FROM_JOIN_RE.findall(sql):
        if es_subconsulta:
            continue
        if nombre.lower() not in conocidos_lower and nombre.lower() not in desconocidos:
            desconocidos.append(nombre.lower())

    if desconocidos:
        raise SQLQualityError(
            f"La consulta referencia tabla(s)/vista(s) que no existen en el esquema: "
            f"{', '.join(desconocidos)}. Revisa los nombres exactos del esquema.",
            motivo="tabla_inexistente",
            detalles=[{"tipo": "tabla", "nombre": n} for n in desconocidos],
        )


# ---------------------------------------------------------------------------
# Capa de validación semántica (patrones donde el LLM de 8B genera SQL
# plausible pero roto): alias reservados, columnas que no existen en la tabla
# referenciada y JOINs entre columnas de dominios distintos.
# ---------------------------------------------------------------------------

# Lista oficial de palabras clave de SQLite (sqlite.org/lang_keywords.html). Solo
# es la lista de CANDIDATAS: cuáles rompen realmente como alias sin comillas lo
# decide el propio SQLite en `_palabras_reservadas_como_alias()` (varias, como
# KEY o ACTION, sí se aceptan como identificador y no hay que tocarlas).
_SQLITE_KEYWORDS = """
ABORT ACTION ADD AFTER ALL ALTER ALWAYS ANALYZE AND AS ASC ATTACH AUTOINCREMENT
BEFORE BEGIN BETWEEN BY CASCADE CASE CAST CHECK COLLATE COLUMN COMMIT CONFLICT
CONSTRAINT CREATE CROSS CURRENT CURRENT_DATE CURRENT_TIME CURRENT_TIMESTAMP
DATABASE DEFAULT DEFERRABLE DEFERRED DELETE DESC DETACH DISTINCT DO DROP EACH
ELSE END ESCAPE EXCEPT EXCLUDE EXCLUSIVE EXISTS EXPLAIN FAIL FILTER FIRST
FOLLOWING FOR FOREIGN FROM FULL GENERATED GLOB GROUP GROUPS HAVING IF IGNORE
IMMEDIATE IN INDEX INDEXED INITIALLY INNER INSERT INSTEAD INTERSECT INTO IS
ISNULL JOIN KEY LAST LEFT LIKE LIMIT MATCH MATERIALIZED NATURAL NO NOT NOTHING
NOTNULL NULL NULLS OF OFFSET ON OR ORDER OTHERS OUTER OVER PARTITION PLAN
PRAGMA PRECEDING PRIMARY QUERY RAISE RANGE RECURSIVE REFERENCES REGEXP REINDEX
RELEASE RENAME REPLACE RESTRICT RETURNING RIGHT ROLLBACK ROW ROWS SAVEPOINT
SELECT SET TABLE TEMP TEMPORARY THEN TIES TO TRANSACTION TRIGGER UNBOUNDED
UNION UNIQUE UPDATE USING VACUUM VALUES VIEW VIRTUAL WHEN WHERE WINDOW WITH
WITHOUT
""".split()

# Palabras que legítimamente siguen al nombre de una tabla en FROM/JOIN: no son alias.
_SEGUIDORES_DE_TABLA = {
    "WHERE", "GROUP", "ORDER", "LIMIT", "OFFSET", "HAVING", "WINDOW", "UNION", "INTERSECT",
    "EXCEPT", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "NATURAL", "FULL", "ON",
    "USING", "INDEXED", "NOT", "RETURNING",
}

# Operadores/palabras de flujo: si el LLM las usó como alias de COLUMNA solo se
# renombra la declaración (`AS or`), nunca las apariciones sueltas, que son el operador real.
_PALABRAS_DE_OPERADOR = {
    "AND", "OR", "NOT", "IN", "IS", "LIKE", "GLOB", "MATCH", "REGEXP", "BETWEEN", "ESCAPE",
    "ISNULL", "NOTNULL", "NULL", "CASE", "WHEN", "THEN", "ELSE", "END", "EXISTS", "COLLATE",
    "AS", "SELECT", "FROM", "WHERE", "GROUP", "ORDER", "BY", "HAVING", "LIMIT", "ON", "JOIN",
    "DISTINCT", "ALL", "UNION", "OVER", "ASC", "DESC",
}

_TOKEN_RE = re.compile(
    r"'(?:[^']|'')*'|\"[^\"]*\"|`[^`]*`|\[[^\]]*\]|--[^\n]*|/\*.*?\*/"
    r"|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|\s+|.",
    re.DOTALL,
)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Columnas que son llaves de unión: dos de ellas con nombre distinto nunca son
# comparables entre sí (order_id vs seller_id son dominios distintos).
COLUMNAS_LLAVE = {"order_id", "seller_id", "customer_id", "customer_unique_id", "product_id", "review_id"}

_reservadas_cache: set[str] | None = None


def _palabras_reservadas_como_alias() -> set[str]:
    """Palabras clave de SQLite que NO se pueden usar como alias sin comillas,
    determinadas empíricamente contra el SQLite real en uso (se calcula una vez)."""
    global _reservadas_cache
    if _reservadas_cache is None:
        import sqlite3

        conn = sqlite3.connect(":memory:")
        reservadas = set()
        try:
            for kw in _SQLITE_KEYWORDS:
                for stmt in (
                    f"SELECT 1 AS {kw}",
                    f"SELECT 1 FROM (SELECT 1 AS x) AS {kw}",
                ):
                    try:
                        conn.execute(stmt).fetchall()
                    except sqlite3.Error:
                        reservadas.add(kw.upper())
                        break
        finally:
            conn.close()
        _reservadas_cache = reservadas
    return _reservadas_cache


def _tokenizar(sql: str) -> list[str]:
    return _TOKEN_RE.findall(sql)


def _indices_significativos(tokens: list[str]) -> list[int]:
    """Índices de los tokens que no son espacios ni comentarios."""
    return [i for i, t in enumerate(tokens) if not t.isspace() and not t.startswith(("--", "/*"))]


def _es_ident(token: str) -> bool:
    return bool(_IDENT_RE.match(token))


def _escanear_declaraciones(tokens: list[str]) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Devuelve (alias_de_tabla, alias_de_columna) como listas de (índice_de_token, alias).

    Alias de tabla: `FROM|JOIN tabla [AS] alias` y `FROM|JOIN (subconsulta) [AS] alias`.
    Alias de columna: `expr AS alias` (fuera de `CAST(x AS tipo)` y de `nombre AS (` en CTEs).
    """
    sig = _indices_significativos(tokens)
    alias_tabla: list[tuple[int, str]] = []
    alias_col: list[tuple[int, str]] = []
    pila_parentesis: list[tuple[bool, int]] = []  # (es_subconsulta_de_FROM, posición en `sig`)
    tabla_con_alias: set[int] = set()  # posiciones en `sig` de alias ya contados como alias de tabla

    def alias_tras(pos: int) -> tuple[int, str] | None:
        """Alias que sigue a la posición `pos` de `sig` (opcional AS)."""
        if pos + 1 >= len(sig):
            return None
        sig_tok = tokens[sig[pos + 1]]
        if sig_tok.upper() == "AS":
            if pos + 2 < len(sig) and _es_ident(tokens[sig[pos + 2]]):
                return sig[pos + 2], tokens[sig[pos + 2]]
            return None
        if _es_ident(sig_tok) and sig_tok.upper() not in _SEGUIDORES_DE_TABLA:
            return sig[pos + 1], sig_tok
        return None

    for pos, idx in enumerate(sig):
        tok = tokens[idx]
        up = tok.upper()
        if up in ("FROM", "JOIN") and pos + 1 < len(sig):
            siguiente = tokens[sig[pos + 1]]
            if _es_ident(siguiente):
                encontrado = alias_tras(pos + 1)
                if encontrado:
                    alias_tabla.append(encontrado)
                    tabla_con_alias.add(sig.index(encontrado[0]))
        elif tok == "(":
            previo = tokens[sig[pos - 1]].upper() if pos > 0 else ""
            pila_parentesis.append((previo in ("FROM", "JOIN"), pos))
        elif tok == ")" and pila_parentesis:
            es_from_sub, _ = pila_parentesis.pop()
            if es_from_sub:
                encontrado = alias_tras(pos)
                if encontrado:
                    alias_tabla.append(encontrado)
                    tabla_con_alias.add(sig.index(encontrado[0]))
        elif up == "AS" and pos + 1 < len(sig) and pos not in tabla_con_alias:
            siguiente_idx = sig[pos + 1]
            if _es_ident(tokens[siguiente_idx]) and (pos + 1) not in tabla_con_alias:
                # CAST(x AS tipo): el tipo no es alias (además nunca es palabra reservada, pero por claridad).
                alias_col.append((siguiente_idx, tokens[siguiente_idx]))
    return alias_tabla, alias_col


def sanitizar_alias_reservados(sql: str) -> tuple[str, dict[str, str]]:
    """Renombra alias generados por el LLM que son palabras reservadas de SQLite
    (ej. `JOIN order_reviews or` -> `JOIN order_reviews orv`), porque rompen la
    consulta con un error de sintaxis que el modelo suele repetir al reintentar.

    Devuelve (sql_corregido, {alias_original: alias_nuevo}); el dict va vacío si
    no hubo nada que cambiar.
    """
    reservadas = _palabras_reservadas_como_alias()
    tokens = _tokenizar(sql)
    alias_tabla, alias_col = _escanear_declaraciones(tokens)

    reservados_tabla = {a.lower() for _, a in alias_tabla if a.upper() in reservadas}
    reservados_col = {a.lower() for _, a in alias_col if a.upper() in reservadas}
    if not reservados_tabla and not reservados_col:
        return sql, {}

    en_uso = {t.lower() for t in tokens if _es_ident(t)}
    renombres: dict[str, str] = {}
    for original in sorted(reservados_tabla | reservados_col):
        nuevo = original + "v"
        while nuevo in en_uso:
            nuevo += "v"
        en_uso.add(nuevo)
        renombres[original] = nuevo

    sig = _indices_significativos(tokens)
    pos_de = {idx: p for p, idx in enumerate(sig)}
    declaraciones = {idx for idx, a in alias_tabla if a.lower() in renombres} | {
        idx for idx, a in alias_col if a.lower() in renombres
    }
    for idx, tok in enumerate(tokens):
        clave = tok.lower()
        if clave not in renombres or not _es_ident(tok):
            continue
        p = pos_de.get(idx)
        if p is None:
            continue
        siguiente = tokens[sig[p + 1]] if p + 1 < len(sig) else ""
        previo = tokens[sig[p - 1]] if p > 0 else ""
        if idx in declaraciones:
            reemplazar = True
        elif siguiente == "." and previo != ".":
            reemplazar = clave in reservados_tabla  # `alias.columna`
        else:
            # Referencia suelta (ej. ORDER BY <alias de columna>): solo si es alias de columna
            # y la palabra no es un operador real de SQL.
            reemplazar = (
                clave in reservados_col
                and clave not in reservados_tabla
                and tok.upper() not in _PALABRAS_DE_OPERADOR
                and previo != "."
            )
        if reemplazar:
            tokens[idx] = renombres[clave]
    return "".join(tokens), renombres


def _mapa_alias_a_tabla(tokens: list[str], esquema: dict[str, set[str]]) -> dict[str, set[str]]:
    """alias (o nombre de tabla sin alias) -> conjunto de tablas reales a las que apunta.
    Las subconsultas y CTEs se marcan con '?' (columnas desconocidas: no se validan)."""
    sig = _indices_significativos(tokens)
    mapa: dict[str, set[str]] = {}

    def registrar(nombre: str, destino: str) -> None:
        mapa.setdefault(nombre.lower(), set()).add(destino)

    pila: list[bool] = []
    for pos, idx in enumerate(sig):
        tok = tokens[idx]
        up = tok.upper()
        if up in ("FROM", "JOIN") and pos + 1 < len(sig):
            siguiente = tokens[sig[pos + 1]]
            if _es_ident(siguiente):
                real = siguiente.lower() if siguiente.lower() in esquema else "?"
                tras = pos + 2
                alias = None
                if tras < len(sig) and tokens[sig[tras]].upper() == "AS" and tras + 1 < len(sig):
                    alias = tokens[sig[tras + 1]]
                elif tras < len(sig) and _es_ident(tokens[sig[tras]]) and tokens[sig[tras]].upper() not in _SEGUIDORES_DE_TABLA:
                    alias = tokens[sig[tras]]
                registrar(alias or siguiente, real)
        elif tok == "(":
            previo = tokens[sig[pos - 1]].upper() if pos > 0 else ""
            pila.append(previo in ("FROM", "JOIN"))
        elif tok == ")" and pila:
            if pila.pop():
                tras = pos + 1
                if tras < len(sig) and tokens[sig[tras]].upper() == "AS":
                    tras += 1
                if tras < len(sig) and _es_ident(tokens[sig[tras]]) and tokens[sig[tras]].upper() not in _SEGUIDORES_DE_TABLA:
                    registrar(tokens[sig[tras]], "?")
    return mapa


def _referencias_calificadas(tokens: list[str]) -> list[tuple[str, str]]:
    """Todas las referencias `qualifier.columna` del SQL (fuera de strings)."""
    sig = _indices_significativos(tokens)
    refs = []
    for pos in range(len(sig) - 2):
        a, punto, b = (tokens[sig[pos]], tokens[sig[pos + 1]], tokens[sig[pos + 2]])
        if punto != "." or not _es_ident(a):
            continue
        if pos > 0 and tokens[sig[pos - 1]] == ".":
            continue
        if _es_ident(b) or b == "*":
            refs.append((a, b))
    return refs


def check_columnas_existentes(sql: str, esquema: dict[str, set[str]]) -> None:
    """Rechaza `alias.columna` cuando la tabla/vista real detrás de `alias` no
    tiene esa columna (ej. `o.seller_id` con `orders o`: seller_id vive en
    order_items). `esquema` es {tabla_o_vista_en_minúsculas: {columnas en minúsculas}}
    tomado de la base real. Subconsultas y CTEs no se validan (su esquema es propio)."""
    tokens = _tokenizar(sql)
    mapa = _mapa_alias_a_tabla(tokens, esquema)

    problemas: list[str] = []
    detalles: list[dict] = []
    for calificador, columna in _referencias_calificadas(tokens):
        destinos = mapa.get(calificador.lower())
        if not destinos or len(destinos) != 1:
            continue  # alias desconocido (lo atrapa SQLite) o ambiguo entre alcances
        tabla = next(iter(destinos))
        if tabla == "?" or columna == "*":
            continue
        if columna.lower() not in esquema[tabla]:
            donde = sorted(t for t, cols in esquema.items() if columna.lower() in cols)
            pista = (
                f" Esa columna sí existe en: {', '.join(donde)}." if donde
                else " Esa columna no existe en ninguna tabla ni vista del esquema."
            )
            problemas.append(f"'{calificador}.{columna}': la tabla/vista '{tabla}' no tiene la columna '{columna}'.{pista}")
            detalles.append({"tipo": "columna", "tabla": tabla, "columna": columna.lower(), "existe_en": donde})
    if problemas:
        raise SQLQualityError(
            "La consulta usa columnas que no existen en la tabla indicada: " + " ".join(dict.fromkeys(problemas))
            + " Revisa las columnas de cada tabla y las 'Columnas de unión' del esquema, o usa una vista.",
            motivo="columna_inexistente",
            detalles=detalles,
        )


def check_dominios_join(sql: str) -> None:
    """Rechaza igualdades entre llaves de dominios distintos (ej.
    `r.order_id = v.seller_id`): SQLite las ejecuta sin error y devuelven 0 filas."""
    tokens = _tokenizar(sql)
    sig = _indices_significativos(tokens)
    malos = []
    for pos in range(len(sig) - 6):
        ventana = [tokens[sig[pos + k]] for k in range(7)]
        if ventana[1] == "." and ventana[3] == "=" and ventana[5] == "." and _es_ident(ventana[0]) and _es_ident(ventana[4]):
            col_a, col_b = ventana[2].lower(), ventana[6].lower()
            if col_a != col_b and col_a in COLUMNAS_LLAVE and col_b in COLUMNAS_LLAVE:
                malos.append(f"{ventana[0]}.{ventana[2]} = {ventana[4]}.{ventana[6]}")
    if malos:
        raise SQLQualityError(
            "La consulta compara columnas de dominios distintos en un JOIN/filtro: "
            + ", ".join(dict.fromkeys(malos))
            + ". Une siempre order_id con order_id, seller_id con seller_id, customer_id con customer_id, etc.",
            motivo="dominio_join",
        )
