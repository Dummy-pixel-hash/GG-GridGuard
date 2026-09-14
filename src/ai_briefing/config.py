"""
BriefingConfig — provider and model configuration for the GridGuard AI briefing layer.

GridGuard is a standalone application.  Its LLM layer is provider-agnostic:
any OpenAI-compatible endpoint works, including hosted services (OpenAI,
Together AI, Groq, …) and self-hosted servers (Ollama, llama.cpp, vLLM, …).

IBM watsonx.ai is supported as an optional secondary path for teams that
already have watsonx credentials, but it is not required.

Primary configuration (OpenAI-compatible)
------------------------------------------
LLM_BASE_URL      Base URL of the OpenAI-compatible inference endpoint.
                  Examples:
                    https://api.openai.com/v1
                    http://localhost:11434/v1        (Ollama)
                    http://localhost:8080/v1          (llama.cpp)
                    https://api.groq.com/openai/v1   (Groq)
LLM_API_KEY       API key for the endpoint.  Leave blank for local servers
                  that do not require authentication.
LLM_MODEL         Model name / deployment ID passed to the endpoint.
                  Example: "gpt-4o-mini", "llama3", "granite3-dense:8b"

Common generation parameters
-----------------------------
GRIDGUARD_LLM_MAX_TOKENS   Max tokens to generate (default: 512).
GRIDGUARD_LLM_TEMPERATURE  Sampling temperature (default: 0.2).

Provider selection
------------------
GRIDGUARD_LLM_PROVIDER  Selects the provider implementation:
    "openai"   — OpenAI-compatible HTTP provider (default when LLM_BASE_URL
                 or LLM_API_KEY is set).
    "watsonx"  — IBM watsonx.ai via ibm_watsonx_ai SDK (optional; requires
                 WATSONX_API_KEY + WATSONX_PROJECT_ID).
    "mock"     — Deterministic in-process mock; no network calls.  Used
                 automatically when no credentials/URL are configured.

Optional: IBM watsonx.ai credentials
--------------------------------------
WATSONX_API_KEY       IBM Cloud API key.
WATSONX_PROJECT_ID    watsonx.ai project ID.
WATSONX_URL           Inference endpoint (default: us-south.ml.cloud.ibm.com).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class BriefingConfig:
    """
    All settings needed to instantiate an LLM provider for briefings.

    Attributes
    ----------
    provider_name:
        Which provider implementation to use.  See module docstring.
        ``"openai"`` is the primary runtime provider; ``"mock"`` is used
        when no credentials are configured.
    model_id:
        The model identifier forwarded to the provider.
    llm_base_url:
        Base URL for OpenAI-compatible providers.  Required when
        ``provider_name == "openai"``.
    llm_api_key:
        API key for the endpoint.  May be empty for local servers that
        do not require authentication.
    max_new_tokens:
        Upper bound on generated tokens per briefing.
    temperature:
        Sampling temperature.  Low values (≤0.3) produce more
        deterministic, factual output — appropriate for operator briefings.
    watsonx_api_key:
        IBM Cloud API key.  Only used when ``provider_name == "watsonx"``.
    watsonx_project_id:
        watsonx.ai project ID.  Only used when ``provider_name == "watsonx"``.
    watsonx_url:
        watsonx.ai endpoint URL.  Only used when ``provider_name == "watsonx"``.
    """

    provider_name: str = "mock"
    model_id: str = "gpt-4o-mini"
    llm_base_url: str = ""
    llm_api_key: str = ""
    max_new_tokens: int = 512
    temperature: float = 0.2

    # Optional watsonx.ai credentials (only needed for provider_name="watsonx")
    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"

    @classmethod
    def from_env(cls) -> "BriefingConfig":
        """
        Construct a ``BriefingConfig`` by reading environment variables.

        Provider selection logic
        ------------------------
        1. If ``GRIDGUARD_LLM_PROVIDER`` is explicitly set, use that value.
        2. Otherwise, if ``LLM_API_KEY`` or ``LLM_BASE_URL`` is set,
           default to ``"openai"``.
        3. Otherwise, if ``WATSONX_API_KEY`` is set, default to
           ``"watsonx"``.
        4. Otherwise, default to ``"mock"`` (offline / CI safe).

        Returns
        -------
        BriefingConfig
            Ready-to-use configuration instance.
        """
        llm_api_key   = os.getenv("LLM_API_KEY", "")
        llm_base_url  = os.getenv("LLM_BASE_URL", "")
        watsonx_key   = os.getenv("WATSONX_API_KEY", "")

        if llm_api_key or llm_base_url:
            default_provider = "openai"
        elif watsonx_key:
            default_provider = "watsonx"
        else:
            default_provider = "mock"

        provider_name = os.getenv("GRIDGUARD_LLM_PROVIDER", default_provider)

        return cls(
            provider_name=provider_name,
            model_id=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            max_new_tokens=int(os.getenv("GRIDGUARD_LLM_MAX_TOKENS", "512")),
            temperature=float(os.getenv("GRIDGUARD_LLM_TEMPERATURE", "0.2")),
            watsonx_api_key=watsonx_key,
            watsonx_project_id=os.getenv("WATSONX_PROJECT_ID", ""),
            watsonx_url=os.getenv(
                "WATSONX_URL", "https://us-south.ml.cloud.ibm.com"
            ),
        )
