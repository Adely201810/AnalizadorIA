"""
Desglosa la latencia de la llamada que genera el SQL (Fase 4): carga del
modelo, evaluación del prompt (proporcional a su tamaño) y generación de
tokens, usando los contadores que devuelve /api/generate de Ollama (el
cliente del proyecto los descarta).

Hace N llamadas seguidas con el MISMO system prompt que usa el pipeline
(esquema completo), para ver además si Ollama reutiliza el prefijo ya
evaluado entre llamadas, y una llamada de control con un system prompt mínimo.

Uso:
    python -m eval.medir_latencia                       # modelo por defecto
    python -m eval.medir_latencia --model qwen2.5-coder:7b-instruct-q4_K_M
"""
from __future__ import annotations

import argparse
import json

import requests

from llm.ollama_client import OllamaClient
from llm.schema_context import get_schema_context
from llm.text_to_sql import SQL_SYSTEM_PROMPT_TEMPLATE

PREGUNTAS = [
    "¿Qué porcentaje de los clientes únicos hizo más de un pedido válido?",
    "¿Qué mes tuvo más ingresos por ventas de pedidos válidos?",
    "¿Qué método de pago se usa en más pedidos válidos?",
]


def llamada(client: OllamaClient, system: str, prompt: str) -> dict:
    r = requests.post(f"{client.host}/api/generate", json={
        "model": client.model, "prompt": prompt, "system": system, "stream": False,
        "options": {"num_ctx": client.num_ctx, "num_predict": 350, "temperature": client.temperature},
    }, timeout=client.timeout).json()
    s = lambda k: round(r.get(k, 0) / 1e9, 2)  # ns -> s
    return {
        "total_s": s("total_duration"), "carga_s": s("load_duration"),
        "prompt_tokens": r.get("prompt_eval_count"), "prompt_eval_s": s("prompt_eval_duration"),
        "tokens_generados": r.get("eval_count"), "generacion_s": s("eval_duration"),
        "tok_s_prompt": round(r.get("prompt_eval_count", 0) / max(r.get("prompt_eval_duration", 1) / 1e9, 1e-9), 1),
        "tok_s_generacion": round(r.get("eval_count", 0) / max(r.get("eval_duration", 1) / 1e9, 1e-9), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    client = OllamaClient(model=args.model) if args.model else OllamaClient()
    system = SQL_SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema_context())
    print(f"modelo={client.model} num_ctx={client.num_ctx} | system prompt: {len(system)} caracteres")
    for i, p in enumerate(PREGUNTAS, start=1):
        print(f"llamada {i} (esquema completo): {json.dumps(llamada(client, system, 'Pregunta: ' + p), ensure_ascii=False)}")
    minimo = "Eres un generador de SQL para SQLite. Responde solo con SQL."
    print(f"control (system mínimo, {len(minimo)} caracteres): "
          f"{json.dumps(llamada(client, minimo, 'Pregunta: ' + PREGUNTAS[0]), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
