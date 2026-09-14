"""
LLM provider abstraction for the GridGuard AI briefing layer.

GridGuard is provider-agnostic.  Any OpenAI-compatible endpoint works —
hosted services (OpenAI, Groq, Together AI, …) or self-hosted servers
(Ollama, llama.cpp, vLLM, …).  IBM watsonx.ai is available as an optional
secondary path but is not required.

Providers
---------
LLMProvider      — Protocol (structural interface) every provider must satisfy.
OpenAIProvider   — Primary runtime provider.  Speaks the OpenAI chat-completions
                   API over plain HTTPS; works with any compatible endpoint.
                   Requires the ``openai`` package at runtime only.
WatsonxProvider  — Optional IBM watsonx.ai provider using ``ibm_watsonx_ai``
                   SDK.  Not a hard dependency; only imported when used.
MockProvider     — Deterministic mock for tests and offline use.  No network
                   calls; no external dependencies.

Adding a new provider
---------------------
1. Create a class with a ``generate(prompt: str) -> str`` method.
2. Pass an instance to ``BriefingService`` directly, or register it in the
   ``create_provider`` factory below.

The external SDKs (openai, ibm_watsonx_ai) are imported lazily — only when
the corresponding provider is instantiated.  The rest of the codebase never
imports them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .config import BriefingConfig


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMProvider(Protocol):
    """
    Structural interface every LLM provider must satisfy.

    A provider takes a fully-formed prompt string and returns the model's
    generated text.  Prompt construction and context injection are handled
    by the caller (``BriefingService`` + ``prompts.py``); the provider is
    only responsible for the inference call.
    """

    def generate(self, prompt: str) -> str:
        """
        Send *prompt* to the underlying model and return the generated text.

        Parameters
        ----------
        prompt:
            The complete prompt string (system context + grounded data +
            operator question).

        Returns
        -------
        str
            The model's response text, stripped of leading/trailing whitespace.

        Raises
        ------
        LLMProviderError
            If the underlying API call fails.
        """
        ...


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider call fails."""


# ---------------------------------------------------------------------------
# Mock provider (for tests and offline use)
# ---------------------------------------------------------------------------

class MockProvider:
    """
    Deterministic mock LLM provider.

    Returns a canned response that includes the asset ID and key scores
    extracted from the prompt so that tests can assert on grounded content
    without any network call.

    The response format mirrors what a real model would produce for a concise
    briefing, so the same test assertions apply when a live provider is
    swapped in.
    """

    def __init__(self, fixed_response: str | None = None) -> None:
        """
        Parameters
        ----------
        fixed_response:
            If set, every ``generate()`` call returns this exact string.
            If ``None`` (default), the mock synthesises a minimal grounded
            response by echoing the asset ID and risk level from the prompt.
        """
        self._fixed_response = fixed_response
        self.last_prompt: str = ""    # recorded for test assertions
        self.call_count: int = 0      # recorded for test assertions

    def generate(self, prompt: str) -> str:
        """Return a canned or synthesised response without any network call."""
        self.last_prompt = prompt
        self.call_count += 1

        if self._fixed_response is not None:
            return self._fixed_response

        return self._synthesise(prompt)

    @staticmethod
    def _synthesise(prompt: str) -> str:
        """
        Extract asset_id, risk_level, and overall_risk from the injected
        JSON block and build a minimal realistic-looking briefing.

        Handles both prompt formats:
        - Structured prompts:      [ASSET DATA] … [END ASSET DATA]
        - Conversational prompts:  [ASSET CONTEXT — ID] … [END ASSET CONTEXT]
        """
        import re
        import json as _json

        # Try both block markers
        for pattern in [
            r"\[ASSET DATA\]\s*(\{.*?\})\s*\[END ASSET DATA\]",
            r"\[ASSET CONTEXT[^\]]*\]\s*(\{.*?\})\s*\[END ASSET CONTEXT\]",
        ]:
            match = re.search(pattern, prompt, re.DOTALL)
            if match:
                try:
                    data = _json.loads(match.group(1))
                    asset_id = data.get("asset_id", "UNKNOWN")
                    risk_level = data.get("risk_level", "Unknown")
                    overall_risk = data.get("overall_risk", 0.0)
                    dominant = data.get("dominant_factor_label", "unknown factor")
                    return (
                        f"{asset_id} is currently rated {risk_level} with an overall "
                        f"risk score of {overall_risk}/100. The primary driver is "
                        f"{dominant}. Inspection is recommended based on the "
                        f"asset data provided. [MockProvider response]"
                    )
                except Exception:
                    pass

        return "[MockProvider] Briefing generated from provided asset data."


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (primary runtime provider)
# ---------------------------------------------------------------------------

