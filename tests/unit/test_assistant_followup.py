# tests/unit/test_assistant_followup.py
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

ID_CONTEXT = {
    "conversationId": "conv_001",
    "leadId": "lead_001",
    "vehicleId": "veh_001",
    "dealerId": "dealer_001",
}

SAMPLE_CUSTOMER_ROWS = {
    "lead": {"id": "lead_001", "fname": "Alice", "email": "alice@example.com", "notes": ""},
    "vehicle": {"id": "veh_001", "year": 2021, "make": "Honda", "model": "Civic", "status": 1,
                "trim": "LX", "mileage": 45000, "transmission": "Automatic", "comments": ""},
    "dealership": {"id": "dealer_001", "name": "City Honda", "email": "sales@cityhonda.com",
                   "phone": "613-555-0100", "address1": "123 Main St", "address2": None,
                   "city": "Ottawa", "province": "ON", "postal_code": "K1A 0A1"},
}

def _configure_db_mocks(assistant, active=True, reply_count=0, vehicle_status=1, alt_vehicles=None):
    assistant.dbcli.conversation_container.get_item_with_id.return_value = [{"id": "conv_001", "status": 1 if active else 0}]
    assistant.dbcli.message_container.query_user_items_with_conversation_and_time.return_value = [1] * reply_count
    
    customer = SAMPLE_CUSTOMER_ROWS.copy()
    customer["vehicle"] = customer["vehicle"].copy()
    customer["vehicle"]["status"] = vehicle_status
    assistant.hydrate_customer_context = MagicMock(return_value=customer)
    
    assistant.dbcli.vehicle_container.query_items_with_vehicle_and_dealership.return_value = alt_vehicles or []
    assistant.dbcli.conversation_container.get_conversation_by_lead.return_value = {"id": "conv_001", "status": 1}


@patch("app.assistant.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_happy_path_seq1(mock_chat, mock_factory, assistant):
    _configure_db_mocks(assistant)
    mock_chat.return_value = make_mock_resp("Re: Civic [ref: conv_001]\nJust checking in!")
    mock_factory.get_provider.return_value.send.return_value = True

    result = assistant.follow_up(ID_CONTEXT, sequence=1, start_time="2024-01-01T00:00:00Z")

    assert result is True
    mock_factory.get_provider.return_value.send.assert_called_once()
    assistant.dbcli.message_container.save_message.assert_called_once()

@patch("app.assistant.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_aborts_on_inactive_conversation(mock_chat, mock_factory, assistant):
    _configure_db_mocks(assistant, active=False)

    result = assistant.follow_up(ID_CONTEXT, sequence=1, start_time="2024-01-01T00:00:00Z")

    assert result is False
    mock_chat.assert_not_called()

@patch("app.assistant.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_aborts_if_user_already_replied(mock_chat, mock_factory, assistant):
    _configure_db_mocks(assistant, reply_count=1)

    result = assistant.follow_up(ID_CONTEXT, sequence=1, start_time="2024-01-01T00:00:00Z")

    assert result is False
    mock_chat.assert_not_called()

@patch("app.assistant.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_aborts_and_closes_conv_when_vehicle_sold(mock_chat, mock_factory, assistant):
    _configure_db_mocks(assistant, vehicle_status=2)

    result = assistant.follow_up(ID_CONTEXT, sequence=1, start_time="2024-01-01T00:00:00Z")

    assert result is None  
    mock_chat.assert_not_called()
    assistant.dbcli.conversation_container.update_item.assert_called_once()

@patch("app.assistant.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_seq2_injects_alt_vehicles_into_prompt(mock_chat, mock_factory, assistant):
    alts = [
        {"year": 2020, "make": "Toyota", "model": "Corolla", "trim": "LE"},
        {"year": 2019, "make": "Mazda", "model": "Mazda3", "trim": "GS"},
    ]
    _configure_db_mocks(assistant, alt_vehicles=alts)
    mock_chat.return_value = make_mock_resp("Re: Civic [ref: conv_001]\nHere are some alternatives!")

    assistant.follow_up(ID_CONTEXT, sequence=2, start_time="2024-01-01T00:00:00Z")

    prompt_messages = mock_chat.call_args[0][0]
    combined = " ".join(str(m) for m in prompt_messages)
    assert "Corolla" in combined
    assert "Mazda3" in combined

@patch("app.assistant.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_seq2_no_alts_uses_fallback_text(mock_chat, mock_factory, assistant):
    _configure_db_mocks(assistant, alt_vehicles=[])
    mock_chat.return_value = make_mock_resp("Re: Civic [ref: conv_001]\nStill available!")

    assistant.follow_up(ID_CONTEXT, sequence=2, start_time="2024-01-01T00:00:00Z")

    prompt_messages = mock_chat.call_args[0][0]
    combined = " ".join(str(m) for m in prompt_messages)
    assert "No direct alternative" in combined