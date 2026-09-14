"""
BriefingService — the main entry point for the GridGuard AI briefing layer.

The service takes structured risk-engine outputs, builds a grounded context,
selects the appropriate prompt template, and calls the configured LLM provider.

Design principle
----------------
The service is a thin orchestrator.  It does not contain any business logic:
- Risk calculation stays in ``risk_engine``
- Grounding stays in ``context_builder``
- Prompt text stays in ``prompts``
- Model calls stay in ``provider``

Usage — conversational (primary)
---------------------------------
    from ai_briefing import BriefingService, BriefingConfig, ConversationTurn
    from ai_briefing.context_builder import BriefingContextBuilder

    service = BriefingService.from_config(BriefingConfig.from_env())
    ctx = BriefingContextBuilder.build(result, inputs)

    history: list[ConversationTurn] = []
    br = service.chat("What's wrong with TX-007?", history=history, ctx=ctx)
    history.append(ConversationTurn("user", "What's wrong with TX-007?"))
    history.append(ConversationTurn("assistant", br.text))

    br2 = service.chat("Why is the weather such a big deal?", history=history, ctx=ctx)
    # → model reads history and answers the follow-up without repeating the intro

Usage — structured (existing API, unchanged)
---------------------------------------------
    result = service.brief(risk_result, risk_inputs)
    result = service.why_risk_level(risk_result, risk_inputs)
    result = service.risk_factors(risk_result, risk_inputs)
    result = service.inspection_recommendation(risk_result, risk_inputs)
    result = service.prioritise([(risk_result_a, risk_inputs_a), ...])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from risk_engine.models import RiskInputs, RiskResult

from .config import BriefingConfig
from .context_builder import AssetRegistryInfo, BriefingContext, BriefingContextBuilder
from .provider import LLMProvider, create_provider
from .prompts import (
    concise_briefing_prompt,
    conversational_prompt,
    inspection_recommendation_prompt,
    prioritisation_prompt,
    risk_factors_prompt,
    why_risk_level_prompt,
)


# ---------------------------------------------------------------------------
# Conversation history type
# ---------------------------------------------------------------------------

@dataclass
class ConversationTurn:
    """
    One turn in an operator–assistant conversation.

    Attributes
    ----------
    role:
        ``"user"`` for operator messages, ``"assistant"`` for model replies.
    content:
        The text of the turn.
    """

    role: str    # "user" | "assistant"
    content: str


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

class BriefingType(str, Enum):
    """Supported briefing query types."""

    CONCISE_BRIEFING           = "concise_briefing"
    WHY_RISK_LEVEL             = "why_risk_level"
    RISK_FACTORS               = "risk_factors"
    INSPECTION_RECOMMENDATION  = "inspection_recommendation"
    PRIORITISATION             = "prioritisation"
    CONVERSATIONAL             = "conversational"


@dataclass
class BriefingResult:
    """
    The complete result of one briefing request.

    Attributes
    ----------
    text:
        The LLM's generated response.
    briefing_type:
        Which type of briefing was requested.
    asset_ids:
        The asset ID(s) that were included in this briefing.
    overall_risks:
        Mapping of asset_id → overall_risk for quick reference.
    risk_levels:
        Mapping of asset_id → risk_level string for quick reference.
    prompt_used:
        The full prompt that was sent to the LLM (useful for debugging
        and audit trails).
    """

    text: str
    briefing_type: BriefingType
    asset_ids: list[str]
    overall_risks: dict[str, float] = field(default_factory=dict)
    risk_levels: dict[str, str] = field(default_factory=dict)
    prompt_used: str = ""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BriefingService:
    """
    Orchestrates the full AI briefing pipeline.

    Parameters
    ----------
    provider:
        Any object satisfying the ``LLMProvider`` protocol.
    include_prompt_in_result:
        If ``True``, the ``prompt_used`` field of ``BriefingResult`` is
        populated.  Useful for debugging; may be disabled in production to
        reduce log volume.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        include_prompt_in_result: bool = True,
    ) -> None:
        self._provider = provider
        self._include_prompt = include_prompt_in_result

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: BriefingConfig,
        *,
        include_prompt_in_result: bool = True,
    ) -> "BriefingService":
        """
        Construct a ``BriefingService`` from a ``BriefingConfig``.

        This is the most common way to instantiate the service in production.
        For tests, pass a ``MockProvider`` instance directly to ``__init__``.
        """
        provider = create_provider(config)
        return cls(provider, include_prompt_in_result=include_prompt_in_result)

    # ------------------------------------------------------------------
    # Single-asset briefing methods
    # ------------------------------------------------------------------

    def brief(
        self,
        result: RiskResult,
        inputs: RiskInputs,
        *,
        registry: Optional[AssetRegistryInfo] = None,
    ) -> BriefingResult:
        """
        Generate a concise 2–4 sentence operator briefing for one asset.

        This is the primary method for dashboard cards and daily briefings.

        Parameters
        ----------
        result:
            Output of ``score_asset(inputs)``.
        inputs:
            The same ``RiskInputs`` passed to ``score_asset()``.
        registry:
            Optional asset registry metadata (type, notes).

        Returns
        -------
        BriefingResult
            Generated briefing text with grounding metadata.
        """
        ctx = BriefingContextBuilder.build(result, inputs, registry=registry)
        prompt = concise_briefing_prompt(ctx)
        return self._call(prompt, BriefingType.CONCISE_BRIEFING, [ctx])

    def why_risk_level(
        self,
        result: RiskResult,
        inputs: RiskInputs,
        *,
        registry: Optional[AssetRegistryInfo] = None,
    ) -> BriefingResult:
        """
        Explain why an asset has reached its current risk classification.

        Suitable for: "Why is T-007 Critical?"

        Parameters
        ----------
        result:
            Output of ``score_asset(inputs)``.
        inputs:
            The same ``RiskInputs`` passed to ``score_asset()``.
        registry:
            Optional asset registry metadata.

        Returns
        -------
        BriefingResult
            Explanation text with grounding metadata.
        """
        ctx = BriefingContextBuilder.build(result, inputs, registry=registry)
        prompt = why_risk_level_prompt(ctx)
        return self._call(prompt, BriefingType.WHY_RISK_LEVEL, [ctx])

    def risk_factors(
        self,
        result: RiskResult,
        inputs: RiskInputs,
        *,
        registry: Optional[AssetRegistryInfo] = None,
    ) -> BriefingResult:
        """
        List the key factors driving an asset's risk score.

        Suitable for: "What factors are driving this asset's risk?"

        Parameters
        ----------
        result:
            Output of ``score_asset(inputs)``.
        inputs:
            The same ``RiskInputs`` passed to ``score_asset()``.
        registry:
            Optional asset registry metadata.

        Returns
        -------
        BriefingResult
            Bulleted factor list with grounding metadata.
        """
        ctx = BriefingContextBuilder.build(result, inputs, registry=registry)
        prompt = risk_factors_prompt(ctx)
        return self._call(prompt, BriefingType.RISK_FACTORS, [ctx])

    def inspection_recommendation(
        self,
        result: RiskResult,
        inputs: RiskInputs,
        *,
        registry: Optional[AssetRegistryInfo] = None,
    ) -> BriefingResult:
        """
        Recommend whether and when an asset should be inspected.

        Suitable for: "Which assets should we inspect today?"
        (call once per candidate asset, then aggregate by urgency)

        Parameters
        ----------
        result:
            Output of ``score_asset(inputs)``.
        inputs:
            The same ``RiskInputs`` passed to ``score_asset()``.
        registry:
            Optional asset registry metadata.

        Returns
        -------
        BriefingResult
            Inspection recommendation text with grounding metadata.
        """
        ctx = BriefingContextBuilder.build(result, inputs, registry=registry)
        prompt = inspection_recommendation_prompt(ctx)
        return self._call(prompt, BriefingType.INSPECTION_RECOMMENDATION, [ctx])

    # ------------------------------------------------------------------
    # Multi-asset prioritisation
    # ------------------------------------------------------------------

    def prioritise(
        self,
        assets: list[tuple[RiskResult, RiskInputs]],
        *,
        registries: Optional[list[Optional[AssetRegistryInfo]]] = None,
    ) -> BriefingResult:
        """
        Rank multiple assets by inspection priority.

        Suitable for: "Which assets should we inspect today?" (fleet view)

        Parameters
        ----------
        assets:
            List of (RiskResult, RiskInputs) tuples to rank.
        registries:
            Optional parallel list of ``AssetRegistryInfo`` objects,
            one per asset.  Pass ``None`` elements where registry data is
            unavailable.

        Returns
        -------
        BriefingResult
            Ranked inspection list with grounding metadata.
        """
        if not assets:
            return BriefingResult(
                text="No assets provided for prioritisation.",
                briefing_type=BriefingType.PRIORITISATION,
                asset_ids=[],
            )

        regs: list[Optional[AssetRegistryInfo]] = (
            registries if registries is not None
            else [None] * len(assets)
        )

        contexts = [
            BriefingContextBuilder.build(result, inputs, registry=reg)
            for (result, inputs), reg in zip(assets, regs)
        ]

        prompt = prioritisation_prompt(contexts)
        return self._call(prompt, BriefingType.PRIORITISATION, contexts)

    # ------------------------------------------------------------------
    # Conversational interface
    # ------------------------------------------------------------------

    def chat(
        self,
        question: str,
        *,
        history: Optional[list[ConversationTurn]] = None,
        ctx: Optional[BriefingContext] = None,
        fleet_summary: str = "",
    ) -> BriefingResult:
        """
        Answer an operator message conversationally.

        This is the primary entry point for the UI's chat panel.  Unlike the
        structured ``brief()`` / ``why_risk_level()`` / etc. methods, ``chat``
        lets the model adapt its response length and tone to what the operator
        actually said — follow-ups, casual reactions, one-liner requests — and
        maintains context across turns via the ``history`` list.

        The grounding contract is identical to the structured methods: the
        model only sees data from the risk engine via ``ctx`` (or the
        ``fleet_summary`` for fleet-wide questions).

        Parameters
        ----------
        question:
            The operator's current message.
        history:
            Ordered list of previous turns (oldest first), or ``None`` / ``[]``
            for the first message.  The caller is responsible for appending the
            new user turn and the returned ``text`` as an assistant turn after
            each call so the next call sees the full history.
        ctx:
            Grounded asset context for the currently selected asset.  Pass
            ``None`` for fleet-wide questions.
        fleet_summary:
            Short plaintext summary of fleet state injected when ``ctx`` is
            ``None`` so the model still has grounded data to reason over.

        Returns
        -------
        BriefingResult
            The model's response with ``briefing_type == BriefingType.CONVERSATIONAL``.
        """
        prompt = conversational_prompt(
            question=question,
            history=history or [],
            ctx=ctx,
            fleet_summary=fleet_summary,
        )
        contexts: list[BriefingContext] = [ctx] if ctx is not None else []
        return self._call(prompt, BriefingType.CONVERSATIONAL, contexts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call(
        self,
        prompt: str,
        briefing_type: BriefingType,
        contexts: list[BriefingContext],
    ) -> BriefingResult:
        """Build the BriefingResult from a prompt and provider call."""
        text = self._provider.generate(prompt)

        return BriefingResult(
            text=text,
            briefing_type=briefing_type,
            asset_ids=[ctx.asset_id for ctx in contexts],
            overall_risks={ctx.asset_id: ctx.overall_risk for ctx in contexts},
            risk_levels={ctx.asset_id: ctx.risk_level for ctx in contexts},
            prompt_used=prompt if self._include_prompt else "",
        )
