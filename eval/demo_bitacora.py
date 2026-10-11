"""
Demostración real de la bitácora de errores de esquema (Fase 10).

1. Control: la pregunta B SIN bitácora (¿comete el error de esquema?).
2. Pregunta A CON bitácora (provoca el error y lo registra).
3. Pregunta B CON bitácora (¿llega la corrección al prompt y se evita el error?).

Usa una bitácora en un archivo temporal propio (no toca runtime/ ni la base).

Uso: python -m eval.demo_bitacora --bitacora <ruta.json>
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from llm.bitacora import BitacoraEsquema
from llm.ollama_client import OllamaClient
from llm.text_to_sql import answer_question

PREGUNTA_A = "¿Qué porcentaje de los clientes únicos hizo más de un pedido válido (sin contar pedidos cancelados o no disponibles)?"
PREGUNTA_B = "¿Cuántos clientes únicos hicieron al menos un pedido entregado?"
_ERROR_ESQUEMA = re.compile(r"no such column|no such table|no tiene la columna|no existen en el esquema")


class ClienteQueRegistra(OllamaClient):
    """El cliente real de Ollama, que además guarda los prompts de generación de SQL."""

    def __init__(self):
        super().__init__()
        self.prompts_sql: list[str] = []

    def generate(self, prompt, system=None, **kw):
        if system and "generador de consultas SQL" in system:
            self.prompts_sql.append(prompt)
        return super().generate(prompt, system=system, **kw)


def correr(etiqueta: str, pregunta: str, bitacora: BitacoraEsquema | None) -> None:
    cliente = ClienteQueRegistra()
    r = answer_question(pregunta, client=cliente, usar_plantillas=False, bitacora=bitacora)
    print(f"\n=== {etiqueta} ===\nPregunta: {pregunta}")
    if bitacora is not None and cliente.prompts_sql:
        inyectado = "Errores de esquema cometidos" in cliente.prompts_sql[0]
        print(f"¿El 1.er prompt de SQL trae la bitácora?: {inyectado}")
        if inyectado:
            print("Fragmento inyectado:\n  " + cliente.prompts_sql[0].split("\n\n", 1)[1].replace("\n", "\n  "))
    for d in r.intentos_detalle:
        error_esquema = bool(_ERROR_ESQUEMA.search(d.get("detalle") or ""))
        print(f"  intento {d['intento']}: tipo={d['tipo']} | error de esquema={error_esquema} | "
              f"detalle={(d.get('detalle') or '')[:140]!r}")
        print(f"    SQL: {' '.join((d.get('sql') or '').split())[:220]}")
    print(f"Filas: {r.filas[:3]} | descompuesta: {bool(r.sub_consultas)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bitacora", required=True)
    args = ap.parse_args()
    ruta = Path(args.bitacora)
    if ruta.exists():
        ruta.unlink()
    bitacora = BitacoraEsquema(ruta)
    correr("1. CONTROL: pregunta B sin bitácora", PREGUNTA_B, None)
    correr("2. Pregunta A con bitácora (vacía al empezar)", PREGUNTA_A, bitacora)
    print("\nBitácora tras la pregunta A:\n" + json.dumps(bitacora.entradas(), ensure_ascii=False, indent=2))
    correr("3. Pregunta B con bitácora", PREGUNTA_B, bitacora)
    print("\nBitácora al final:\n" + json.dumps(bitacora.entradas(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
