"""
CLI interactivo para hacer preguntas en español sobre la base de datos de
e-commerce Olist, usando el pipeline Text-to-SQL de llm/text_to_sql.py.

Uso:
    python -m llm.cli
    python -m llm.cli "¿Cuál fue el mes con más ingresos netos en 2025?"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm.bitacora import BitacoraEsquema
from llm.juez import JuezLLM
from llm.ollama_client import OllamaClient
from llm.text_to_sql import answer_question


def _print_resultado(resultado):
    print(f"\nSQL generado:\n  {resultado.sql}")
    if resultado.error:
        print(f"\n⚠ {resultado.error}")
        return
    print(f"\nFilas obtenidas: {resultado.total_filas}")
    print(f"\nRespuesta:\n{resultado.respuesta}\n")
    if resultado.revision_sensatez:
        r = resultado.revision_sensatez
        estado = {True: "parece coherente", False: "posible problema"}.get(r["tiene_sentido"], "sin revisión")
        print(f"Revisión automática del SQL (no comprueba la cifra): {estado}. {r['motivo']}\n")


def main():
    client = OllamaClient()
    if not client.is_available():
        print(f"⚠ No se pudo conectar a Ollama en {client.host}. Ejecuta 'ollama serve' e intenta de nuevo.")
        sys.exit(1)
    print(f"Modelo: {client.model} | Ollama: {client.host}\n")
    bitacora = BitacoraEsquema()
    juez = JuezLLM(client)

    if len(sys.argv) > 1:
        pregunta = " ".join(sys.argv[1:])
        resultado = answer_question(pregunta, client=client, bitacora=bitacora, juez_sensatez=juez)
        _print_resultado(resultado)
        return

    print("Escribe tu pregunta sobre el marketplace Olist en español (o 'salir' para terminar).\n")
    while True:
        try:
            pregunta = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pregunta:
            continue
        if pregunta.lower() in ("salir", "exit", "quit"):
            break
        resultado = answer_question(pregunta, client=client, bitacora=bitacora, juez_sensatez=juez)
        _print_resultado(resultado)


if __name__ == "__main__":
    main()
