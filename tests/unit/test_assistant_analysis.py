# tests/unit/test_assistant_analysis.py
import json
import pytest
from unittest.mock import patch, MagicMock
from app.assistant.analysis import Analysis
from conftest import make_mock_resp

@pytest.fixture
def analysis():
    with patch("app.assistant.gpt.OpenAI"):
        return Analysis()

def test_analyze_returns_parsed_dict(analysis):
    payload = {
        "intentCategory": "appointment",
        "intentAction": "request",
        "sentimentLabel": "positive",
        "tone": "positive",
        "urgency": "low",
        "intentConfidence": "high",
        "escalate": False,
        "summary": "Lead wants to book a test drive.",
    }
    with patch.object(analysis, "chat", return_value=make_mock_resp(json.dumps(payload))):
        result = analysis.analyze("Can I book a test drive Saturday?")
    assert result["escalate"] is False
    assert result["intentCategory"] == "appointment"

def test_analyze_sets_escalate_true_for_pricing(analysis):
    payload = {
        "intentCategory": "pricing",
        "intentAction": "inquire",
        "sentimentLabel": "neutral",
        "tone": "neutral",
        "urgency": "medium",
        "intentConfidence": "high",
        "escalate": True,
        "summary": "Lead asking about price.",
    }
    with patch.object(analysis, "chat", return_value=make_mock_resp(json.dumps(payload))):
        result = analysis.analyze("What's your best price on the Civic?")
    assert result["escalate"] is True

def test_analyze_falls_back_on_bad_json(analysis):
    with patch.object(analysis, "chat", return_value=make_mock_resp("not json at all")):
        result = analysis.analyze("some message")
    
    assert result["escalate"] is True
    assert result["intentCategory"] == "out_of_scope"
    assert result["summary"] == "Unable to analyze lead message"

def test_analyze_falls_back_on_empty_response(analysis):
    with patch.object(analysis, "chat", return_value=make_mock_resp("")):
        result = analysis.analyze("some message")
    assert result["escalate"] is True