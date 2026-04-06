import pytest
import json
from unittest.mock import patch, MagicMock
from app.assistant import Assistant
from conftest import make_mock_resp


@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        return Assistant()


def _routine_analysis():
    return {
        "intentCategory": "appointment",
        "intentAction": "request",
        "sentimentLabel": "positive",
        "tone": "positive",
        "urgency": "low",
        "intentConfidence": "high",
        "escalate": False,
        "summary": "Wants a test drive.",
    }


def _escalating_analysis():
    return {**_routine_analysis(), "escalate": True, "intentCategory": "pricing"}


# ---- contact() analysis pre-check ----

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_contact_analysis_escalation_skips_chat(mock_chat, mock_analysis_cls, mock_factory, mock_db, assistant, sample_customer):
    """If Analysis flags escalate before chat, chat must never be called."""
    mock_analysis_cls.return_value.analyze.return_value = _escalating_analysis()

    # also need _escalate to short-circuit; give it a minimal db
    mock_db.return_value.query_items.return_value = []
    mock_db.return_value.get_item_by_id.return_value = {"id": "conv_001", "status": 1}

    assistant.contact(sample_customer)

    mock_chat.assert_not_called()


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_contact_routine_analysis_proceeds_to_chat(mock_chat, mock_analysis_cls, mock_factory, mock_db, assistant, sample_customer):
    mock_analysis_cls.return_value.analyze.return_value = _routine_analysis()
    mock_chat.return_value = make_mock_resp("Re: Civic\nHi Alice!")
    mock_factory.get_provider.return_value.send.return_value = True

    assistant.contact(sample_customer)

    mock_chat.assert_called_once()


# ---- reply() analysis pre-check ----

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_reply_analysis_escalation_skips_chat(mock_chat, mock_analysis_cls, mock_factory, mock_db_cls, assistant, sample_received_email):
    mock_analysis_cls.return_value.analyze.return_value = _escalating_analysis()

    mock_db_cls.return_value.query_items.side_effect = [
        # chain lookup for in_reply_to
        [{"responseId": "resp_prev", "conversationId": "conv_001",
          "leadId": "lead_001", "vehicleId": "veh_001", "dealerId": "dealer_001"}],
        # messages for escalation thread (empty is fine)
        [],
    ]
    mock_db_cls.return_value.get_item_by_id.return_value = {"id": "conv_001", "status": 1}

    assistant.reply(sample_received_email)

    mock_chat.assert_not_called()