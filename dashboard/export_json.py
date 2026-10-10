"""
Exportación a JSON de las respuestas del dashboard (SQL directo, sin IA).

`exportar_necesidad_json(n)` arma, para la necesidad `n` (1..10), un dict con el
MISMO esquema que `llm.text_to_sql.exportar_resultado_json`, para poder
comparar ambos archivos campo por campo. Se distinguen por el campo `fuente`
("software_sql_directo" aquí, "llm_local" en el chatbot).

Este módulo solo lee lo que devuelven las funciones qNN() de
dashboard/queries.py; no modifica ni duplica ningún cálculo.
"""
from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd

from dashboard import queries

FUENTE = "software_sql_directo"


def _nativo(valor):
    """Convierte un valor de pandas/numpy a un tipo JSON estándar (NaN/NaT -> None)."""
    if valor is None:
        return None
    if isinstance(valor, (pd.Timestamp, datetime, date)):
        return None if pd.isna(valor) else valor.isoformat()
    if hasattr(valor, "item") and not isinstance(valor, (str, bytes)):  # escalares numpy
        valor = valor.item()
    if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
        return None
    if isinstance(valor, dict):
        return {str(k): _nativo(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_nativo(v) for v in valor]
    return valor


def _df_a_filas(df: pd.DataFrame) -> list[dict]:
    return [{str(col): _nativo(v) for col, v in fila.items()} for fila in df.to_dict("records")]


def exportar_necesidad_json(n: int, resultado_precalculado: dict | None = None, **parametros) -> dict:
    """Devuelve el dict listo para `json.dumps` de la necesidad `n`.

    `parametros` se pasan tal cual a qNN(); los que no se indiquen usan el valor
    por defecto de esa función. Si la página ya calculó el resultado con esos
    parámetros, se puede pasar como `resultado_precalculado` para no repetir la
    consulta SQL (las cifras del JSON son entonces exactamente las de pantalla).
    """
    if not 1 <= n <= 10:
        raise ValueError(f"La necesidad debe estar entre 1 y 10, no {n!r}.")

    r = resultado_precalculado
    if r is None:
        r = getattr(queries, f"q{n:02d}")(**parametros)

    nombres = list(r["tablas"].keys())
    principal = r["tablas"][nombres[0]]
    otras = {nombre: _df_a_filas(r["tablas"][nombre]) for nombre in nombres[1:]}

    return {
        "necesidad": n,
        "pregunta": r["pregunta"],
        "respuesta_clave": r["respuesta_clave"],
        "parametros_usados": _nativo(r.get("parametros", {})),
        "sql": r["sql"],
        "columnas": [str(c) for c in principal.columns],
        "resultado": _df_a_filas(principal),
        "tabla_principal": nombres[0],
        "otras_tablas": otras,
        "error": None,
        "fuente": FUENTE,
        "generado_en": datetime.now().isoformat(timespec="seconds"),
    }
