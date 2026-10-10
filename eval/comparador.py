"""
Árbitro determinista de la evaluación: compara el resultado del SQL del modelo
contra el resultado del SQL de REFERENCIA ejecutado sobre la misma base.

Reglas (documentadas también en docs/FASE_03.md):
  1. Mismo número de filas que la referencia.
  2. Cada columna de la referencia con tipo (`tipos_columnas` en el oráculo;
     `null` = columna que no se compara) debe corresponder a una columna
     DISTINTA del modelo, con todos sus valores dentro de la tolerancia de su
     tipo. El modelo puede devolver columnas extra; el nombre y la posición de
     las columnas no importan.
  3. Si `orden_importa` es true, las filas se comparan en orden; si no, se
     comparan como conjunto (se ordenan ambos lados por las columnas comparadas).

Tolerancias por tipo (sobre la diferencia absoluta d = |modelo - referencia|):
  - conteo:      exacto (d == 0).
  - dinero:      d <= 0.01 (un centavo) o d <= 0.1 % de la referencia.
  - porcentaje:  d <= 0.05 puntos porcentuales. También se acepta el valor en
                 escala de fracción (0.0304 para 3.04 %) si ×100 cumple lo mismo.
  - decimal:     d <= 0.01 (la referencia está redondeada a 2 decimales; cubre
                 días, calificaciones y otros promedios).
  - texto:       igualdad exacta, sin distinguir mayúsculas ni espacios en los
                 extremos.
"""
from __future__ import annotations

from dataclasses import dataclass

TIPOS_VALIDOS = {"conteo", "dinero", "porcentaje", "decimal", "texto"}

TOL_DINERO_ABS = 0.01
TOL_DINERO_REL = 0.001
TOL_PORCENTAJE = 0.05
TOL_DECIMAL = 0.01


@dataclass
class Veredicto:
    correcto: bool
    motivo: str


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def valor_coincide(modelo, referencia, tipo: str) -> bool:
    if referencia is None:
        return modelo is None
    if tipo == "texto":
        return modelo is not None and str(modelo).strip().lower() == str(referencia).strip().lower()
    m, r = _num(modelo), _num(referencia)
    if m is None or r is None:
        return False
    d = abs(m - r)
    if tipo == "conteo":
        return d == 0
    if tipo == "dinero":
        return d <= TOL_DINERO_ABS or (r != 0 and d / abs(r) <= TOL_DINERO_REL)
    if tipo == "porcentaje":
        return d <= TOL_PORCENTAJE or abs(m * 100 - r) <= TOL_PORCENTAJE
    if tipo == "decimal":
        return d <= TOL_DECIMAL
    raise ValueError(f"tipo de columna desconocido: {tipo!r}")


def _clave_orden(v):
    """Clave para ordenar filas de forma estable entre tipos mezclados."""
    n = _num(v)
    return (0, n, "") if n is not None else (1, 0.0, str(v).strip().lower())


def _columna_coincide(filas_m, k, filas_r, j, tipo) -> bool:
    return all(valor_coincide(fm[k], fr[j], tipo) for fm, fr in zip(filas_m, filas_r))


def _buscar_asignacion(filas_m, filas_r, necesarias, tipos, usadas, i):
    """Backtracking: asigna a cada columna necesaria de la referencia una
    columna distinta del modelo que coincida en todas las filas."""
    if i == len(necesarias):
        return {}
    j = necesarias[i]
    for k in range(len(filas_m[0]) if filas_m else 0):
        if k in usadas or not _columna_coincide(filas_m, k, filas_r, j, tipos[j]):
            continue
        resto = _buscar_asignacion(filas_m, filas_r, necesarias, tipos, usadas | {k}, i + 1)
        if resto is not None:
            return {j: k, **resto}
    return None


def comparar(
    filas_modelo: list[tuple],
    filas_referencia: list[tuple],
    tipos_columnas: list[str | None],
    orden_importa: bool = False,
) -> Veredicto:
    if len(tipos_columnas) != (len(filas_referencia[0]) if filas_referencia else len(tipos_columnas)):
        raise ValueError("tipos_columnas no coincide con las columnas de la referencia")
    for t in tipos_columnas:
        if t is not None and t not in TIPOS_VALIDOS:
            raise ValueError(f"tipo de columna desconocido: {t!r}")
    necesarias = [j for j, t in enumerate(tipos_columnas) if t is not None]
    if not necesarias:
        raise ValueError("el oráculo no marca ninguna columna para comparar")

    filas_m = [tuple(f) for f in filas_modelo]
    filas_r = [tuple(f) for f in filas_referencia]
    if len(filas_m) != len(filas_r):
        return Veredicto(False, f"filas: el modelo devolvió {len(filas_m)}, la referencia tiene {len(filas_r)}")
    if not filas_r:
        return Veredicto(True, "ambos sin filas")
    n_cols_m = len(filas_m[0])
    if n_cols_m < len(necesarias):
        return Veredicto(False, f"columnas: el modelo devolvió {n_cols_m}, se necesitan al menos {len(necesarias)}")

    if orden_importa:
        asignacion = _buscar_asignacion(filas_m, filas_r, necesarias, tipos_columnas, frozenset(), 0)
    else:
        # Sin orden: se ordena la referencia por sus columnas comparadas y, para
        # cada posible asignación de columnas, el modelo por las columnas asignadas.
        filas_r = sorted(filas_r, key=lambda f: [_clave_orden(f[j]) for j in necesarias])
        asignacion = None
        from itertools import permutations

        for cols in permutations(range(n_cols_m), len(necesarias)):
            ordenadas = sorted(filas_m, key=lambda f: [_clave_orden(f[k]) for k in cols])
            if all(_columna_coincide(ordenadas, k, filas_r, j, tipos_columnas[j]) for j, k in zip(necesarias, cols)):
                asignacion = dict(zip(necesarias, cols))
                break

    if asignacion is None:
        return Veredicto(False, "valores: ninguna asignación de columnas del modelo coincide con la referencia dentro de tolerancia")
    return Veredicto(True, f"coincide (columna referencia -> columna modelo: {asignacion})")
