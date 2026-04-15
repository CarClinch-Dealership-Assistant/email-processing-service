# tests/unit/test_assistant_appointment.py
import pytest
import datetime
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

def test_get_available_timeslots_no_bookings(assistant):
    assistant.dbcli.appointments_container.query_appointments_with_dealer_and_date.return_value = []
    
    slots = assistant.get_available_timeslots("dealer_001", "2024-05-15")
    assert len(slots) == 9  # 9 AM to 5 PM (17) is 9 slots
    assert 9 in slots
    assert 17 in slots

def test_get_available_timeslots_with_bookings(assistant):
    assistant.dbcli.appointments_container.query_appointments_with_dealer_and_date.return_value = [
        {"timeslot": "10"}, {"timeslot": "14"}
    ]
    
    slots = assistant.get_available_timeslots("dealer_001", "2024-05-15")
    assert len(slots) == 7
    assert 10 not in slots
    assert 14 not in slots
    assert 9 in slots

def test_get_available_timeslots_with_time_range(assistant):
    assistant.dbcli.appointments_container.query_appointments_with_dealer_and_date.return_value = []
    
    slots = assistant.get_available_timeslots("dealer_001", "2024-05-15", time_range=[13, 16])
    assert slots == [13, 14, 15, 16]

def test_get_available_timeslots_fallback_if_range_fully_booked(assistant):
    # If they ask for 1-3 PM, but 1, 2, and 3 PM are all booked, it should fallback to all available slots
    assistant.dbcli.appointments_container.query_appointments_with_dealer_and_date.return_value = [
        {"timeslot": "13"}, {"timeslot": "14"}, {"timeslot": "15"}
    ]
    slots = assistant.get_available_timeslots("dealer_001", "2024-05-15", time_range=[13, 15])
    assert len(slots) > 0
    assert 13 not in slots
    assert 9 in slots

def test_get_candidate_dates_parses_llm_string(assistant):
    date_str = "2024-05-15, 2024-05-16, 2024-05-17"
    candidates = assistant.get_candidate_dates(date_str)
    assert len(candidates) == 3
    assert "2024-05-15" in candidates

def test_get_candidate_dates_fallback_next_5_biz_days(assistant):
    # Provide garbage string so it falls back
    candidates = assistant.get_candidate_dates("garbage date string")
    assert len(candidates) == 5
    # Verify no weekends (0 = Monday, 6 = Sunday)
    for date_str in candidates:
        parsed = datetime.date.fromisoformat(date_str)
        assert parsed.weekday() < 5

def test_process_booking_intent_auto_upgrades_to_confirm(assistant):
    analysis = {
        "intentCategory": "appointment",
        "intentAction": "request_time",
        "appointmentDate": "2024-05-15",
        "appointmentTime": 14
    }
    with patch.object(assistant, "finalize_booking") as mock_finalize:
        context, is_finalized = assistant.process_booking_intent(analysis, ID_CONTEXT, "test@test.com")
        assert is_finalized is True
        mock_finalize.assert_called_once()
        # Verify it passed the parsed dict correctly
        passed_parsed = mock_finalize.call_args[0][1]
        assert passed_parsed["date"] == "2024-05-15"
        assert passed_parsed["timeslot"] == 14

def test_process_booking_intent_downgrades_multi_date_confirm(assistant):
    analysis = {
        "intentCategory": "appointment",
        "intentAction": "confirm_booking",
        "appointmentDate": "2024-05-15, 2024-05-16",
        "appointmentTime": 14
    }
    with patch.object(assistant, "finalize_booking") as mock_finalize:
        context, is_finalized = assistant.process_booking_intent(analysis, ID_CONTEXT, "test@test.com")
        
        # It should downgrade to request_date_range and NOT finalize
        assert is_finalized is False
        mock_finalize.assert_not_called()
        assert analysis["intentAction"] == "request_date_range"

def test_generate_ics(assistant):
    dealer = {"name": "Test Dealer", "address1": "123 Main", "city": "Ottawa"}
    vehicle = {"year": 2020, "make": "Honda", "model": "Civic"}
    
    ics = assistant.generate_ics(dealer, vehicle, "2024-05-15", 14)
    
    assert "BEGIN:VCALENDAR" in ics
    assert "DTSTART:20240515T140000" in ics
    assert "DTEND:20240515T150000" in ics
    assert "LOCATION:Test Dealer - 123 Main, Ottawa" in ics

@patch("app.assistant.appointment.EmailFactory")
def test_finalize_booking_sends_emails_and_updates_db(mock_factory, assistant, sample_customer):
    assistant.hydrate_customer_context = MagicMock(return_value=sample_customer)
    
    parsed = {"date": "2024-05-15", "timeslot": 14}
    
    assistant.finalize_booking(ID_CONTEXT, parsed, "alice@example.com")
    
    # Verify DB updates
    assistant.dbcli.appointments_container.update_item.assert_called_once()
    assistant.dbcli.leads_container.update_item.assert_called_once()
    assistant.dbcli.message_container.save_message.assert_called_once()
    
    # Verify Emails (Customer + Dealer sent via Send)
    send_calls = mock_factory.get_provider.return_value.send.call_args_list
    customer_email_calls = [c for c in send_calls if c[0][0] == "alice@example.com"]
    dealer_email_calls = [c for c in send_calls if c[0][0] == "sales@cityhonda.com"]
    
    assert len(customer_email_calls) == 1
    assert len(dealer_email_calls) == 1
    
    # Verify ICS attachment is in the customer email call
    attachments = customer_email_calls[0][1].get("attachments")
    assert attachments is not None
    assert attachments[0][0] == "invite.ics"