import pytest
from unittest.mock import patch, MagicMock
from app.assistant import Assistant
from conftest import make_mock_resp

@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        return Assistant()

def _db_with_chain(mock_db_cls, msg_doc=None):
    """Helper: DB returns a previous assistant message for chain lookup."""
    doc = msg_doc or {
        "responseId": "resp_prev",
        "conversationId": "conv_001",
        "leadId": "lead_001",
        "vehicleId": "veh_001",
        "dealerId": "dealer_001",
    }
    mock_db_cls.return_value.query_items.return_value = [doc]
    return mock_db_cls

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_reply_happy_path_with_chain(mock_chat, mock_analysis_cls, mock_factory, mock_db_cls, assistant, sample_received_email):
    _db_with_chain(mock_db_cls)
    mock_analysis_cls.return_value.analyze.return_value = {"escalate": False}
    mock_chat.return_value = make_mock_resp("Re: Civic\nSee you Saturday!", "resp_new")
    mock_factory.get_provider.return_value.reply.return_value = True

    assistant.reply(sample_received_email)

    mock_factory.get_provider.return_value.reply.assert_called_once()
    
    assert mock_db_cls.return_value.save_message.call_count == 2

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_reply_no_chain_falls_back_to_sender_lookup(mock_chat, mock_analysis_cls, mock_factory, mock_db_cls, assistant, sample_received_email):
    """When in_reply_to yields no chain, _resolve_context_from_sender is called."""
    mock_db_cls.return_value.query_items.return_value = []
    mock_analysis_cls.return_value.analyze.return_value = {"escalate": False}
    mock_chat.return_value = make_mock_resp("Re: Civic\nSee you Saturday!")
    mock_factory.get_provider.return_value.reply.return_value = True

    with patch.object(assistant, "_resolve_context_from_sender") as mock_resolve:
        mock_resolve.return_value = {
            "conversationId": "conv_001",
            "leadId": "lead_001",
            "vehicleId": "veh_001",
            "dealerId": "dealer_001",
        }
        assistant.reply(sample_received_email)
        mock_resolve.assert_called_once_with(sample_received_email["sender"])

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_reply_aborts_if_context_unresolvable(mock_chat, mock_analysis_cls, mock_factory, mock_db_cls, assistant, sample_received_email):
    mock_db_cls.return_value.query_items.return_value = []

    with patch.object(assistant, "_resolve_context_from_sender", return_value=None):
        assistant.reply(sample_received_email)

    mock_chat.assert_not_called()
    mock_factory.get_provider.assert_not_called()

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_reply_escalation_skips_send(mock_chat, mock_analysis_cls, mock_factory, mock_db_cls, assistant, sample_received_email):
    _db_with_chain(mock_db_cls)
    mock_analysis_cls.return_value.analyze.return_value = {"escalate": True, "reason": "trade_inquiry", "intentCategory": "pricing"}

    assistant.reply(sample_received_email)

    
    mock_factory.get_provider.return_value.reply.assert_not_called()
    
    
    assert mock_factory.get_provider.return_value.send.call_count >= 1

    
    assert mock_db_cls.return_value.save_message.call_count == 2

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_reply_no_in_reply_to_still_attempts_sender_lookup(mock_chat, mock_analysis_cls, mock_factory, mock_db_cls, assistant, sample_received_email):
    sample_received_email["in_reply_to"] = ""
    mock_analysis_cls.return_value.analyze.return_value = {"escalate": False}
    mock_chat.return_value = make_mock_resp("Re: Civic\nSounds good!")
    mock_factory.get_provider.return_value.reply.return_value = True

    with patch.object(assistant, "_resolve_context_from_sender") as mock_resolve:
        mock_resolve.return_value = {
            "conversationId": "conv_001", "leadId": "lead_001",
            "vehicleId": "veh_001", "dealerId": "dealer_001",
        }
        assistant.reply(sample_received_email)
        mock_resolve.assert_called_once()