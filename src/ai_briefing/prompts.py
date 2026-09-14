"""
Prompt templates for the GridGuard AI briefing layer.

Each template function takes a ``BriefingContext`` and returns the full
prompt string that the LLM receives.  The context data is injected inline so
the model sees exactly the numbers it must reason over — no retrieval needed.

Grounding contract
------------------
Every prompt begins with an explicit system instruction that:
1. Identifies the model as a grid-operations analyst assistant.
2. States that all facts, scores, and measurements come from the provided
   structured data only.
3. Forbids invention of sensor values, incidents, or recommendations that are
   not supported by the provided context.

The system section and the factual context block are clearly separated from
the operator question so that they can be split into system / user roles if
the provider supports them.

Conversational prompts
----------------------
``conversational_prompt`` takes the full conversation history and the current
asset context so the model can answer follow-up questions, react to casual
messages, and adapt its response length — without restarting from scratch
each turn.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .context_builder import BriefingContext

if TYPE_CHECKING:
    from .service import ConversationTurn


# ---------------------------------------------------------------------------
# Shared preamble
# ---------------------------------------------------------------------------

_SYSTEM_PREAMBLE = """\
You are a concise grid-operations analyst assistant for GridGuard, a utility \
asset risk monitoring platform.

GROUNDING RULE: You must reason ONLY from the structured asset data provided \
in the [ASSET DATA] block below. Do NOT invent, estimate, or assume any sensor \
readings, scores, incidents, dates, or facility names that are not explicitly \
present in that block. If a piece of information is absent, say so rather than \
guessing.

Keep responses direct and operator-friendly. Avoid unnecessary hedging. \
Prioritise safety and actionability.\
"""

_CONVERSATIONAL_SYSTEM = """\
You are GridGuard's operator assistant — a sharp, practical grid-operations \
expert embedded in a live monitoring platform.

GROUNDING RULE: Every factual claim you make MUST be grounded in the \
[ASSET CONTEXT] block provided. Do NOT invent sensor readings, scores, \
incident dates, facility names, or any values not present in that block. \
If information is missing, say so plainly.

CONVERSATION RULES:
- Read the conversation history to understand what has already been discussed.
- Answer the CURRENT message only — do not repeat information from earlier \
turns unless the operator is asking for a recap.
- Match your response length and tone to the message:
    * Short question → concise, direct answer (1–3 sentences max).
    * Follow-up ("why?", "what about…") → address only the new question.
    * Casual reactions ("oh shit", "really?", "calm down") → respond \
naturally as a calm, knowledgeable colleague, no new risk report.
    * Request for brief ("1 liner", "tldr", "quick summary") → honour it.
    * Detailed request ("walk me through", "explain fully") → be thorough.
- Never generate an unsolicited full risk report if the operator is just \
reacting or asking a narrow follow-up.
- Always refer to the currently selected asset by name; do not ask the \
operator to clarify which asset when it is already in context.\
"""


def _format_context_block(ctx: BriefingContext) -> str:
    """Serialise BriefingContext as a readable JSON block for injection."""
    data = ctx.to_dict()
    return f"[ASSET DATA]\n{json.dumps(data, indent=2)}\n[END ASSET DATA]"


def _ranked_components_summary(ctx: BriefingContext) -> str:
    """Return a bullet list of components sorted by score (highest first)."""
    lines = []
    for name, score in ctx.components.as_ranked_list():
        from .context_builder import _COMPONENT_LABELS  # local import to avoid cycle
        label = _COMPONENT_LABELS.get(name, name)
        lines.append(f"  - {label}: {score:.1f}/100")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Template: concise asset briefing
# ---------------------------------------------------------------------------

def concise_briefing_prompt(ctx: BriefingContext) -> str:
    """
    Single-paragraph operator briefing for one asset.

    Suitable for a risk dashboard card or a daily briefing email.
    The model should produce 2–4 sentences covering:
    - Current risk level and overall score
    - The primary driver
    - A clear, actionable recommendation
    """
    return f"""{_SYSTEM_PREAMBLE}

{_format_context_block(ctx)}

TASK: Write a concise 2–4 sentence operator briefing for asset {ctx.asset_id}.

State the risk level and overall score, identify the primary risk driver \
from the component scores, and give one clear recommendation. Reference only \
the numbers provided above. Do not add caveats or disclaimers beyond what the \
data supports."""


# ---------------------------------------------------------------------------
# Template: why is this asset at its current risk level?
# ---------------------------------------------------------------------------

def why_risk_level_prompt(ctx: BriefingContext) -> str:
    """
    Explain why the asset has reached its current risk classification.

    Covers all significant component scores (those above 50) and how they
    combine to produce the overall score.
    """
    ranked = _ranked_components_summary(ctx)
    return f"""{_SYSTEM_PREAMBLE}

{_format_context_block(ctx)}

TASK: Explain in 3–5 sentences why {ctx.asset_id} is currently rated \
{ctx.risk_level} (overall risk {ctx.overall_risk}/100).

Component scores (highest to lowest):
{ranked}

