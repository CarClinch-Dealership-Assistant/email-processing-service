# tests/unit/test_assistant_escalation.py
import json
import pytest
from unittest.mock import patch, MagicMock
from app.assistant.assistant import Assistant

@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        a = Assistant()
        a.dbcli = MagicMock()
        return a

ID_CONTEXT = {
    "conversationId": "conv_001",
    "leadId": "lead_001",
    "vehicleId": "veh_001",
    "dealerId": "dealer_001",
}

@patch("app.assistant.escalation.EmailFactory")
def test_escalate_returns_false_for_non_escalation(mock_factory, assistant):
    result = assistant.escalate('{"escalate": false}', "alice@example.com", ID_CONTEXT)
    assert result is False
    mock_factory.get_provider.assert_not_called()

@patch("app.assistant.escalation.EmailFactory")
def test_escalate_returns_false_for_bad_json(mock_factory, assistant):
    result = assistant.escalate("not json", "alice@example.com", ID_CONTEXT)
    assert result is False

@patch("app.assistant.escalation.EmailFactory")
def test_escalate_closes_conversation(mock_factory, assistant):
    assistant.dbcli.message_container.query_items_with_conversation.return_value = []
    assistant.dbcli.conversation_container.get_conversation_by_lead.return_value = {"id": "conv_001", "status": 1}

    payload = json.dumps({"escalate": True, "intentCategory": "pricing", "summary": "wants price"})
    assistant.escalate(payload, "alice@example.com", ID_CONTEXT)

    assistant.dbcli.conversation_container.update_item.assert_called_once()
    updated = assistant.dbcli.conversation_container.update_item.call_args[0][0]
    assert updated["status"] == 0

@patch("app.assistant.escalation.EmailFactory")
def test_escalate_sends_ack_to_customer(mock_factory, assistant):
    assistant.dbcli.message_container.query_items_with_conversation.return_value = []
    assistant.dbcli.conversation_container.get_conversation_by_lead.return_value = {"id": "conv_001", "status": 1}

    payload = json.dumps({"escalate": True, "intentCategory": "trade_in", "summary": "wants trade"})
    assistant.escalate(payload, "alice@example.com", ID_CONTEXT)

    send_calls = mock_factory.get_provider.return_value.send.call_args_list
    customer_ack = [c for c in send_calls if c[0][0] == "alice@example.com"]
    assert len(customer_ack) == 1

@patch("app.assistant.escalation.EmailFactory")
def test_escalate_emails_dealer_when_thread_exists(mock_factory, assistant):
    thread = [
        {"role": "assistant", "body": "Hi Alice", "subject": "Re: Civic", "timestamp": "2024-01-01T10:00:00Z", "dealerId": "dealer_001"},
        {"role": "user", "body": "What is the price?", "subject": "Re: Civic", "timestamp": "2024-01-01T10:05:00Z", "dealerId": "dealer_001"},
    ]
    assistant.dbcli.message_container.query_items_with_conversation.return_value = thread
    assistant.dbcli.dealerships_container.get_item_with_id.return_value = {"id": "dealer_001", "email": "sales@cityhonda.com"}
    assistant.dbcli.conversation_container.get_conversation_by_lead.return_value = {"id": "conv_001", "status": 1}

    payload = json.dumps({"escalate": True, "intentCategory": "pricing", "summary": "wants price"})
    assistant.escalate(payload, "alice@example.com", ID_CONTEXT)

    send_calls = mock_factory.get_provider.return_value.send.call_args_list
    dealer_email_call = [c for c in send_calls if c[0][0] == "sales@cityhonda.com"]
    assert len(dealer_email_call) == 1

@patch("app.assistant.escalation.EmailFactory")
def test_escalate_returns_true_on_success(mock_factory, assistant):
    assistant.dbcli.message_container.query_items_with_conversation.return_value = []
    assistant.dbcli.conversation_container.get_conversation_by_lead.return_value = {"id": "conv_001", "status": 1}

    payload = json.dumps({"escalate": True, "intentCategory": "financing", "summary": "wants financing"})
    result = assistant.escalate(payload, "alice@example.com", ID_CONTEXT)
    assert result is True