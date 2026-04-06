import pytest
from unittest.mock import patch, MagicMock
from app.assistant import Assistant

@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        return Assistant()

#  _process_response 

def test_process_response_splits_subject_and_body(assistant):
    subject, body = assistant._process_response("Subject Line\nHello there\nSecond line")
    assert subject == "Subject Line"
    assert "Hello there" in body

def test_process_response_newlines_converted_to_br(assistant):
    _, body = assistant._process_response("Subject\nLine one\nLine two")
    assert "<br />" in body

def test_process_response_no_body(assistant):
    subject, body = assistant._process_response("Only a subject")
    assert subject == "Only a subject"
    assert body == ""

#  _get_formatting_data 

def test_formatting_data_used_status(assistant, sample_customer):
    data = assistant._get_formatting_data(sample_customer)
    assert data["vehicle_status"] == "used"   # status=1 → used

def test_formatting_data_new_status(assistant, sample_customer):
    sample_customer["vehicle"]["status"] = 0
    data = assistant._get_formatting_data(sample_customer)
    assert data["vehicle_status"] == "new"

def test_formatting_data_address2_appended(assistant, sample_customer):
    sample_customer["dealership"]["address2"] = "Suite 5"
    data = assistant._get_formatting_data(sample_customer)
    assert "Suite 5" in data["dealership_address"]

def test_formatting_data_notes_list_joined(assistant, sample_customer):
    sample_customer["lead"]["notes"] = [
        {"text": "Interested in financing"},
        {"text": "Prefers automatic"},
    ]
    data = assistant._get_formatting_data(sample_customer)
    assert "Interested in financing" in data["lead_notes"]
    assert "Prefers automatic" in data["lead_notes"]

#  _resolve_context_from_sender 

@patch("app.assistant.CosmosDBClient")
def test_resolve_context_no_lead_returns_none(mock_db_cls, assistant):
    mock_db_cls.return_value.query_items.return_value = []
    result = assistant._resolve_context_from_sender("Unknown <nobody@example.com>")
    assert result is None

@patch("app.assistant.CosmosDBClient")
def test_resolve_context_no_active_conversation_returns_none(mock_db_cls, assistant):
    db = mock_db_cls.return_value
    db.query_items.side_effect = [
        [{"id": "lead_001", "email": "alice@example.com"}],  # lead found
        [],  # no active conversation
    ]
    result = assistant._resolve_context_from_sender("Alice <alice@example.com>")
    assert result is None

@patch("app.assistant.CosmosDBClient")
def test_resolve_context_returns_context_dict(mock_db_cls, assistant):
    db = mock_db_cls.return_value
    db.query_items.side_effect = [
        [{"id": "lead_001", "email": "alice@example.com"}],
        [{"id": "conv_001", "vehicleId": "veh_001", "dealerId": "dealer_001"}],
    ]
    result = assistant._resolve_context_from_sender("Alice <alice@example.com>")
    assert result["leadId"] == "lead_001"
    assert result["conversationId"] == "conv_001"