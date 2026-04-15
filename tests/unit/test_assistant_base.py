# tests/unit/test_assistant_helpers.py
import pytest
from unittest.mock import patch, MagicMock
from app.assistant.assistant import Assistant

@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        a = Assistant()
        a.dbcli = MagicMock()
        return a

def test_process_response_splits_subject_and_body(assistant):
    subject, body = assistant.process_response("Subject Line\nHello there\nSecond line")
    assert subject == "Subject Line"
    assert "Hello there" in body

def test_process_response_newlines_converted_to_br(assistant):
    _, body = assistant.process_response("Subject\nLine one\nLine two")
    assert "<br />" in body

def test_process_response_no_body(assistant):
    subject, body = assistant.process_response("Only a subject")
    assert subject == "Only a subject"
    assert body == ""

def test_formatting_data_used_status(assistant, sample_customer):
    data = assistant.get_formatting_data(sample_customer)
    assert data["vehicle_status"] == "used"   

def test_formatting_data_new_status(assistant, sample_customer):
    sample_customer["vehicle"]["status"] = 0
    data = assistant.get_formatting_data(sample_customer)
    assert data["vehicle_status"] == "new"

def test_formatting_data_address2_appended(assistant, sample_customer):
    sample_customer["dealership"]["address2"] = "Suite 5"
    data = assistant.get_formatting_data(sample_customer)
    assert "Suite 5" in data["dealership_address"]

def test_formatting_data_notes_list_joined(assistant, sample_customer):
    sample_customer["lead"]["notes"] = [
        {"text": "Interested in financing"},
        {"text": "Prefers automatic"},
    ]
    data = assistant.get_formatting_data(sample_customer)
    assert "Interested in financing" in data["lead_notes"]
    assert "Prefers automatic" in data["lead_notes"]

def test_resolve_context_no_lead_returns_none(assistant):
    assistant.dbcli.leads_container.query_items_with_email.return_value = []
    result = assistant.resolve_context_from_sender("Unknown <nobody@example.com>")
    assert result is None

def test_resolve_context_no_active_conversation_returns_none(assistant):
    assistant.dbcli.leads_container.query_items_with_email.return_value = [{"id": "lead_001", "email": "alice@example.com"}]
    assistant.dbcli.conversation_container.query_items_with_lead.return_value = []
    result = assistant.resolve_context_from_sender("Alice <alice@example.com>")
    assert result is None

def test_resolve_context_returns_context_dict(assistant):
    assistant.dbcli.leads_container.query_items_with_email.return_value = [{"id": "lead_001", "email": "alice@example.com"}]
    assistant.dbcli.conversation_container.query_items_with_lead.return_value = [{"id": "conv_001", "vehicleId": "veh_001", "dealerId": "dealer_001"}]
    result = assistant.resolve_context_from_sender("Alice <alice@example.com>")
    assert result["leadId"] == "lead_001"
    assert result["conversationId"] == "conv_001"