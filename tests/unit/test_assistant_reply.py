# tests/unit/test_assistant_reply.py
import pytest
from unittest.mock import patch, MagicMock
from app.assistant.assistant import Assistant
from conftest import make_mock_resp

@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        a = Assistant()
        a.dbcli = MagicMock()
        return a

def _db_with_chain(assistant):
    assistant.dbcli.conversation_container.get_item_with_id.return_value = {
        "id": "conv_001", "leadId": "lead_001", "vehicleId": "veh_001", "dealerId": "dealer_001"
    }
    assistant.dbcli.message_container.query_assistant_items_with_msg_id.return_value = [{"responseId": "resp_prev"}]

@patch("app.assistant.assistant.EmailFactory")
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_reply_happy_path_with_chain(mock_chat, mock_analysis_cls, mock_factory, assistant, sample_received_email):
    _db_with_chain(assistant)
    mock_analysis_cls.return_value.analyze.return_value = {"escalate": False}
    mock_chat.return_value = make_mock_resp("Re: Civic\nSee you Saturday!", "resp_new")
    mock_factory.get_provider.return_value.reply.return_value = True

    assistant.reply(sample_received_email)

    mock_factory.get_provider.return_value.reply.assert_called_once()
    assert assistant.dbcli.message_container.save_message.call_count == 2

@patch("app.assistant.assistant.EmailFactory")
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_reply_no_chain_falls_back_to_sender_lookup(mock_chat, mock_analysis_cls, mock_factory, assistant, sample_received_email):
    sample_received_email["in_reply_to"] = "random_string"
    assistant.dbcli.conversation_container.get_item_with_id.return_value = None
    mock_analysis_cls.return_value.analyze.return_value = {"escalate": False}
    mock_chat.return_value = make_mock_resp("Re: Civic\nSee you Saturday!")
    mock_factory.get_provider.return_value.reply.return_value = True

    with patch.object(assistant, "resolve_context_from_sender") as mock_resolve:
        mock_resolve.return_value = {
            "conversationId": "conv_001", "leadId": "lead_001",
            "vehicleId": "veh_001", "dealerId": "dealer_001",
        }
        assistant.reply(sample_received_email)
        mock_resolve.assert_called_once_with(sample_received_email["sender"])

@patch("app.assistant.assistant.EmailFactory")
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_reply_aborts_if_context_unresolvable(mock_chat, mock_analysis_cls, mock_factory, assistant, sample_received_email):
    sample_received_email["in_reply_to"] = "random_string"
    assistant.dbcli.conversation_container.get_item_with_id.return_value = None

    with patch.object(assistant, "resolve_context_from_sender", return_value=None):
        assistant.reply(sample_received_email)

    mock_chat.assert_not_called()
    mock_factory.get_provider.assert_not_called()

@patch("app.assistant.escalation.EmailFactory") 
@patch("app.assistant.assistant.EmailFactory")  
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_reply_escalation_skips_send(mock_chat, mock_analysis_cls, mock_assistant_factory, mock_escalation_factory, assistant, sample_received_email):
    _db_with_chain(assistant)
    mock_analysis_cls.return_value.analyze.return_value = {"escalate": True, "reason": "trade_inquiry", "intentCategory": "pricing"}

    assistant.reply(sample_received_email)

    # Standard reply should be skipped
    mock_assistant_factory.get_provider.return_value.reply.assert_not_called()
    
    # Escalation emails (to dealer and customer) should be triggered via the escalation factory
    assert mock_escalation_factory.get_provider.return_value.send.call_count >= 1
    
@patch("app.assistant.assistant.EmailFactory")
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_reply_no_in_reply_to_still_attempts_sender_lookup(mock_chat, mock_analysis_cls, mock_factory, assistant, sample_received_email):
    sample_received_email["in_reply_to"] = ""
    mock_analysis_cls.return_value.analyze.return_value = {"escalate": False}
    mock_chat.return_value = make_mock_resp("Re: Civic\nSounds good!")
    mock_factory.get_provider.return_value.reply.return_value = True

    with patch.object(assistant, "resolve_context_from_sender") as mock_resolve:
        mock_resolve.return_value = {
            "conversationId": "conv_001", "leadId": "lead_001",
            "vehicleId": "veh_001", "dealerId": "dealer_001",
        }
        assistant.reply(sample_received_email)
        mock_resolve.assert_called_once()