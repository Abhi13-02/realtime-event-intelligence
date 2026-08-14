"""
Unit tests for the LLM relevance gate.

The gate can DELETE a narrative before the user ever sees it, so the property
that matters most is not "does it reject the right things" — that is the
model's job — but "does it ever reject when it was not clearly told to".
A missing key, malformed JSON, a network failure or an unexpected type must all
resolve to KEEP. These tests pin that contract.

Run:
    docker compose exec backend python -m pytest tests/test_relevance_gate.py -v
"""
import json

import pytest

from app.tasks.discovery.labeling import _SENSITIVITY_RULES, _call_groq_label


class FakeGroq:
    """Minimal stand-in for the Groq client. Returns canned content, or raises."""

    def __init__(self, content=None, raises=None):
        self._content = content
        self._raises = raises
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer._raises:
                    raise outer._raises
                msg = type("M", (), {"content": outer._content})
                choice = type("C", (), {"message": msg})
                return type("R", (), {"choices": [choice]})

        self.chat = type("Chat", (), {"completions": _Completions()})()


def call(client, sensitivity="balanced", topic_description="Electric vehicles"):
    return _call_groq_label(
        groq_client=client,
        topic_name="EVs",
        topic_description=topic_description,
        sensitivity=sensitivity,
        keywords=["battery", "charging"],
        sample_headlines=["A new battery plant opens"],
        article_count=5,
        reddit_count=0,
        sentiment_score=None,
    )


class TestVerdictParsing:
    def test_explicit_rejection_is_honoured(self):
        c = FakeGroq(json.dumps({"relevant": False, "label": "X", "description": "d"}))
        _, _, relevant = call(c)
        assert relevant is False

    def test_explicit_acceptance(self):
        c = FakeGroq(json.dumps({"relevant": True, "label": "X", "description": "d"}))
        label, desc, relevant = call(c)
        assert (label, desc, relevant) == ("X", "d", True)

    def test_markdown_fenced_json_is_unwrapped(self):
        c = FakeGroq('```json\n{"relevant": false, "label": "X", "description": "d"}\n```')
        _, _, relevant = call(c)
        assert relevant is False


class TestFailsOpen:
    """Every one of these must KEEP the cluster. No verdict != delete."""

    def test_missing_relevant_key(self):
        c = FakeGroq(json.dumps({"label": "X", "description": "d"}))
        assert call(c)[2] is True

    def test_malformed_json(self):
        c = FakeGroq("this is not json at all")
        assert call(c)[2] is True

    def test_empty_response(self):
        c = FakeGroq("")
        assert call(c)[2] is True

    def test_api_raises(self):
        c = FakeGroq(raises=RuntimeError("connection reset"))
        assert call(c) == (None, None, True)

    def test_null_verdict(self):
        c = FakeGroq(json.dumps({"relevant": None, "label": "X", "description": "d"}))
        assert call(c)[2] is True

    def test_string_verdict_is_not_treated_as_rejection(self):
        # Only a literal boolean false rejects. "false" as a string is a model
        # formatting slip, not a considered verdict.
        c = FakeGroq(json.dumps({"relevant": "false", "label": "X", "description": "d"}))
        assert call(c)[2] is True

    def test_retries_before_giving_up(self):
        c = FakeGroq(raises=RuntimeError("boom"))
        call(c)
        assert len(c.calls) == 3, "should retry twice before failing open"


class TestPromptConstruction:
    def test_temperature_is_zero(self):
        # The default of 1.0 would let the same cluster be judged differently on
        # consecutive runs, making the dashboard flicker.
        c = FakeGroq(json.dumps({"relevant": True, "label": "X", "description": "d"}))
        call(c)
        assert c.calls[0]["temperature"] == 0

    @pytest.mark.parametrize("sensitivity", ["broad", "balanced", "high"])
    def test_each_sensitivity_injects_its_own_rule(self, sensitivity):
        c = FakeGroq(json.dumps({"relevant": True, "label": "X", "description": "d"}))
        call(c, sensitivity=sensitivity)
        prompt = c.calls[0]["messages"][0]["content"]
        assert _SENSITIVITY_RULES[sensitivity] in prompt

    def test_unknown_sensitivity_falls_back_to_balanced(self):
        c = FakeGroq(json.dumps({"relevant": True, "label": "X", "description": "d"}))
        call(c, sensitivity="nonsense")
        assert _SENSITIVITY_RULES["balanced"] in c.calls[0]["messages"][0]["content"]

    def test_topic_description_reaches_the_prompt(self):
        # Judging against a bare topic name cannot separate "Apple" the company
        # from the fruit — the user's own description is the discriminator.
        c = FakeGroq(json.dumps({"relevant": True, "label": "X", "description": "d"}))
        call(c, topic_description="Only battery supply-chain news")
        assert "Only battery supply-chain news" in c.calls[0]["messages"][0]["content"]

    def test_missing_topic_description_is_omitted_cleanly(self):
        c = FakeGroq(json.dumps({"relevant": True, "label": "X", "description": "d"}))
        call(c, topic_description=None)
        prompt = c.calls[0]["messages"][0]["content"]
        assert "WHAT THE USER WANTS" not in prompt

    def test_high_sensitivity_is_stricter_wording_than_broad(self):
        assert "TIGHT" in _SENSITIVITY_RULES["high"]
        assert "WIDE" in _SENSITIVITY_RULES["broad"]
