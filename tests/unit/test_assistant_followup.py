import pytest
from unittest.mock import patch, MagicMock
from app.assistant import Assistant
from conftest import make_mock_resp


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

SAMPLE_CUSTOMER_ROWS = {
    "lead": [{"id": "lead_001", "fname": "Alice", "email": "alice@example.com", "notes": ""}],
    "vehicle": [{"id": "veh_001", "year": 2021, "make": "Honda", "model": "Civic", "status": 1,
                 "trim": "LX", "mileage": 45000, "transmission": "Automatic", "comments": ""}],
    "dealer": [{"id": "dealer_001", "name": "City Honda", "email": "sales@cityhonda.com",
                "phone": "613-555-0100", "address1": "123 Main St", "address2": None,
                "city": "Ottawa", "province": "ON", "postal_code": "K1A 0A1"}],
}


def _db_for_followup(mock_db_cls, *, active=True, reply_count=0, vehicle_status=1, alt_vehicles=None):
    """Configure a mock CosmosDBClient for follow_up scenarios."""
    db = mock_db_cls.return_value

    conversation = {"id": "conv_001", "status": 1 if active else 0}

    def query_side_effect(container, query, params):
        if container == "conversations":
            return [conversation] if active else [{"id": "conv_001", "status": 0}]
        if container == "messages" and "COUNT" in query:
            return [reply_count]
        if container == "leads":
            return SAMPLE_CUSTOMER_ROWS["lead"]
        if container == "vehicles" and "TOP 3" in query:
            return alt_vehicles or []
        if container == "vehicles":
            v = SAMPLE_CUSTOMER_ROWS["vehicle"][0].copy()
            v["status"] = vehicle_status
            return [v]
        if container == "dealerships":
            return SAMPLE_CUSTOMER_ROWS["dealer"]
        return []

    db.query_items.side_effect = query_side_effect
    return db


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_happy_path_seq1(mock_chat, mock_factory, mock_db_cls, assistant):
    _db_for_followup(mock_db_cls)
    mock_chat.return_value = make_mock_resp("Re: Civic [ref: conv_001]\nJust checking in!")
    mock_factory.get_provider.return_value.send.return_value = True

    result = assistant.follow_up(ID_CONTEXT, sequence=1, start_time="2024-01-01T00:00:00Z")

    assert result is True
    mock_factory.get_provider.return_value.send.assert_called_once()
    mock_db_cls.return_value.save_message.assert_called_once()


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_aborts_on_inactive_conversation(mock_chat, mock_factory, mock_db_cls, assistant):
    _db_for_followup(mock_db_cls, active=False)

    result = assistant.follow_up(ID_CONTEXT, sequence=1, start_time="2024-01-01T00:00:00Z")

    assert result is False
    mock_chat.assert_not_called()


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_aborts_if_user_already_replied(mock_chat, mock_factory, mock_db_cls, assistant):
    _db_for_followup(mock_db_cls, reply_count=1)

    result = assistant.follow_up(ID_CONTEXT, sequence=1, start_time="2024-01-01T00:00:00Z")

    assert result is False
    mock_chat.assert_not_called()


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_aborts_and_closes_conv_when_vehicle_sold(mock_chat, mock_factory, mock_db_cls, assistant):
    db = _db_for_followup(mock_db_cls, vehicle_status=2)
    db.get_item_by_id.return_value = {"id": "conv_001", "status": 1}

    result = assistant.follow_up(ID_CONTEXT, sequence=1, start_time="2024-01-01T00:00:00Z")

    assert result is None  
    mock_chat.assert_not_called()
    
    db.update_item_in_container.assert_called_once()


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_seq2_injects_alt_vehicles_into_prompt(mock_chat, mock_factory, mock_db_cls, assistant):
    alts = [
        {"year": 2020, "make": "Toyota", "model": "Corolla", "trim": "LE"},
        {"year": 2019, "make": "Mazda", "model": "Mazda3", "trim": "GS"},
    ]
    _db_for_followup(mock_db_cls, alt_vehicles=alts)
    mock_chat.return_value = make_mock_resp("Re: Civic [ref: conv_001]\nHere are some alternatives!")

    assistant.follow_up(ID_CONTEXT, sequence=2, start_time="2024-01-01T00:00:00Z")

    
    prompt_messages = mock_chat.call_args[0][0]
    combined = " ".join(str(m) for m in prompt_messages)
    assert "Corolla" in combined
    assert "Mazda3" in combined


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_followup_seq2_no_alts_uses_fallback_text(mock_chat, mock_factory, mock_db_cls, assistant):
    _db_for_followup(mock_db_cls, alt_vehicles=[])
    mock_chat.return_value = make_mock_resp("Re: Civic [ref: conv_001]\nStill available!")

    assistant.follow_up(ID_CONTEXT, sequence=2, start_time="2024-01-01T00:00:00Z")

    prompt_messages = mock_chat.call_args[0][0]
    combined = " ".join(str(m) for m in prompt_messages)
    assert "No direct alternative" in combined