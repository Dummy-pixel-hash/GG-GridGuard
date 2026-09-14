"""
Tests for the GridGuard AI briefing layer.

Coverage
--------
1.  BriefingContextBuilder
    - build() produces a BriefingContext with correctly mapped values
    - all scores match the RiskResult and RiskInputs exactly (grounding)
    - dominant_factor_label and description are populated
    - missing_sensor_pct is calculated correctly
    - past_rated_lifespan flag is set correctly
    - optional AssetRegistryInfo fields are forwarded

2.  MockProvider
    - generate() returns the fixed response when provided
    - synthesised response contains asset_id and risk_level from context
    - call_count increments on each call
    - last_prompt is recorded

3.  BriefingService
    - brief() returns a BriefingResult with correct type and asset_id
    - why_risk_level() delegates to the correct prompt
    - risk_factors() delegates to the correct prompt
    - inspection_recommendation() delegates to the correct prompt
    - prioritise() handles a list of assets and returns ranked text
    - prioritise() with empty list returns graceful empty result
    - include_prompt_in_result=True populates prompt_used
    - include_prompt_in_result=False leaves prompt_used empty
    - BriefingResult contains correct overall_risks and risk_levels maps

4.  Prompt grounding
    - every prompt template includes the asset_id in output
    - every prompt template includes the numeric risk score
    - multi-asset prioritisation prompt lists all asset IDs
    - asset data JSON block appears in every single-asset prompt

5.  BriefingConfig
    - from_env() defaults to "mock" when no credentials are configured
    - from_env() auto-selects "openai" when LLM_API_KEY is set
    - from_env() auto-selects "openai" when LLM_BASE_URL is set
    - from_env() auto-selects "watsonx" when only WATSONX_API_KEY is set
    - from_env() picks up LLM_MODEL override
    - from_env() picks up GRIDGUARD_LLM_PROVIDER explicit override
    - from_env() picks up temperature and max_tokens overrides
    - explicit GRIDGUARD_LLM_PROVIDER beats auto-detection

6.  Provider factory
    - create_provider("mock") returns MockProvider
    - create_provider("openai") returns OpenAIProvider (SDK mocked)
    - create_provider with unknown name raises ValueError
    - OpenAIProvider raises LLMProviderError when no credentials given
    - WatsonxProvider raises when credentials absent

7.  OpenAIProvider (mocked HTTP)
    - successful generate() call returns stripped text
    - API error is wrapped in LLMProviderError
    - prompt is sent as the user-role message content
    - base_url is forwarded to the openai client
    - local server (no API key) is accepted
    - openai ImportError is re-raised as ImportError with helpful message

8.  End-to-end integration
    - full pipeline: raw fixture → score_asset → brief() → non-empty text
    - grounding: response from MockProvider contains asset_id from fixture
    - all four risk level fixtures produce coherent briefings
    - prioritise() over all four fixtures returns a result listing all IDs

All tests use MockProvider or unittest.mock — no real network calls.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from risk_engine import score_asset, RiskLevel
from risk_engine.models import (
    RiskInputs,
    SensorReadings,
    WeatherConditions,
    HistoricalFailureRecord,
    AssetDegradationState,
    GridImpactFactors,
)

from ai_briefing.context_builder import (
    AssetRegistryInfo,
    BriefingContext,
    BriefingContextBuilder,
)
from ai_briefing.config import BriefingConfig
from ai_briefing.provider import (
    MockProvider,
    OpenAIProvider,
    LLMProvider,
    LLMProviderError,
    create_provider,
)
from ai_briefing.service import BriefingService, BriefingType, BriefingResult
from ai_briefing.prompts import (
    concise_briefing_prompt,
    why_risk_level_prompt,
    risk_factors_prompt,
    inspection_recommendation_prompt,
    prioritisation_prompt,
)

from tests.fixtures import NORMAL_FIXTURE, WATCH_FIXTURE, HIGH_FIXTURE, CRITICAL_FIXTURE


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _score(fixture: RiskInputs):
    return score_asset(fixture)


def _ctx(fixture: RiskInputs, *, registry=None) -> BriefingContext:
    result = _score(fixture)
    return BriefingContextBuilder.build(result, fixture, registry=registry)


def _service(fixed_response: str | None = None) -> BriefingService:
    """Return a BriefingService backed by a MockProvider."""
    return BriefingService(MockProvider(fixed_response=fixed_response))


# ===========================================================================
# 1.  BriefingContextBuilder
# ===========================================================================

class TestBriefingContextBuilder:

    def test_asset_id_matches(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        assert ctx.asset_id == CRITICAL_FIXTURE.asset_id

    def test_overall_risk_matches_score_asset(self):
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        assert ctx.overall_risk == result.overall_risk

    def test_risk_level_is_string(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        assert ctx.risk_level == "Critical"

    def test_component_scores_match(self):
        result = _score(HIGH_FIXTURE)
        ctx = BriefingContextBuilder.build(result, HIGH_FIXTURE)
        assert ctx.components.sensor_health == result.components.sensor_health
        assert ctx.components.weather_risk == result.components.weather_risk
        assert ctx.components.historical_failure == result.components.historical_failure
        assert ctx.components.asset_degradation == result.components.asset_degradation
        assert ctx.components.grid_impact == result.components.grid_impact

    def test_sensor_values_match_inputs(self):
        result = _score(HIGH_FIXTURE)
        ctx = BriefingContextBuilder.build(result, HIGH_FIXTURE)
        assert ctx.sensors.temperature_score == HIGH_FIXTURE.sensors.temperature_score
        assert ctx.sensors.missing_sensor_ratio == HIGH_FIXTURE.sensors.missing_sensor_ratio

    def test_missing_sensor_pct_is_percentage(self):
        ctx = _ctx(HIGH_FIXTURE)
        expected_pct = round(HIGH_FIXTURE.sensors.missing_sensor_ratio * 100)
        assert ctx.sensors.missing_sensor_pct == expected_pct

    def test_weather_values_match_inputs(self):
        result = _score(WATCH_FIXTURE)
        ctx = BriefingContextBuilder.build(result, WATCH_FIXTURE)
        assert ctx.weather.wind_storm_score == WATCH_FIXTURE.weather.wind_storm_score
        assert ctx.weather.forecast_hours == WATCH_FIXTURE.weather.forecast_hours

    def test_history_values_match_inputs(self):
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        assert ctx.history.failure_count_last_5yr == CRITICAL_FIXTURE.history.failure_count_last_5yr
        assert ctx.history.repeat_failure_flag == CRITICAL_FIXTURE.history.repeat_failure_flag
        assert ctx.history.last_failure_days_ago == CRITICAL_FIXTURE.history.last_failure_days_ago

    def test_degradation_values_match_inputs(self):
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        assert ctx.degradation.age_years == CRITICAL_FIXTURE.degradation.age_years
        assert ctx.degradation.maintenance_overdue_days == CRITICAL_FIXTURE.degradation.maintenance_overdue_days

    def test_past_rated_lifespan_true_when_over_age(self):
        # CRITICAL_FIXTURE: age 42 > lifespan 40
        ctx = _ctx(CRITICAL_FIXTURE)
        assert ctx.degradation.past_rated_lifespan is True

    def test_past_rated_lifespan_false_when_under_age(self):
        # NORMAL_FIXTURE: age 10 < lifespan 40
        ctx = _ctx(NORMAL_FIXTURE)
        assert ctx.degradation.past_rated_lifespan is False

    def test_grid_impact_values_match_inputs(self):
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        assert ctx.grid_impact.customers_served == CRITICAL_FIXTURE.grid_impact.customers_served
        assert ctx.grid_impact.critical_facility_count == CRITICAL_FIXTURE.grid_impact.critical_facility_count
        assert ctx.grid_impact.has_redundant_path == CRITICAL_FIXTURE.grid_impact.has_redundant_path

    def test_dominant_factor_label_is_non_empty(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        assert ctx.dominant_factor_label
        assert isinstance(ctx.dominant_factor_label, str)

    def test_dominant_factor_description_is_non_empty(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        assert ctx.dominant_factor_description
        assert isinstance(ctx.dominant_factor_description, str)

    def test_registry_info_forwarded(self):
        reg = AssetRegistryInfo(asset_type="transformer", notes="Test unit")
        ctx = _ctx(NORMAL_FIXTURE, registry=reg)
        assert ctx.asset_type == "transformer"
        assert ctx.notes == "Test unit"

    def test_no_registry_defaults_to_unknown(self):
        ctx = _ctx(NORMAL_FIXTURE)
        assert ctx.asset_type == "unknown"
        assert ctx.notes == ""

    def test_to_dict_is_serialisable(self):
        import json
        ctx = _ctx(CRITICAL_FIXTURE)
        d = ctx.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert ctx.asset_id in serialised

    def test_component_ranked_list_descending(self):
        ctx = _ctx(HIGH_FIXTURE)
        ranked = ctx.components.as_ranked_list()
        scores = [score for _, score in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_component_ranked_list_has_five_items(self):
        ctx = _ctx(NORMAL_FIXTURE)
        ranked = ctx.components.as_ranked_list()
        assert len(ranked) == 5


# ===========================================================================
# 2.  MockProvider
# ===========================================================================

class TestMockProvider:

    def test_fixed_response_returned(self):
        provider = MockProvider(fixed_response="FIXED")
        assert provider.generate("any prompt") == "FIXED"

    def test_call_count_increments(self):
        provider = MockProvider(fixed_response="X")
        provider.generate("p1")
        provider.generate("p2")
        assert provider.call_count == 2

    def test_last_prompt_recorded(self):
        provider = MockProvider(fixed_response="X")
        provider.generate("my test prompt")
        assert provider.last_prompt == "my test prompt"

    def test_synthesised_response_contains_asset_id(self):
        provider = MockProvider()
        ctx = _ctx(CRITICAL_FIXTURE)
        prompt = concise_briefing_prompt(ctx)
        response = provider.generate(prompt)
        assert CRITICAL_FIXTURE.asset_id in response

    def test_synthesised_response_contains_risk_level(self):
        provider = MockProvider()
        ctx = _ctx(CRITICAL_FIXTURE)
        prompt = concise_briefing_prompt(ctx)
        response = provider.generate(prompt)
        assert "Critical" in response

    def test_synthesised_response_contains_risk_score(self):
        provider = MockProvider()
        ctx = _ctx(CRITICAL_FIXTURE)
        result = _score(CRITICAL_FIXTURE)
        prompt = concise_briefing_prompt(ctx)
        response = provider.generate(prompt)
        assert str(result.overall_risk) in response

    def test_satisfies_llm_provider_protocol(self):
        provider = MockProvider()
        assert isinstance(provider, LLMProvider)


# ===========================================================================
# 3.  BriefingService
# ===========================================================================

class TestBriefingService:

    def test_brief_returns_briefing_result(self):
        svc = _service()
        result = _score(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert isinstance(br, BriefingResult)

    def test_brief_type_is_concise_briefing(self):
        svc = _service()
        result = _score(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert br.briefing_type == BriefingType.CONCISE_BRIEFING

    def test_why_risk_level_type(self):
        svc = _service()
        result = _score(CRITICAL_FIXTURE)
        br = svc.why_risk_level(result, CRITICAL_FIXTURE)
        assert br.briefing_type == BriefingType.WHY_RISK_LEVEL

    def test_risk_factors_type(self):
        svc = _service()
        result = _score(CRITICAL_FIXTURE)
        br = svc.risk_factors(result, CRITICAL_FIXTURE)
        assert br.briefing_type == BriefingType.RISK_FACTORS

    def test_inspection_recommendation_type(self):
        svc = _service()
        result = _score(CRITICAL_FIXTURE)
        br = svc.inspection_recommendation(result, CRITICAL_FIXTURE)
        assert br.briefing_type == BriefingType.INSPECTION_RECOMMENDATION

    def test_asset_id_in_result(self):
        svc = _service()
        result = _score(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert CRITICAL_FIXTURE.asset_id in br.asset_ids

    def test_overall_risk_in_result_map(self):
        svc = _service()
        result = _score(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert br.overall_risks[CRITICAL_FIXTURE.asset_id] == result.overall_risk

    def test_risk_level_in_result_map(self):
        svc = _service()
        result = _score(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert br.risk_levels[CRITICAL_FIXTURE.asset_id] == "Critical"

    def test_include_prompt_in_result_true(self):
        svc = BriefingService(MockProvider(), include_prompt_in_result=True)
        result = _score(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert br.prompt_used != ""
        assert CRITICAL_FIXTURE.asset_id in br.prompt_used

    def test_include_prompt_in_result_false(self):
        svc = BriefingService(MockProvider(), include_prompt_in_result=False)
        result = _score(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert br.prompt_used == ""

    def test_text_is_non_empty(self):
        svc = _service()
        result = _score(HIGH_FIXTURE)
        br = svc.brief(result, HIGH_FIXTURE)
        assert br.text.strip() != ""

    def test_prioritise_multiple_assets(self):
        svc = _service()
        pairs = [
            (_score(CRITICAL_FIXTURE), CRITICAL_FIXTURE),
            (_score(HIGH_FIXTURE), HIGH_FIXTURE),
            (_score(WATCH_FIXTURE), WATCH_FIXTURE),
        ]
        br = svc.prioritise(pairs)
        assert br.briefing_type == BriefingType.PRIORITISATION
        assert len(br.asset_ids) == 3

    def test_prioritise_empty_list(self):
        svc = _service()
        br = svc.prioritise([])
        assert br.briefing_type == BriefingType.PRIORITISATION
        assert br.asset_ids == []
        assert "No assets" in br.text

    def test_prioritise_asset_ids_in_result(self):
        svc = _service()
        pairs = [
            (_score(CRITICAL_FIXTURE), CRITICAL_FIXTURE),
            (_score(HIGH_FIXTURE), HIGH_FIXTURE),
        ]
        br = svc.prioritise(pairs)
        assert CRITICAL_FIXTURE.asset_id in br.asset_ids
        assert HIGH_FIXTURE.asset_id in br.asset_ids

    def test_from_config_with_mock_provider(self):
        config = BriefingConfig(provider_name="mock")
        svc = BriefingService.from_config(config)
        result = _score(NORMAL_FIXTURE)
        br = svc.brief(result, NORMAL_FIXTURE)
        assert isinstance(br, BriefingResult)

    def test_registry_info_forwarded_to_prompt(self):
        provider = MockProvider()
        svc = BriefingService(provider, include_prompt_in_result=True)
        result = _score(NORMAL_FIXTURE)
        reg = AssetRegistryInfo(asset_type="power transformer", notes="Main feeder")
        br = svc.brief(result, NORMAL_FIXTURE, registry=reg)
        # Registry fields should appear in the injected JSON context
        assert "power transformer" in br.prompt_used
        assert "Main feeder" in br.prompt_used


# ===========================================================================
# 4.  Prompt grounding
# ===========================================================================

class TestPromptGrounding:
    """
    Verify that prompt templates correctly embed grounded data.

    These tests do NOT test the LLM's response — they test that the prompt
    construction layer properly injects all the values the model needs to
    reason over.
    """

    def test_concise_briefing_contains_asset_id(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        prompt = concise_briefing_prompt(ctx)
        assert CRITICAL_FIXTURE.asset_id in prompt

    def test_concise_briefing_contains_risk_score(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        result = _score(CRITICAL_FIXTURE)
        prompt = concise_briefing_prompt(ctx)
        assert str(result.overall_risk) in prompt

    def test_concise_briefing_contains_asset_data_block(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        prompt = concise_briefing_prompt(ctx)
        assert "[ASSET DATA]" in prompt
        assert "[END ASSET DATA]" in prompt

    def test_why_risk_level_contains_risk_level(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        prompt = why_risk_level_prompt(ctx)
        assert "Critical" in prompt

    def test_why_risk_level_contains_component_scores(self):
        ctx = _ctx(CRITICAL_FIXTURE)
        prompt = why_risk_level_prompt(ctx)
        # The ranked component list is injected directly
        assert "sensor health" in prompt or "sensor_health" in prompt

    def test_risk_factors_contains_asset_data(self):
        ctx = _ctx(HIGH_FIXTURE)
        prompt = risk_factors_prompt(ctx)
        assert "[ASSET DATA]" in prompt
        assert HIGH_FIXTURE.asset_id in prompt

    def test_inspection_recommendation_contains_asset_id(self):
        ctx = _ctx(WATCH_FIXTURE)
        prompt = inspection_recommendation_prompt(ctx)
        assert WATCH_FIXTURE.asset_id in prompt

    def test_prioritisation_prompt_lists_all_asset_ids(self):
        contexts = [_ctx(f) for f in [CRITICAL_FIXTURE, HIGH_FIXTURE, WATCH_FIXTURE]]
        prompt = prioritisation_prompt(contexts)
        assert CRITICAL_FIXTURE.asset_id in prompt
        assert HIGH_FIXTURE.asset_id in prompt
        assert WATCH_FIXTURE.asset_id in prompt

    def test_prioritisation_prompt_contains_risk_scores(self):
        result_c = _score(CRITICAL_FIXTURE)
        contexts = [_ctx(CRITICAL_FIXTURE)]
        prompt = prioritisation_prompt(contexts)
        assert str(result_c.overall_risk) in prompt

    def test_grounding_rule_present_in_all_prompts(self):
        """All prompts must include the grounding rule forbidding invention."""
        ctx = _ctx(CRITICAL_FIXTURE)
        for fn, args in [
            (concise_briefing_prompt, (ctx,)),
            (why_risk_level_prompt, (ctx,)),
            (risk_factors_prompt, (ctx,)),
            (inspection_recommendation_prompt, (ctx,)),
            (prioritisation_prompt, ([ctx],)),
        ]:
            prompt = fn(*args)
            assert "GROUNDING RULE" in prompt, (
                f"{fn.__name__} is missing the grounding rule"
            )

    @pytest.mark.parametrize("fixture", [
        NORMAL_FIXTURE, WATCH_FIXTURE, HIGH_FIXTURE, CRITICAL_FIXTURE
    ])
    def test_asset_id_in_prompt_for_all_risk_levels(self, fixture):
        ctx = _ctx(fixture)
        prompt = concise_briefing_prompt(ctx)
        assert fixture.asset_id in prompt


# ===========================================================================
# 5.  BriefingConfig
# ===========================================================================

def _clean_env(*keys):
    """Context manager: remove named env vars, restoring them after the block."""
    return patch.dict(os.environ, {k: "" for k in keys}, clear=False)


class TestBriefingConfig:

    def test_from_env_defaults_to_mock_with_no_credentials(self):
        """All credential vars absent → provider defaults to 'mock'."""
        vars_to_clear = ["LLM_API_KEY", "LLM_BASE_URL", "WATSONX_API_KEY",
                         "GRIDGUARD_LLM_PROVIDER"]
        env_patch = {k: "" for k in vars_to_clear}
        with patch.dict(os.environ, env_patch):
            for k in vars_to_clear:
                os.environ.pop(k, None)
            config = BriefingConfig.from_env()
        assert config.provider_name == "mock"

    def test_from_env_auto_selects_openai_when_api_key_set(self):
        with patch.dict(os.environ, {
            "LLM_API_KEY": "sk-test",
            "LLM_BASE_URL": "",
        }):
            os.environ.pop("GRIDGUARD_LLM_PROVIDER", None)
            config = BriefingConfig.from_env()
        assert config.provider_name == "openai"
        assert config.llm_api_key == "sk-test"

    def test_from_env_auto_selects_openai_when_base_url_set(self):
        with patch.dict(os.environ, {
            "LLM_BASE_URL": "http://localhost:11434/v1",
            "LLM_API_KEY": "",
        }):
            os.environ.pop("GRIDGUARD_LLM_PROVIDER", None)
            config = BriefingConfig.from_env()
        assert config.provider_name == "openai"
        assert config.llm_base_url == "http://localhost:11434/v1"

    def test_from_env_auto_selects_watsonx_when_only_watsonx_key_set(self):
        with patch.dict(os.environ, {
            "WATSONX_API_KEY": "wx-test",
            "LLM_API_KEY": "",
            "LLM_BASE_URL": "",
        }):
            os.environ.pop("GRIDGUARD_LLM_PROVIDER", None)
            config = BriefingConfig.from_env()
        assert config.provider_name == "watsonx"
        assert config.watsonx_api_key == "wx-test"

    def test_from_env_explicit_provider_beats_auto_detection(self):
        """GRIDGUARD_LLM_PROVIDER overrides the auto-detected default."""
        with patch.dict(os.environ, {
            "LLM_API_KEY": "sk-test",
            "GRIDGUARD_LLM_PROVIDER": "mock",
        }):
            config = BriefingConfig.from_env()
        assert config.provider_name == "mock"

    def test_from_env_picks_up_model_override(self):
        with patch.dict(os.environ, {
            "LLM_MODEL": "llama3:70b",
            "GRIDGUARD_LLM_PROVIDER": "mock",
        }):
            config = BriefingConfig.from_env()
        assert config.model_id == "llama3:70b"

    def test_from_env_picks_up_temperature(self):
        with patch.dict(os.environ, {
            "GRIDGUARD_LLM_TEMPERATURE": "0.5",
            "GRIDGUARD_LLM_PROVIDER": "mock",
        }):
            config = BriefingConfig.from_env()
        assert config.temperature == 0.5

    def test_from_env_picks_up_max_tokens(self):
        with patch.dict(os.environ, {
            "GRIDGUARD_LLM_MAX_TOKENS": "256",
            "GRIDGUARD_LLM_PROVIDER": "mock",
        }):
            config = BriefingConfig.from_env()
        assert config.max_new_tokens == 256

    def test_from_env_stores_llm_base_url(self):
        with patch.dict(os.environ, {
            "LLM_BASE_URL": "http://localhost:11434/v1",
            "GRIDGUARD_LLM_PROVIDER": "mock",
        }):
            config = BriefingConfig.from_env()
        assert config.llm_base_url == "http://localhost:11434/v1"

    def test_defaults_are_sane(self):
        config = BriefingConfig()
        assert config.temperature >= 0.0
        assert config.max_new_tokens > 0
        assert config.model_id != ""
        assert config.watsonx_url.startswith("https://")

    def test_default_provider_is_mock(self):
        """Default BriefingConfig() with no arguments should be safe for offline use."""
        config = BriefingConfig()
        assert config.provider_name == "mock"


# ===========================================================================
# 6.  Provider factory
# ===========================================================================

class TestProviderFactory:

    def test_mock_provider_created(self):
        config = BriefingConfig(provider_name="mock")
        provider = create_provider(config)
        assert isinstance(provider, MockProvider)

    def test_unknown_provider_raises_value_error(self):
        config = BriefingConfig(provider_name="nonexistent_llm")
        with pytest.raises(ValueError, match="Unknown provider_name"):
            create_provider(config)

    def test_openai_provider_created_when_openai_importable(self):
        """create_provider('openai') should return an OpenAIProvider when the SDK exists."""
        # Build a minimal mock openai module so we don't need the real SDK
        fake_openai = MagicMock()
        fake_client = MagicMock()
        fake_openai.OpenAI.return_value = fake_client

        config = BriefingConfig(
            provider_name="openai",
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="",
        )
        with patch.dict("sys.modules", {"openai": fake_openai}):
            provider = create_provider(config)
        assert isinstance(provider, OpenAIProvider)

    def test_openai_provider_raises_without_any_credentials(self):
        """OpenAIProvider must refuse to start with no URL and no key."""
        config = BriefingConfig(
            provider_name="openai",
            llm_base_url="",
            llm_api_key="",
        )
        fake_openai = MagicMock()
        with patch.dict("sys.modules", {"openai": fake_openai}):
            with pytest.raises(LLMProviderError, match="LLM_BASE_URL or LLM_API_KEY"):
                create_provider(config)

    def test_watsonx_provider_raises_without_credentials(self):
        """WatsonxProvider should raise LLMProviderError when credentials are absent."""
        config = BriefingConfig(
            provider_name="watsonx",
            watsonx_api_key="",
            watsonx_project_id="",
        )
        with pytest.raises((LLMProviderError, ImportError)):
            create_provider(config)

    def test_watsonx_provider_raises_without_project_id(self):
        """WatsonxProvider should raise LLMProviderError when project_id is absent."""
        config = BriefingConfig(
            provider_name="watsonx",
            watsonx_api_key="some-key",
            watsonx_project_id="",
        )
        with pytest.raises((LLMProviderError, ImportError)):
            create_provider(config)


# ===========================================================================
# 7.  OpenAIProvider — mocked HTTP
# ===========================================================================

def _fake_openai_module(response_text: str = "Mocked LLM response") -> MagicMock:
    """
    Build a minimal fake ``openai`` module whose client returns a fixed response.
    Mirrors the shape of openai.OpenAI().chat.completions.create().
    """
    fake_choice = MagicMock()
    fake_choice.message.content = response_text

    fake_completion = MagicMock()
    fake_completion.choices = [fake_choice]

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_completion

    fake_openai = MagicMock()
    fake_openai.OpenAI.return_value = fake_client

    return fake_openai


class TestOpenAIProvider:

    def _make_provider(
        self,
        response_text: str = "Test response",
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "",
    ) -> tuple["OpenAIProvider", MagicMock]:
        """Return (OpenAIProvider, fake_openai_module) for a provider backed by a mock client."""
        fake_openai = _fake_openai_module(response_text)
        config = BriefingConfig(
            provider_name="openai",
            model_id="llama3",
            llm_base_url=base_url,
            llm_api_key=api_key,
            max_new_tokens=256,
            temperature=0.1,
        )
        with patch.dict("sys.modules", {"openai": fake_openai}):
            provider = OpenAIProvider(config)
        return provider, fake_openai

    def test_generate_returns_response_text(self):
        provider, _ = self._make_provider(response_text="  Hello from LLM  ")
        result = provider.generate("Test prompt")
        assert result == "Hello from LLM"  # stripped

    def test_generate_sends_user_role_message(self):
        provider, fake_openai = self._make_provider()
        provider.generate("My prompt text")
        call_kwargs = fake_openai.OpenAI.return_value.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs["messages"]
        # The call may use kwargs; check either way
        create_call = fake_openai.OpenAI.return_value.chat.completions.create
        _, kwargs = create_call.call_args
        assert kwargs["messages"] == [{"role": "user", "content": "My prompt text"}]

    def test_generate_passes_model_id(self):
        provider, fake_openai = self._make_provider()
        provider.generate("prompt")
        create_call = fake_openai.OpenAI.return_value.chat.completions.create
        _, kwargs = create_call.call_args
        assert kwargs["model"] == "llama3"

    def test_generate_passes_max_tokens(self):
        provider, fake_openai = self._make_provider()
        provider.generate("prompt")
        create_call = fake_openai.OpenAI.return_value.chat.completions.create
        _, kwargs = create_call.call_args
        assert kwargs["max_tokens"] == 256

    def test_generate_passes_temperature(self):
        provider, fake_openai = self._make_provider()
        provider.generate("prompt")
        create_call = fake_openai.OpenAI.return_value.chat.completions.create
        _, kwargs = create_call.call_args
        assert kwargs["temperature"] == pytest.approx(0.1)

    def test_base_url_forwarded_to_client(self):
        fake_openai = _fake_openai_module()
        config = BriefingConfig(
            provider_name="openai",
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="",
        )
        with patch.dict("sys.modules", {"openai": fake_openai}):
            OpenAIProvider(config)
        _, kwargs = fake_openai.OpenAI.call_args
        assert kwargs["base_url"] == "http://localhost:11434/v1"

    def test_openai_default_url_when_base_url_empty(self):
        """When only api_key is given, base_url=None so the SDK uses its default."""
        fake_openai = _fake_openai_module()
        config = BriefingConfig(
            provider_name="openai",
            llm_base_url="",
            llm_api_key="sk-real-key",
        )
        with patch.dict("sys.modules", {"openai": fake_openai}):
            OpenAIProvider(config)
        _, kwargs = fake_openai.OpenAI.call_args
        assert kwargs["base_url"] is None

    def test_local_server_no_key_accepted(self):
        """Local Ollama / llama.cpp servers need no API key."""
        fake_openai = _fake_openai_module()
        config = BriefingConfig(
            provider_name="openai",
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="",
        )
        # Should not raise
        with patch.dict("sys.modules", {"openai": fake_openai}):
            provider = OpenAIProvider(config)
        assert isinstance(provider, OpenAIProvider)

    def test_api_error_wrapped_in_llm_provider_error(self):
        """Any exception from the API call must be re-raised as LLMProviderError."""
        fake_openai = _fake_openai_module()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = (
            RuntimeError("connection refused")
        )
        config = BriefingConfig(
            provider_name="openai",
            llm_base_url="http://localhost:11434/v1",
        )
        with patch.dict("sys.modules", {"openai": fake_openai}):
            provider = OpenAIProvider(config)
        with pytest.raises(LLMProviderError, match="OpenAI-compatible API call failed"):
            provider.generate("any prompt")

    def test_missing_openai_sdk_raises_import_error(self):
        """If the openai package is absent, a clear ImportError is raised."""
        config = BriefingConfig(
            provider_name="openai",
            llm_base_url="http://localhost:11434/v1",
        )
        # Simulate openai not installed by removing it from sys.modules
        import sys
        original = sys.modules.get("openai")
        sys.modules["openai"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(ImportError, match="openai"):
                OpenAIProvider(config)
        finally:
            if original is None:
                sys.modules.pop("openai", None)
            else:
                sys.modules["openai"] = original

    def test_satisfies_llm_provider_protocol(self):
        provider, _ = self._make_provider()
        assert isinstance(provider, LLMProvider)

    def test_full_briefing_pipeline_with_openai_provider(self):
        """End-to-end: risk engine → OpenAIProvider → BriefingResult."""
        response_text = "T-007 is Critical. Inspect immediately. [OpenAIProvider mock]"
        provider, _ = self._make_provider(response_text=response_text)
        svc = BriefingService(provider)
        result = score_asset(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert br.text == response_text
        assert br.briefing_type == BriefingType.CONCISE_BRIEFING
        assert CRITICAL_FIXTURE.asset_id in br.asset_ids


# ===========================================================================
# 8.  End-to-end integration
# ===========================================================================

class TestEndToEnd:
    """Full pipeline: raw fixture → score_asset → briefing service → text."""

    @pytest.mark.parametrize("fixture,expected_level", [
        (NORMAL_FIXTURE,   RiskLevel.NORMAL),
        (WATCH_FIXTURE,    RiskLevel.WATCH),
        (HIGH_FIXTURE,     RiskLevel.HIGH),
        (CRITICAL_FIXTURE, RiskLevel.CRITICAL),
    ])
    def test_brief_produces_non_empty_text_for_all_risk_levels(
        self, fixture, expected_level
    ):
        svc = _service()
        result = score_asset(fixture)
        assert result.risk_level == expected_level
        br = svc.brief(result, fixture)
        assert br.text.strip() != ""

    def test_critical_briefing_mentions_asset_id(self):
        svc = _service()
        result = score_asset(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert CRITICAL_FIXTURE.asset_id in br.text

    def test_critical_briefing_mentions_risk_level(self):
        svc = _service()
        result = score_asset(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        assert "Critical" in br.text

    def test_why_risk_level_for_critical_contains_asset_id(self):
        svc = _service()
        result = score_asset(CRITICAL_FIXTURE)
        br = svc.why_risk_level(result, CRITICAL_FIXTURE)
        assert CRITICAL_FIXTURE.asset_id in br.text

    def test_risk_factors_for_high_produces_text(self):
        svc = _service()
        result = score_asset(HIGH_FIXTURE)
        br = svc.risk_factors(result, HIGH_FIXTURE)
        assert len(br.text) > 10

    def test_inspection_recommendation_for_critical(self):
        svc = _service()
        result = score_asset(CRITICAL_FIXTURE)
        br = svc.inspection_recommendation(result, CRITICAL_FIXTURE)
        assert isinstance(br.text, str)
        assert len(br.text) > 0

    def test_prioritise_all_four_fixtures(self):
        svc = _service()
        pairs = [
            (score_asset(f), f)
            for f in [CRITICAL_FIXTURE, HIGH_FIXTURE, WATCH_FIXTURE, NORMAL_FIXTURE]
        ]
        br = svc.prioritise(pairs)
        assert br.briefing_type == BriefingType.PRIORITISATION
        assert len(br.asset_ids) == 4

    def test_determinism_mock_provider_gives_same_text_twice(self):
        """MockProvider must be deterministic for the same inputs."""
        svc = _service()
        result = score_asset(CRITICAL_FIXTURE)
        br1 = svc.brief(result, CRITICAL_FIXTURE)
        br2 = svc.brief(result, CRITICAL_FIXTURE)
        assert br1.text == br2.text

    def test_llm_never_called_with_empty_prompt(self):
        """The provider must always receive a non-empty prompt."""
        provider = MockProvider(fixed_response="ok")
        svc = BriefingService(provider)
        result = score_asset(NORMAL_FIXTURE)
        svc.brief(result, NORMAL_FIXTURE)
        assert len(provider.last_prompt) > 50  # must be a meaningful prompt

    def test_risk_score_in_prompt_matches_engine_output(self):
        """The score in the prompt must be exactly what score_asset() returned."""
        provider = MockProvider(fixed_response="ok")
        svc = BriefingService(provider, include_prompt_in_result=True)
        result = score_asset(CRITICAL_FIXTURE)
        br = svc.brief(result, CRITICAL_FIXTURE)
        # The exact overall_risk float must appear in the injected context
        assert str(result.overall_risk) in br.prompt_used


# ===========================================================================
# 9.  Conversational service — BriefingService.chat()
# ===========================================================================

from ai_briefing.service import ConversationTurn
from ai_briefing.prompts import conversational_prompt


class TestConversationTurn:
    """ConversationTurn is a plain dataclass — test construction and fields."""

    def test_user_turn(self):
        t = ConversationTurn(role="user", content="What's wrong?")
        assert t.role == "user"
        assert t.content == "What's wrong?"

    def test_assistant_turn(self):
        t = ConversationTurn(role="assistant", content="TX-007 is critical.")
        assert t.role == "assistant"

    def test_empty_content_allowed(self):
        t = ConversationTurn(role="user", content="")
        assert t.content == ""


class TestConversationalPrompt:
    """Verify conversational_prompt injects history and context correctly."""

    def _ctx(self, fixture=None):
        from tests.fixtures import CRITICAL_FIXTURE
        f = fixture or CRITICAL_FIXTURE
        return _ctx(f)

    def test_prompt_contains_question(self):
        p = conversational_prompt("What's wrong with this thing?", [], self._ctx())
        assert "What's wrong with this thing?" in p

    def test_prompt_contains_asset_id(self):
        p = conversational_prompt("Tell me more", [], self._ctx())
        assert "TX-CRITICAL-004" in p

    def test_prompt_contains_grounding_rule(self):
        p = conversational_prompt("What's wrong?", [], self._ctx())
        assert "GROUNDING RULE" in p

    def test_prompt_contains_conversation_rules(self):
        p = conversational_prompt("What's wrong?", [], self._ctx())
        assert "CONVERSATION RULES" in p

    def test_history_injected_into_prompt(self):
        history = [
            ConversationTurn("user", "What's wrong with TX-007?"),
            ConversationTurn("assistant", "TX-007 is at 94.9, critical due to weather."),
        ]
        p = conversational_prompt("Why is the weather a big deal?", history, self._ctx())
        assert "What's wrong with TX-007?" in p
        assert "TX-007 is at 94.9" in p

    def test_empty_history_shows_first_message_note(self):
        p = conversational_prompt("Hello", [], self._ctx())
        assert "first message" in p.lower() or "CONVERSATION HISTORY" in p

    def test_no_asset_ctx_uses_no_specific_asset_placeholder(self):
        p = conversational_prompt("Which assets need attention?", [], None)
        assert "No specific asset" in p or "ASSET CONTEXT" in p

    def test_fleet_summary_injected_when_no_ctx(self):
        summary = "Top assets: TX-007 Critical 94.9, TX-008 Critical 90.0"
        p = conversational_prompt("Which ones?", [], None, fleet_summary=summary)
        assert "TX-007" in p
        assert "FLEET CONTEXT" in p

    def test_history_oldest_first(self):
        history = [
            ConversationTurn("user", "First question"),
            ConversationTurn("assistant", "First answer"),
            ConversationTurn("user", "Second question"),
        ]
        p = conversational_prompt("Third question", history, self._ctx())
        first_pos = p.index("First question")
        second_pos = p.index("Second question")
        assert first_pos < second_pos

    def test_operator_prefix_for_user_turns(self):
        history = [ConversationTurn("user", "test user turn")]
        p = conversational_prompt("follow up", history, self._ctx())
        assert "Operator: test user turn" in p

    def test_assistant_prefix_for_assistant_turns(self):
        history = [ConversationTurn("assistant", "test assistant reply")]
        p = conversational_prompt("follow up", history, self._ctx())
        assert "Assistant: test assistant reply" in p

    def test_risk_score_in_prompt_grounded_from_engine(self):
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        p = conversational_prompt("Tell me about this asset", [], ctx)
        assert str(result.overall_risk) in p

    @pytest.mark.parametrize("fixture", [
        NORMAL_FIXTURE, WATCH_FIXTURE, HIGH_FIXTURE, CRITICAL_FIXTURE
    ])
    def test_prompt_built_for_all_risk_levels(self, fixture):
        ctx = _ctx(fixture)
        p = conversational_prompt("Any news?", [], ctx)
        assert fixture.asset_id in p
        assert "GROUNDING RULE" in p


class TestChatMethod:
    """Tests for BriefingService.chat() end-to-end."""

    def _svc(self, response="Mock response from chat."):
        return BriefingService(MockProvider(fixed_response=response))

    def test_chat_returns_briefing_result(self):
        svc = self._svc()
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        br = svc.chat("What's wrong?", ctx=ctx)
        assert isinstance(br, BriefingResult)

    def test_chat_briefing_type_is_conversational(self):
        svc = self._svc()
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        br = svc.chat("Any news?", ctx=ctx)
        assert br.briefing_type == BriefingType.CONVERSATIONAL

    def test_chat_text_is_not_empty(self):
        svc = self._svc()
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        br = svc.chat("Tell me about this asset", ctx=ctx)
        assert br.text.strip() != ""

    def test_chat_asset_id_in_result(self):
        svc = self._svc()
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        br = svc.chat("What's the risk here?", ctx=ctx)
        assert CRITICAL_FIXTURE.asset_id in br.asset_ids

    def test_chat_no_ctx_returns_result(self):
        """Fleet-wide question with no specific asset selected."""
        svc = self._svc()
        br = svc.chat("Which assets need attention?", fleet_summary="TX-007 Critical 94.9")
        assert isinstance(br, BriefingResult)
        assert br.asset_ids == []  # no single asset

    def test_chat_with_empty_history(self):
        svc = self._svc()
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        br = svc.chat("What's wrong?", history=[], ctx=ctx)
        assert br.text != ""

    def test_chat_with_conversation_history(self):
        """History is injected and the model receives it in the prompt."""
        provider = MockProvider(fixed_response="Follow-up answer.")
        svc = BriefingService(provider, include_prompt_in_result=True)
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)

        history = [
            ConversationTurn("user", "What's wrong with TX-CRITICAL-004?"),
            ConversationTurn("assistant", "It is Critical at 94.9 due to severe weather."),
        ]
        br = svc.chat("Why is the weather such a big deal?", history=history, ctx=ctx)
        # The previous turns must appear in the prompt
        assert "What's wrong with TX-CRITICAL-004?" in br.prompt_used
        assert "It is Critical at 94.9" in br.prompt_used

    def test_chat_follow_up_question_in_prompt(self):
        """The actual follow-up question appears at the end of the prompt."""
        provider = MockProvider(fixed_response="ok")
        svc = BriefingService(provider, include_prompt_in_result=True)
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)

        br = svc.chat("Should we send someone?", ctx=ctx)
        assert "Should we send someone?" in br.prompt_used

    def test_chat_prompt_contains_asset_data(self):
        """The grounded asset data is always present so model can't fabricate."""
        provider = MockProvider(fixed_response="ok")
        svc = BriefingService(provider, include_prompt_in_result=True)
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)

        br = svc.chat("Calm down.", ctx=ctx)
        assert "ASSET CONTEXT" in br.prompt_used
        assert str(result.overall_risk) in br.prompt_used

    def test_chat_fleet_summary_in_prompt_when_no_ctx(self):
        provider = MockProvider(fixed_response="ok")
        svc = BriefingService(provider, include_prompt_in_result=True)
        br = svc.chat(
            "Which assets should I worry about?",
            fleet_summary="TX-007 Critical 94.9, TX-008 Critical 90.1",
        )
        assert "TX-007" in br.prompt_used
        assert "FLEET CONTEXT" in br.prompt_used

    def test_chat_grounding_rule_always_in_prompt(self):
        provider = MockProvider(fixed_response="ok")
        svc = BriefingService(provider, include_prompt_in_result=True)
        result = _score(HIGH_FIXTURE)
        ctx = BriefingContextBuilder.build(result, HIGH_FIXTURE)
        br = svc.chat("oh shit", ctx=ctx)
        assert "GROUNDING RULE" in br.prompt_used

    def test_chat_casual_reaction_gets_response(self):
        """Casual inputs still produce a response (the model handles tone)."""
        svc = self._svc(response="Yeah, TX-007 is serious. The weather score is 100.")
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        br = svc.chat("oh shit", ctx=ctx)
        assert br.text.strip() != ""

    def test_chat_none_history_treated_as_empty(self):
        svc = self._svc()
        result = _score(NORMAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, NORMAL_FIXTURE)
        br = svc.chat("Any issues?", history=None, ctx=ctx)
        assert isinstance(br, BriefingResult)

    def test_chat_deterministic_with_mock_provider(self):
        """Same inputs → same output (mock is deterministic)."""
        svc = BriefingService(MockProvider(fixed_response="Stable answer."))
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        br1 = svc.chat("What's wrong?", ctx=ctx)
        br2 = svc.chat("What's wrong?", ctx=ctx)
        assert br1.text == br2.text

    def test_chat_include_prompt_false_clears_prompt_used(self):
        svc = BriefingService(MockProvider(fixed_response="ok"), include_prompt_in_result=False)
        result = _score(NORMAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, NORMAL_FIXTURE)
        br = svc.chat("Any issues?", ctx=ctx)
        assert br.prompt_used == ""

    def test_chat_multi_turn_history_all_injected(self):
        """All previous turns must appear in the prompt, not just the last one."""
        provider = MockProvider(fixed_response="ok")
        svc = BriefingService(provider, include_prompt_in_result=True)
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)

        history = [
            ConversationTurn("user", "Turn one user"),
            ConversationTurn("assistant", "Turn one assistant"),
            ConversationTurn("user", "Turn two user"),
            ConversationTurn("assistant", "Turn two assistant"),
        ]
        br = svc.chat("Turn three user", history=history, ctx=ctx)
        for turn in history:
            assert turn.content in br.prompt_used

    def test_chat_overall_risks_empty_for_fleet_question(self):
        svc = self._svc()
        br = svc.chat("What's the fleet status?")
        assert br.overall_risks == {}

    def test_chat_overall_risks_populated_for_asset_question(self):
        svc = self._svc()
        result = _score(CRITICAL_FIXTURE)
        ctx = BriefingContextBuilder.build(result, CRITICAL_FIXTURE)
        br = svc.chat("Status?", ctx=ctx)
        assert CRITICAL_FIXTURE.asset_id in br.overall_risks
        assert br.overall_risks[CRITICAL_FIXTURE.asset_id] == result.overall_risk


