import json
import pytest
from unittest.mock import patch
from app.assistant import Assistant


@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        return Assistant()

ID_CONTEXT = {
    "conversationId": "conv_001",
    "leadId": "lead_001",
    "vehicleId": "veh_001",
    "dealerId": "dealer_001",
}

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
def test_escalate_returns_false_for_non_escalation(mock_factory, mock_db_cls, assistant):
    result = assistant._escalate('{"escalate": false}', "alice@example.com", ID_CONTEXT)
    assert result is False
    mock_factory.get_provider.assert_not_called()


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
def test_escalate_returns_false_for_bad_json(mock_factory, mock_db_cls, assistant):
    result = assistant._escalate("not json", "alice@example.com", ID_CONTEXT)
    assert result is False

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
def test_escalate_closes_conversation(mock_factory, mock_db_cls, assistant):
    db = mock_db_cls.return_value
    db.query_items.return_value = []  
    db.get_item_by_id.return_value = {"id": "conv_001", "status": 1}

    payload = json.dumps({"escalate": True, "intentCategory": "pricing", "summary": "wants price"})
    assistant._escalate(payload, "alice@example.com", ID_CONTEXT)

    
    db.update_item_in_container.assert_called_once()
    updated = db.update_item_in_container.call_args[0][1]
    assert updated["status"] == 0


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
def test_escalate_sends_ack_to_customer(mock_factory, mock_db_cls, assistant):
    db = mock_db_cls.return_value
    db.query_items.return_value = []
    db.get_item_by_id.return_value = {"id": "conv_001", "status": 1}

    payload = json.dumps({"escalate": True, "intentCategory": "trade_in", "summary": "wants trade"})
    assistant._escalate(payload, "alice@example.com", ID_CONTEXT)

    send_calls = mock_factory.get_provider.return_value.send.call_args_list
    customer_ack = [c for c in send_calls if c[0][0] == "alice@example.com"]
    assert len(customer_ack) == 1

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
def test_escalate_emails_dealer_when_thread_exists(mock_factory, mock_db_cls, assistant):
    db = mock_db_cls.return_value
    thread = [
        {"role": "assistant", "body": "Hi Alice", "subject": "Re: Civic", "timestamp": "2024-01-01T10:00:00Z", "dealerId": "dealer_001"},
        {"role": "user", "body": "What is the price?", "subject": "Re: Civic", "timestamp": "2024-01-01T10:05:00Z", "dealerId": "dealer_001"},
    ]
    db.query_items.side_effect = [
        thread,           
        [{"id": "dealer_001", "email": "sales@cityhonda.com"}],  
    ]
    db.get_item_by_id.return_value = {"id": "conv_001", "status": 1}

    payload = json.dumps({"escalate": True, "intentCategory": "pricing", "summary": "wants price"})
    assistant._escalate(payload, "alice@example.com", ID_CONTEXT)

    send_calls = mock_factory.get_provider.return_value.send.call_args_list
    dealer_email_call = [c for c in send_calls if c[0][0] == "sales@cityhonda.com"]
    assert len(dealer_email_call) == 1

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
def test_escalate_returns_true_on_success(mock_factory, mock_db_cls, assistant):
    db = mock_db_cls.return_value
    db.query_items.return_value = []
    db.get_item_by_id.return_value = {"id": "conv_001", "status": 1}

    payload = json.dumps({"escalate": True, "intentCategory": "financing", "summary": "wants financing"})
    result = assistant._escalate(payload, "alice@example.com", ID_CONTEXT)
    assert result is True