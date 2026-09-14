"""
GridGuard AI briefing layer.

This package translates structured, deterministic risk-engine results into
operator-facing natural-language explanations.  The LLM explains and reasons
over pre-computed scores; it never calculates risk scores itself.

GridGuard is provider-agnostic: any OpenAI-compatible endpoint works
(OpenAI, Groq, Ollama, llama.cpp, vLLM, …).  IBM watsonx.ai is available
as an optional secondary path.

Public API
----------
    BriefingService          — main entry point; call .brief(), .why_risk_level() etc.
    BriefingContext          — structured grounded context passed to the LLM
    BriefingContextBuilder   — assembles BriefingContext from RiskResult + RiskInputs
    LLMProvider              — protocol every provider must implement
    OpenAIProvider           — primary runtime provider (OpenAI-compatible endpoints)
    WatsonxProvider          — optional IBM watsonx.ai provider
    MockProvider             — deterministic mock for tests; no external API
    BriefingConfig           — provider + model configuration
    BriefingType             — enum of supported query types
    BriefingResult           — returned briefing with grounding metadata
"""

from .context_builder import BriefingContext, BriefingContextBuilder
from .provider import LLMProvider, OpenAIProvider, WatsonxProvider, MockProvider
from .config import BriefingConfig
from .service import BriefingService, BriefingType, BriefingResult, ConversationTurn

__all__ = [
    "BriefingContext",
    "BriefingContextBuilder",
    "LLMProvider",
    "OpenAIProvider",
    "WatsonxProvider",
    "MockProvider",
    "BriefingConfig",
    "BriefingService",
    "BriefingType",
    "BriefingResult",
    "ConversationTurn",
]