# ===========================================================================
# 10.  Grid service answer_question (conversational path)
# ===========================================================================

class TestAnswerQuestionConversational:
    """Test grid_service.GridState.answer_question with history threading."""

    def _make_state(self):
        from api.grid_service import GridState
        return GridState(db_path=":memory:")

    def test_answer_question_returns_text(self):
        state = self._make_state()
        resp = state.answer_question("What's the status?")
        assert "text" in resp
        assert isinstance(resp["text"], str)

    def test_answer_question_grounded_flag_set(self):
        state = self._make_state()
        resp = state.answer_question("Any critical assets?")
        assert resp.get("grounded") is True

    def test_answer_question_with_asset_id(self):
        state = self._make_state()
        resp = state.answer_question("Tell me about this asset", asset_id="TX-007")
        assert "TX-007" in resp.get("asset_ids", [])

    def test_answer_question_with_history_forwarded(self):
        """History dicts are accepted without raising."""
        state = self._make_state()
        history = [
            {"role": "user", "content": "What's wrong with TX-007?"},
            {"role": "assistant", "content": "TX-007 is Critical at 94.9."},
        ]
        resp = state.answer_question(
            "Why is the weather such a big deal?",
            asset_id="TX-007",
            history=history,
        )
        assert isinstance(resp["text"], str)

    def test_answer_question_none_history_accepted(self):
        state = self._make_state()
        resp = state.answer_question("Status update", history=None)
        assert "text" in resp

    def test_answer_question_empty_history_accepted(self):
        state = self._make_state()
        resp = state.answer_question("Status update", history=[])
        assert "text" in resp

    def test_answer_question_unknown_asset_falls_back_to_fleet(self):
        state = self._make_state()
        resp = state.answer_question("Tell me about TX-999")
        # No asset matched, fleet path used — text must contain engine numbers
        assert isinstance(resp["text"], str)
        assert len(resp["text"]) > 0

    def test_answer_question_briefing_type_conversational(self):
        state = self._make_state()
        resp = state.answer_question("Anything critical?")
        assert resp["briefing_type"] == "conversational"

    def test_answer_question_provider_and_model_returned(self):
        state = self._make_state()
        resp = state.answer_question("Status?")
        assert "provider" in resp
        assert "model" in resp

    def test_answer_question_invalid_history_type_ignored(self):
        """Non-list history value must not crash the server."""
        state = self._make_state()
        resp = state.answer_question("Status?", history="not a list")  # type: ignore[arg-type]
        assert "text" in resp
