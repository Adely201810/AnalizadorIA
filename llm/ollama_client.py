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
import uuid
from dataclasses import dataclass, field
from typing import Any

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Modelo objetivo (ver docs/DEPLOY.md para instrucciones de descarga).
# Alternativas más ligeras/pesadas: "mistral:7b-instruct-q4_K_M", "qwen2.5:7b-instruct-q4_K_M".
# Etapa 3 (D-31): qwen2.5-coder pasa a ser el modelo por defecto por la regla establecida (mejor en
# DESARROLLO y no peor en PRUEBA_2). Revertir: OLLAMA_MODEL=llama3.1:8b-instruct-q4_K_M.
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M")

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


# Juez iterativo (Fase 2, D-33): Ollama recorta el prompt EN SILENCIO si no cabe en num_ctx.
# Si prompt + num_predict deja menos de este margen libre, se corta con error explícito.
MARGEN_CONTEXTO = 0.10
CARACTERES_POR_TOKEN_CONSERVADOR = 2.5  # por exceso: el esquema auditado da 12,984 car / 3,329 tokens ≈ 3.9


class ContextoInsuficienteError(RuntimeError):
    """El prompt + num_predict no cabe en num_ctx con el margen exigido: Ollama lo truncaría."""


def verificar_margen_contexto(tokens_prompt: int, num_predict: int, num_ctx: int,
                              margen: float = MARGEN_CONTEXTO, origen: str = "") -> None:
    limite = (1 - margen) * num_ctx
    if tokens_prompt + num_predict > limite:
        raise ContextoInsuficienteError(
            f"{origen or 'prompt'}: {tokens_prompt} tokens de prompt + {num_predict} de num_predict = "
            f"{tokens_prompt + num_predict} > {limite:.0f} ({100 * (1 - margen):.0f} % de num_ctx={num_ctx}). "
            "Ollama recortaría el prompt en silencio: sube num_ctx o acorta el contexto."
        )


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

    # --- Juez iterativo (Fase 2-3). No cambia generate(): el chat sigue igual. ---------------

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = requests.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            raise OllamaError(f"No se pudo conectar a Ollama en {self.host}.") from exc
        except requests.exceptions.Timeout as exc:
            raise OllamaError(f"Ollama no respondió en {self.timeout}s.") from exc
        if resp.status_code != 200:
            raise OllamaError(f"Ollama respondió con error {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def contar_tokens(self, texto: str, keep_alive: str | None = None) -> int:
        """Tokens reales de `texto` con el tokenizador del modelo (raw, num_predict=1).
        Un prefijo único evita que la caché de prefijos de Ollama descuente tokens."""
        marca = f"[{uuid.uuid4().hex[:8]}]\n"

        def pec(t: str) -> int:
            p = {"model": self.model, "prompt": t, "raw": True, "stream": False,
                 "options": {"num_predict": 1, "num_ctx": self.num_ctx, "temperature": 0}}
            if keep_alive:
                p["keep_alive"] = keep_alive
            return int(self._post(p)["prompt_eval_count"])

        return pec(marca + texto) - pec(marca)

    def generate_detallado(
        self,
        prompt: str,
        system: str | None = None,
        num_predict: int = 400,
        temperature: float | None = None,
        seed: int | None = None,
        formato: dict | str | None = None,
        keep_alive: str | None = None,
        tokens_system: int | None = None,
    ) -> dict[str, Any]:
        """Como generate(), pero devuelve el JSON completo de Ollama (prompt_eval_count,
        load_duration, ...) y admite `format` (JSON schema), `seed` y `keep_alive`.

        Guarda de truncamiento: si se da `tokens_system` (medido con contar_tokens), ANTES de
        llamar se estima el total (system + prompt por exceso + plantilla de chat) y se corta si
        no deja el margen. DESPUÉS se repite con prompt_eval_count (que puede ser menor por la
        caché de prefijos, así que se usa el máximo de ambas cifras)."""
        estimado = None
        if tokens_system is not None:
            estimado = tokens_system + int(len(prompt) / CARACTERES_POR_TOKEN_CONSERVADOR) + 64
            verificar_margen_contexto(estimado, num_predict, self.num_ctx, origen="antes de llamar")
        options: dict[str, Any] = {
            "num_ctx": self.num_ctx,
            "num_predict": num_predict,
            "temperature": self.temperature if temperature is None else temperature,
        }
        if seed is not None:
            options["seed"] = seed
        payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False, "options": options}
        if system:
            payload["system"] = system
        if formato is not None:
            payload["format"] = formato
        if keep_alive:
            payload["keep_alive"] = keep_alive
        data = self._post(payload)
        reportado = int(data.get("prompt_eval_count") or 0)
        verificar_margen_contexto(max(reportado, estimado or 0), num_predict, self.num_ctx,
                                  origen="según Ollama")
        data["response"] = (data.get("response") or "").strip()
        data["tokens_prompt_estimados"] = estimado
        return data

    def procesos_cargados(self) -> list[dict[str, Any]]:
        """/api/ps: modelos cargados con size y size_vram (size_vram < size = parte en CPU)."""
        r = requests.get(f"{self.host}/api/ps", timeout=10)
        r.raise_for_status()
        return r.json().get("models", [])
