# tests/unit/test_assistant_analysis_precheck.py
import pytest
import json
from unittest.mock import patch, MagicMock
from app.assistant.assistant import Assistant
from conftest import make_mock_resp

@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        a = Assistant()
        a.dbcli = MagicMock()
        return a

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

@patch("app.assistant.assistant.EmailFactory")
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_contact_analysis_escalation_skips_chat(mock_chat, mock_analysis_cls, mock_factory, assistant, sample_customer):
    mock_analysis_cls.return_value.analyze.return_value = _escalating_analysis()
    assistant.dbcli.conversation_container.get_item_with_id.return_value = {"id": "conv_001", "status": 1}

    assistant.contact(sample_customer)
    mock_chat.assert_not_called()

@patch("app.assistant.assistant.EmailFactory")
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_contact_routine_analysis_proceeds_to_chat(mock_chat, mock_analysis_cls, mock_factory, assistant, sample_customer):
    mock_analysis_cls.return_value.analyze.return_value = _routine_analysis()
    mock_chat.return_value = make_mock_resp("Re: Civic\nHi Alice!")
    mock_factory.get_provider.return_value.send.return_value = True

    assistant.contact(sample_customer)
    mock_chat.assert_called_once()

@patch("app.assistant.assistant.EmailFactory")
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_reply_analysis_escalation_skips_chat(mock_chat, mock_analysis_cls, mock_factory, assistant, sample_received_email):
    mock_analysis_cls.return_value.analyze.return_value = _escalating_analysis()
    assistant.dbcli.conversation_container.get_item_with_id.return_value = {"id": "conv_001", "leadId": "lead_001", "vehicleId": "veh_001", "dealerId": "dealer_001", "status": 1}
    assistant.dbcli.message_container.query_assistant_items_with_msg_id.return_value = [{"responseId": "resp_prev"}]

    assistant.reply(sample_received_email)
    mock_chat.assert_not_called()