"""Offline provider-failure tests. These do not measure real language accuracy."""

from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from freight import ai
from freight.fixtures import demo_snapshot
from freight.settings import Settings


@pytest.mark.parametrize("failure", ["incomplete", "refused", "transport", "rejected"])
def test_provider_failures_never_create_a_rule(monkeypatch, failure):
    settings = Settings(
        openai_api_key="offline-test-placeholder", openai_model_rules="offline-model"
    )
    monkeypatch.setattr(ai, "get_settings", lambda: settings)

    def parse(**kwargs):
        assert kwargs["store"] is False
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        if failure == "transport":
            raise APIConnectionError(request=request)
        if failure == "rejected":
            raise APIStatusError(
                "offline rejection", response=httpx.Response(401, request=request), body={}
            )
        return SimpleNamespace(
            status="incomplete" if failure == "incomplete" else "completed", output_parsed=None
        )

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    monkeypatch.setattr(ai, "OpenAI", lambda **_: nullcontext(client))
    snapshot = demo_snapshot()
    with pytest.raises(ai.InterpretationError):
        ai.propose_rule(snapshot, "Assign SFD-1041 to Team 02")
    assert snapshot.rules == ()


@pytest.mark.parametrize(
    "instruction", ["Prefer Team 02 for SFD-1041.", "أفضل إسناد SFD-1041 إلى Team 02."]
)
def test_missing_soft_tradeoff_requests_clarification_without_activating_a_rule(instruction):
    interpretation = ai.RuleInterpretation(
        status="proposed",
        explanation="Preference",
        question=None,
        kind="preferred_assignment",
        resource_id=None,
        team_id="team-02",
        job_id="job-001",
        site_id=None,
        customer=None,
        start=None,
        end=None,
        strength="soft",
        penalty_minor=None,
    )
    result = ai.validate_interpretation(demo_snapshot(), instruction, interpretation)
    assert result["status"] == "clarification"
    assert result["rule"] is None
    assert result["question"]


def test_replies_follow_the_dispatchers_screen_language(monkeypatch):
    """English instruction on an Arabic screen: the reply is Arabic, and the model is told."""
    interpretation = ai.RuleInterpretation(
        status="proposed",
        explanation="x",
        question=None,
        kind="preferred_assignment",
        resource_id=None,
        team_id="team-02",
        job_id="job-001",
        site_id=None,
        customer=None,
        start=None,
        end=None,
        strength="soft",
        penalty_minor=None,
    )
    english_text = "Prefer Team 02 for SFD-1041."
    arabic = ai.validate_interpretation(demo_snapshot(), english_text, interpretation, "ar")
    english = ai.validate_interpretation(demo_snapshot(), english_text, interpretation, "en")
    assert "ريال" in arabic["question"] and "SAR" in english["question"]

    sent = {}
    settings = Settings(openai_api_key="offline-test-placeholder", openai_model_rules="m")
    monkeypatch.setattr(ai, "get_settings", lambda: settings)

    def parse(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(status="completed", output_parsed=None)

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    monkeypatch.setattr(ai, "OpenAI", lambda **_: nullcontext(client))
    with pytest.raises(ai.InterpretationError):
        ai.propose_rule(demo_snapshot(), english_text, "ar")
    assert '"reply_language": "Arabic"' in sent["input"]


def test_an_environment_key_hiding_a_different_env_file_key_is_reported(tmp_path, monkeypatch):
    from freight.settings import key_override_warning

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-new-key-from-file\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-old-key-in-environment")
    warning = key_override_warning((env_file,))
    assert warning and "overrides" in warning
    assert "sk-new" not in warning and "sk-old" not in warning  # fingerprints only
    monkeypatch.setenv("OPENAI_API_KEY", "sk-new-key-from-file")
    assert key_override_warning((env_file,)) is None