Describe which components are elevated and why, referencing specific values \
from the asset data. Conclude with what the operator should prioritise. \
Do not reference scores or facts that are not in the asset data above."""


# ---------------------------------------------------------------------------
# Template: what factors are driving this asset's risk?
# ---------------------------------------------------------------------------

def risk_factors_prompt(ctx: BriefingContext) -> str:
    """
    Itemised breakdown of risk factors driving the overall score.

    The model should produce a short bulleted list, one item per elevated
    component, with a sentence explaining what is contributing.
    """
    return f"""{_SYSTEM_PREAMBLE}

{_format_context_block(ctx)}

TASK: List the key risk factors driving {ctx.asset_id}'s overall risk score \
of {ctx.overall_risk}/100 (risk level: {ctx.risk_level}).

For each component score above 40/100, write one bullet point that names the \
factor, states its score, and explains in plain language what is contributing \
to it based on the asset data above. Use only values explicitly provided. \
Order bullets from highest to lowest component score."""


# ---------------------------------------------------------------------------
# Template: should this asset be inspected today?
# ---------------------------------------------------------------------------

def inspection_recommendation_prompt(ctx: BriefingContext) -> str:
    """
    Recommend whether this asset should be inspected and with what urgency.

    Used when ranking assets for daily work orders.
    """
    return f"""{_SYSTEM_PREAMBLE}

{_format_context_block(ctx)}

TASK: Based solely on the asset data above, provide a concrete inspection \
recommendation for {ctx.asset_id}.

Answer: should this asset be inspected today, this week, or can it wait for \
scheduled maintenance? State the urgency clearly in the first sentence, then \
give 2–3 specific reasons drawn from the asset data. Reference exact scores \
and values where relevant. Do not recommend actions not supported by the data."""


# ---------------------------------------------------------------------------
# Template: multi-asset prioritisation list
# ---------------------------------------------------------------------------

def prioritisation_prompt(contexts: list[BriefingContext]) -> str:
    """
    Produce a ranked inspection list across multiple assets.

    Args:
        contexts: List of BriefingContext objects, one per asset to evaluate.
                  The caller is responsible for pre-filtering (e.g. only HIGH
                  and CRITICAL assets).

    Returns:
        Prompt string for a ranked list of assets with brief justifications.
    """
    asset_summaries = []
    for ctx in contexts:
        summary = (
            f"  Asset {ctx.asset_id} | {ctx.risk_level} | "
            f"overall: {ctx.overall_risk}/100 | "
            f"dominant: {ctx.dominant_factor_label} ({getattr(ctx.components, ctx.dominant_factor):.1f}) | "
            f"customers: {ctx.grid_impact.customers_served:,} | "
            f"critical facilities: {ctx.grid_impact.critical_facility_count} | "
            f"redundancy: {'yes' if ctx.grid_impact.has_redundant_path else 'no'}"
        )
        asset_summaries.append(summary)

    assets_block = "\n".join(asset_summaries)

    return f"""{_SYSTEM_PREAMBLE}

[ASSETS FOR PRIORITISATION]
{assets_block}
[END ASSETS]

TASK: Rank the above assets from highest to lowest inspection priority for \
today's work orders.

For each asset, write one line: rank, asset ID, risk level, overall score, \
and a single sentence explaining why it is ranked in that position. \
Base your reasoning only on the data provided above. Do not introduce \
external knowledge about specific locations or facilities."""


# ---------------------------------------------------------------------------
# Template: conversational / follow-up
# ---------------------------------------------------------------------------

def conversational_prompt(
    question: str,
    history: "list[ConversationTurn]",
    ctx: BriefingContext | None,
    fleet_summary: str = "",
) -> str:
    """
    Build a prompt for a conversational operator message.

    This is the primary prompt used by ``BriefingService.chat()``.  It:
    - Injects conversation history so the model understands what was already
      said and does not repeat it.
    - Provides the current asset's grounded data (or a fleet summary for
      fleet-wide questions) so the model can answer without inventing values.
    - Instructs the model to adapt its length and tone to the actual message.

    Parameters
    ----------
    question:
        The operator's current message.
    history:
        Previous turns in the conversation (oldest first).  Each turn has
        a ``role`` (``"user"`` or ``"assistant"``) and ``content`` string.
    ctx:
        Grounded asset context from the risk engine.  ``None`` for fleet-wide
        questions where no single asset is selected.
    fleet_summary:
        Short text summary of fleet state (e.g. top-3 ranked assets).
        Used when ``ctx`` is ``None`` so the model still has grounded data.
    """
    # Build the history block
    history_lines: list[str] = []
    for turn in history:
        prefix = "Operator" if turn.role == "user" else "Assistant"
        history_lines.append(f"{prefix}: {turn.content}")
    history_block = (
        "\n".join(history_lines)
        if history_lines
        else "(This is the first message in this conversation.)"
    )

    # Build the asset context block
    if ctx is not None:
        context_block = (
            f"[ASSET CONTEXT — {ctx.asset_id}]\n"
            f"{json.dumps(ctx.to_dict(), indent=2)}\n"
            "[END ASSET CONTEXT]"
        )
    elif fleet_summary:
        context_block = f"[FLEET CONTEXT]\n{fleet_summary}\n[END FLEET CONTEXT]"
    else:
        context_block = "[ASSET CONTEXT]\n(No specific asset selected.)\n[END ASSET CONTEXT]"

    return f"""{_CONVERSATIONAL_SYSTEM}

{context_block}

[CONVERSATION HISTORY]
{history_block}
[END CONVERSATION HISTORY]

Operator: {question}
Assistant:"""
