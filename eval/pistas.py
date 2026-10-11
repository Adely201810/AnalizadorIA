"""
Pistas entre intentos en la evaluación (Fase 7) y guarda contra fugas.

Cuando el árbitro rechaza un resultado, el siguiente intento recibe una pista
que dice QUÉ tipo de problema hubo, nunca cuál es la respuesta:
  - "ninguno":  solo que el resultado no es correcto (control sin feedback).
  - "generico": el tipo de discrepancia (nº de filas, columnas o valores), sin números.
  - "juez":     lo anterior + el diagnóstico del enfoque del juez-LLM, que no
                conoce la referencia.

Defensa en profundidad: `censurar()` reemplaza en la pista cualquier forma
escrita de los valores de la referencia (y derivados evidentes: redondeos,
separadores de miles, escala ×100 / ÷100) por "[valor omitido]".
"""
from __future__ import annotations

import re

MODOS = ("ninguno", "generico", "juez")
OMITIDO = "[valor omitido]"

PISTA_SIN_FEEDBACK = "El resultado de la consulta no es correcto. Genera una consulta distinta."


def motivo_generico(motivo_arbitro: str) -> str:
    """Traduce el motivo del árbitro (que puede incluir el nº de filas de la
    referencia) a una descripción SIN cifras de la referencia."""
    if motivo_arbitro.startswith("filas"):
        return "El número de filas del resultado no corresponde a lo que pide la pregunta."
    if motivo_arbitro.startswith("columnas"):
        return "Al resultado le faltan datos (columnas) que la pregunta pide explícitamente."
    return "El resultado tiene la forma esperada, pero sus valores no son los correctos: revisa la lógica del cálculo."


def construir_pista(modo: str, motivo_arbitro: str, diagnostico_juez: str | None = None) -> str:
    if modo == "ninguno":
        return PISTA_SIN_FEEDBACK
    pista = motivo_generico(motivo_arbitro)
    if modo == "juez" and diagnostico_juez:
        pista += f" Diagnóstico del revisor: {diagnostico_juez}"
    return pista


def _miles(entero: int, sep: str) -> str:
    return f"{entero:,}".replace(",", sep)


def formas_de_valor(valor) -> set[str]:
    """Formas en que un valor de la referencia podría aparecer escrito."""
    if valor is None or isinstance(valor, bool):
        return set()
    if isinstance(valor, str):
        return {valor.strip().lower()} if len(valor.strip()) >= 3 else set()
    formas: set[str] = set()
    for v in (float(valor), float(valor) * 100, float(valor) / 100):
        for dec in (0, 1, 2, 3):
            if dec == 0 and abs(v) < 10:
                continue  # enteros pequeños aparecen solos en cualquier texto ("5 categorías")
            if dec > 0 and abs(v) < 0.01:
                continue
            texto = f"{v:.{dec}f}"
            entero, _, decimales = texto.partition(".")
            formas.add(texto)
            formas.add(texto.replace(".", ","))
            if abs(v) >= 1000:
                n = int(entero.lstrip("-"))
                formas.add(_miles(n, ",") + (f".{decimales}" if decimales else ""))
                formas.add(_miles(n, ".") + (f",{decimales}" if decimales else ""))
    return formas


def valores_de_referencia(filas_referencia: list, tipos_columnas: list) -> list:
    """Valores de las columnas que el árbitro compara (las demás no se protegen)."""
    return [f[j] for f in filas_referencia for j, t in enumerate(tipos_columnas) if t is not None]


def fugas(texto: str, valores: list) -> list[str]:
    """Formas de valores de referencia presentes en `texto` (sin distinguir mayúsculas)."""
    bajo = texto.lower()
    encontradas = []
    for v in valores:
        for forma in formas_de_valor(v):
            patron = r"(?<![\w.,])" + re.escape(forma.lower()) + r"(?![\w]|[.,]\d)"
            if re.search(patron, bajo):
                encontradas.append(forma)
    return sorted(set(encontradas))


def censurar(texto: str, valores: list) -> tuple[str, list[str]]:
    encontradas = fugas(texto, valores)
    for forma in sorted(encontradas, key=len, reverse=True):
        texto = re.sub(r"(?<![\w.,])" + re.escape(forma) + r"(?![\w]|[.,]\d)", OMITIDO, texto, flags=re.I)
    return texto, encontradas
