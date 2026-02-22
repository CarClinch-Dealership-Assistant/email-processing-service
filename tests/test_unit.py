import os
from dotenv import load_dotenv
from unittest.mock import MagicMock, patch
import pytest
from function_app import build_email_body, send_email
from mail_template import build_email_template, content

load_dotenv()

"""
UNIT TESTS:
this test file focuses on unit tests on logic for the individual functions 
in function_app.py and mail_template.py
the tests verify that the email template is correctly built w the provided sections and that 
the email body is rendered with the expected content based on the input data
"""

@pytest.fixture
# this fixture provides a sample input data dictionary that can be used in the tests below. It includes a lead, vehicle, and dealership section with realistic values.
def sample_input_data():
    return {
        "lead": {
            "fname": "Alice",
            "lname": "Yang",
            "email": "alice@example.com",
        },
        "vehicle": {
            "year": 2022,
            "make": "Toyota",
            "model": "Corolla",
            "trim": "LE",
            "status": 0,  # 0 = new, 1 = used
        },
        "dealership": {
            "email": "sales@dealer.com",
            "phone": "555-123-4567",
            "address1": "123 Main St",
            "address2": "Unit 4",
            "city": "Ottawa",
            "province": "ON",
            "postal_code": "K1A0B1",
        },
    }

# this test verifies that the build_email_template function 
# correctly injects the provided lead and dealership html 
# sections into the overall email template it checks that 
# the placeholders are replaced and that the resulting 
# string contains the expected content
def test_build_email_template_injects_sections():
    lead_html = "<p>Hello Lead</p>"
    dealership_html = "<p>Dealer block</p>"

    result = build_email_template(lead_html, dealership_html)

    assert "{customer}" not in result
    assert "{dealership}" not in result
    assert lead_html in result
    assert dealership_html in result
    assert "<html" in result and "</html>" in result

# this test checks that the build_email_body function correctly 
# formats the email body based on the input data it verifies that 
# the lead's name, vehicle details, and dealership contact 
# information are all included in the generated email content.
def test_build_email_body_renders_expected_fields(sample_input_data):
    body = build_email_body(sample_input_data)

    # sanity checks
    assert "Hello Alice" in body
    assert "2022 Toyota Corolla LE" in body
    assert "new model" in body  # status 0 -> "new"
    assert "sales@dealer.com" in body
    assert "555-123-4567" in body
    assert "123 Main St" in body
    assert "Ottawa, ON K1A0B1" in body

# this test modifies the vehicle status to 1 meaning "used" 
# and checks that the email body reflects this change by 
# including "used model" instead of "new model"
def test_build_email_body_handles_used_vehicle(sample_input_data):
    sample_input_data["vehicle"]["status"] = 1  # used
    body = build_email_body(sample_input_data)

    assert "used model" in body
    assert "new model" not in body


@patch("function_app.EmailClient")
# this patch replaces the EmailClient class in function_app w a mock object 
# for duration of the test so we can verify that the send_email function 
# interacts w the email client as expected wo actually sending an email
def test_send_email_uses_email_client_and_returns_string(mock_email_client_cls, sample_input_data, monkeypatch):
    # load env
    monkeypatch.setenv("ACS_CONNECTION_STRING", os.getenv("ACS_CONNECTION_STRING"))
    monkeypatch.setenv("SENDER_ADDRESS", os.getenv("SENDER_ADDRESS"))

    # mock EmailClient instance and poller
    mock_email_client = MagicMock()
    mock_poller = MagicMock()
    mock_email_client.begin_send.return_value = mock_poller
    mock_poller.result.return_value = None
    mock_email_client_cls.from_connection_string.return_value = mock_email_client

    result = send_email(sample_input_data)

    # assert
    mock_email_client_cls.from_connection_string.assert_called_once()
    mock_email_client.begin_send.assert_called_once()
    mock_poller.result.assert_called_once()

    assert result == "Email sent"

    # inspect payload
    args, kwargs = mock_email_client.begin_send.call_args
    message = args[0]

    assert message["senderAddress"] == os.getenv("SENDER_ADDRESS")
    assert "content" in message
    assert "html" in message["content"]
    assert "CarClinch Email" in message["content"]["html"]
    # rn it is hardcoded as rongjunfeng09@gmail.com; 
    # we can uncomment when we actually email to the lead's email
    assert message["recipients"]["to"][0]["address"] == sample_input_data["lead"]["email"]
