"""
Cliente minimalista para la API local de Ollama (http://localhost:11434).

Pensado para hardware modesto (Ryzen 5 7000-series, 16 GB RAM totales):
  - Usa /api/generate en modo no-streaming (respuesta completa de una vez),
    lo cual es más simple de manejar que un stream y no cambia el uso de RAM.
  - Limita num_ctx y num_predict por defecto para no disparar el tamaño del
    KV-cache del modelo y no saturar la RAM compartida con el resto del sistema.
  - Expone timeouts explícitos: en hardware CPU-only, una respuesta puede
    tardar decenas de segundos; mejor fallar con un mensaje claro que colgarse.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Modelo objetivo (ver docs/DEPLOY.md para instrucciones de descarga).
# Alternativas más ligeras/pesadas: "mistral:7b-instruct-q4_K_M", "qwen2.5:7b-instruct-q4_K_M".
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")

# num_ctx: el esquema compacto (llm/schema_context.py) ya incluye notas,
# ejemplos few-shot y ahora 6 vistas -- 8192 da margen para eso + la pregunta +
# el contexto de reintento + resultados truncados, sin acercarse al límite en
# 16 GB compartidos (ver llm.schema_context.get_schema_context(), ~2000
# tokens con el esquema actual).
DEFAULT_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
# 300s: las preguntas abiertas se descomponen en varias sub-consultas + una
# síntesis integradora, y en CPU cada llamada puede tardar bastante.
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT", "300"))


class OllamaError(RuntimeError):
    """Error de comunicación con el servidor de Ollama (no disponible, timeout, etc.)."""


@dataclass
class OllamaClient:
    host: str = OLLAMA_HOST
    model: str = DEFAULT_MODEL
    num_ctx: int = DEFAULT_NUM_CTX
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    temperature: float = 0.1  # baja temperatura: queremos SQL determinista, no creativo

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        num_predict: int = 400,
        temperature: float | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Llama a /api/generate y devuelve el texto de respuesta completo (sin streaming)."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": self.num_ctx,
                "num_predict": num_predict,
                "temperature": self.temperature if temperature is None else temperature,
                **(options or {}),
            },
        }
        if system:
            payload["system"] = system

        try:
            resp = requests.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            raise OllamaError(
                f"No se pudo conectar a Ollama en {self.host}. "
                f"¿Está corriendo? Prueba con: ollama serve"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise OllamaError(
                f"Ollama no respondió en {self.timeout}s. En CPU esto puede pasar con prompts largos; "
                f"intenta con una pregunta más simple o sube OLLAMA_TIMEOUT."
            ) from exc

        if resp.status_code == 404:
            raise OllamaError(
                f"El modelo '{self.model}' no está descargado en Ollama. "
                f"Ejecuta: ollama pull {self.model}"
            )
        if resp.status_code != 200:
            raise OllamaError(f"Ollama respondió con error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        return data.get("response", "").strip()