class OpenAIProvider:
    """
    LLM provider that speaks the OpenAI chat-completions API.

    Works with any OpenAI-compatible endpoint, including:
    - OpenAI (https://api.openai.com/v1)
    - Ollama  (http://localhost:11434/v1)
    - llama.cpp server (http://localhost:8080/v1)
    - Groq   (https://api.groq.com/openai/v1)
    - Together AI, Fireworks, Anyscale, …
    - vLLM, LM Studio, and any other compatible server

    The ``openai`` package is imported lazily so it is only required when
    this provider is actually used.

    Parameters
    ----------
    config:
        ``BriefingConfig`` with ``llm_base_url``, ``llm_api_key``,
        ``model_id``, ``max_new_tokens``, and ``temperature`` populated.

    Raises
    ------
    ImportError
        If the ``openai`` package is not installed.
    LLMProviderError
        If ``llm_base_url`` is empty (required for non-OpenAI endpoints) or
        if the API call fails.
    """

    def __init__(self, config: BriefingConfig) -> None:
        try:
            import openai as _openai  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIProvider. "
                "Install it with: pip install openai"
            ) from exc

        if not config.llm_base_url and not config.llm_api_key:
            raise LLMProviderError(
                "OpenAIProvider requires LLM_BASE_URL or LLM_API_KEY to be set. "
                "For local servers (Ollama, llama.cpp) set LLM_BASE_URL. "
                "For hosted providers also set LLM_API_KEY. "
                "Use provider_name='mock' for offline use."
            )

        # Use the OpenAI default base URL when none is given (i.e. talking to
        # api.openai.com with only an API key set).
        base_url = config.llm_base_url or None  # None → openai SDK default

        self._client = _openai.OpenAI(
            api_key=config.llm_api_key or "no-key",  # local servers ignore key
            base_url=base_url,
        )
        self._config = config

    def generate(self, prompt: str) -> str:
        """
        Send *prompt* as a user message to the chat-completions endpoint and
        return the assistant's response text.

        The ``_SYSTEM_PREAMBLE`` from ``prompts.py`` is already embedded in
        the full prompt string; we send everything as a single user message
        so that providers without a system-role concept (some local models)
        still work correctly.

        Raises
        ------
        LLMProviderError
            If the API call fails for any reason.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._config.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self._config.max_new_tokens,
                temperature=self._config.temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            raise LLMProviderError(
                f"OpenAI-compatible API call failed "
                f"(model={self._config.model_id}, "
                f"base_url={self._config.llm_base_url or 'default'}): {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# IBM watsonx.ai provider (optional)
# ---------------------------------------------------------------------------

class WatsonxProvider:
    """
    Optional IBM watsonx.ai provider using the ``ibm_watsonx_ai`` SDK.

    This provider is not required for GridGuard to run.  Use it when you
    already have watsonx.ai credentials and prefer the IBM-managed inference
    service over a self-hosted or third-party OpenAI-compatible endpoint.

    The SDK and credentials are only required at runtime when this class is
    instantiated — the rest of the codebase has no dependency on it.

    Parameters
    ----------
    config:
        ``BriefingConfig`` with ``watsonx_api_key``, ``watsonx_project_id``,
        ``watsonx_url``, ``model_id``, ``max_new_tokens``, and
        ``temperature`` populated.

    Raises
    ------
    ImportError
        If ``ibm_watsonx_ai`` is not installed.
    LLMProviderError
        If credentials are missing or the API call fails.
    """

    def __init__(self, config: BriefingConfig) -> None:
        try:
            from ibm_watsonx_ai import Credentials              # type: ignore[import]
            from ibm_watsonx_ai.foundation_models import ModelInference  # type: ignore[import]
            from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "ibm_watsonx_ai is required for WatsonxProvider. "
                "Install it with: pip install ibm-watsonx-ai"
            ) from exc

        if not config.watsonx_api_key:
            raise LLMProviderError(
                "WATSONX_API_KEY is not set. "
                "Provide credentials or use provider_name='openai' / 'mock'."
            )
        if not config.watsonx_project_id:
            raise LLMProviderError(
                "WATSONX_PROJECT_ID is not set. "
                "Provide credentials or use provider_name='openai' / 'mock'."
            )

        credentials = Credentials(
            url=config.watsonx_url,
            api_key=config.watsonx_api_key,
        )
        self._model = ModelInference(
            model_id=config.model_id,
            credentials=credentials,
            project_id=config.watsonx_project_id,
            params={
                GenParams.MAX_NEW_TOKENS: config.max_new_tokens,
                GenParams.TEMPERATURE: config.temperature,
                GenParams.DECODING_METHOD: "greedy" if config.temperature == 0.0 else "sample",
            },
        )
        self._config = config

    def generate(self, prompt: str) -> str:
        """
        Send *prompt* to the configured watsonx model and return the response.

        Raises
        ------
        LLMProviderError
            If the API call fails for any reason.
        """
        try:
            response = self._model.generate_text(prompt=prompt)
            return response
        except Exception as exc:
            raise LLMProviderError(
                f"watsonx API call failed for model {self._config.model_id}: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_provider(config: BriefingConfig) -> LLMProvider:
    """
    Instantiate the correct provider from a ``BriefingConfig``.

    Supported ``provider_name`` values
    ------------------------------------
    ``"openai"``    — ``OpenAIProvider`` (requires ``openai`` package +
                      ``LLM_BASE_URL`` and/or ``LLM_API_KEY``)
    ``"watsonx"``   — ``WatsonxProvider`` (requires ``ibm_watsonx_ai`` +
                      watsonx credentials; optional)
    ``"mock"``      — ``MockProvider`` (no dependencies; deterministic)

    Parameters
    ----------
    config:
        Fully populated ``BriefingConfig``.

    Returns
    -------
    LLMProvider
        Ready-to-use provider instance.

    Raises
    ------
    ValueError
        If ``config.provider_name`` is not a recognised value.
    """
    name = config.provider_name.lower().strip()
    if name == "mock":
        return MockProvider()
    if name == "openai":
        return OpenAIProvider(config)
    if name == "watsonx":
        return WatsonxProvider(config)
    raise ValueError(
        f"Unknown provider_name '{config.provider_name}'. "
        "Supported values: 'openai', 'watsonx', 'mock'."
    )
