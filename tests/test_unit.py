import os
from dotenv import load_dotenv
from unittest.mock import MagicMock, patch
import pytest
from function_app import build_email_body, send_email, store_message
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
            "status": 0,
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
        "conversationId": "conv_test123"
    }

# build_email_template test

# this test checks that the build_email_template function 
# correctly injects the provided lead and dealership 
# HTML sections into the overall email template.
def test_build_email_template_injects_sections():
    lead_html = "<p>Hello Lead</p>"
    dealership_html = "<p>Dealer block</p>"

    result = build_email_template(lead_html, dealership_html)

    assert "{customer}" not in result
    assert "{dealership}" not in result
    assert lead_html in result
    assert dealership_html in result
    assert "<html" in result and "</html>" in result

# build_email_body tests

# this test verifies that the build_email_body function 
# correctly renders the email body w the sample input data
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

# send_email tests; docoupled them from each other

@patch("function_app.EmailClient")
# this test checks that send_email returns a dictionary w the expected keys: acsOperationId, emailBody, and messageId
def test_send_email_returns_dict_with_expected_keys(mock_email_client_cls, sample_input_data, monkeypatch):
    monkeypatch.setenv("ACS_CONNECTION_STRING", os.getenv("ACS_CONNECTION_STRING", "dummy"))
    monkeypatch.setenv("SENDER_ADDRESS", os.getenv("SENDER_ADDRESS", "dummy@example.com"))

    mock_email_client = MagicMock()
    mock_poller = MagicMock()
    mock_email_client.begin_send.return_value = mock_poller
    mock_poller.result.return_value = {"id": "acs-test-id-123"}
    mock_email_client_cls.from_connection_string.return_value = mock_email_client

    result = send_email(sample_input_data)

    assert isinstance(result, dict)
    assert "acsOperationId" in result
    assert "emailBody" in result
    assert "messageId" in result


@patch("function_app.EmailClient")
# this test verifies that the acsOperationId returned by send_email matches the id returned by the mocked poller.result(), 
# ensuring that the function correctly captures and returns the operation ID from ACS.
def test_send_email_acs_operation_id_matches_poller_result(mock_email_client_cls, sample_input_data, monkeypatch):
    monkeypatch.setenv("ACS_CONNECTION_STRING", os.getenv("ACS_CONNECTION_STRING", "dummy"))
    monkeypatch.setenv("SENDER_ADDRESS", os.getenv("SENDER_ADDRESS", "dummy@example.com"))

    mock_email_client = MagicMock()
    mock_poller = MagicMock()
    mock_email_client.begin_send.return_value = mock_poller
    mock_poller.result.return_value = {"id": "acs-test-id-123"}
    mock_email_client_cls.from_connection_string.return_value = mock_email_client

    result = send_email(sample_input_data)

    assert result["acsOperationId"] == "acs-test-id-123"


@patch("function_app.EmailClient")
# this test checks that the outbound emails set a custom Message-ID header in the right format
def test_send_email_sets_custom_message_id_header(mock_email_client_cls, sample_input_data, monkeypatch):
    monkeypatch.setenv("ACS_CONNECTION_STRING", os.getenv("ACS_CONNECTION_STRING", "dummy"))
    monkeypatch.setenv("SENDER_ADDRESS", os.getenv("SENDER_ADDRESS", "dummy@example.com"))

    mock_email_client = MagicMock()
    mock_poller = MagicMock()
    mock_email_client.begin_send.return_value = mock_poller
    mock_poller.result.return_value = {"id": "acs-test-id-123"}
    mock_email_client_cls.from_connection_string.return_value = mock_email_client

    result = send_email(sample_input_data)

    args, _ = mock_email_client.begin_send.call_args
    message = args[0]

    assert "headers" in message
    assert "Message-ID" in message["headers"]
    assert "@carclinch.com" in message["headers"]["Message-ID"]
    # messageId in result should match what was set in headers
    assert result["messageId"] == message["headers"]["Message-ID"]


@patch("function_app.EmailClient")
# this test checks that first outbound email (no headers in inputData) does not have In-Reply-To header
# ensuring that the function correctly distinguishes between new messages and replies.
def test_send_email_no_in_reply_to_on_first_outbound(mock_email_client_cls, sample_input_data, monkeypatch):
    """first outbound email (no headers in inputData) should not set In-Reply-To"""
    monkeypatch.setenv("ACS_CONNECTION_STRING", os.getenv("ACS_CONNECTION_STRING", "dummy"))
    monkeypatch.setenv("SENDER_ADDRESS", os.getenv("SENDER_ADDRESS", "dummy@example.com"))

    mock_email_client = MagicMock()
    mock_poller = MagicMock()
    mock_email_client.begin_send.return_value = mock_poller
    mock_poller.result.return_value = {"id": "acs-test-id-123"}
    mock_email_client_cls.from_connection_string.return_value = mock_email_client

    result = send_email(sample_input_data)

    args, _ = mock_email_client.begin_send.call_args
    message = args[0]

    assert "In-Reply-To" not in message["headers"]


@patch("function_app.EmailClient")
# this test checks that if the inputData contains headers with a Message-ID (indicating an inbound reply)
# the send_email function correctly sets the In-Reply-To header in the outbound email, ensuring proper email threading
def test_send_email_sets_in_reply_to_on_inbound_reply(mock_email_client_cls, sample_input_data, monkeypatch):
    """if inputData has headers with Message-ID (inbound reply), In-Reply-To should be set"""
    monkeypatch.setenv("ACS_CONNECTION_STRING", os.getenv("ACS_CONNECTION_STRING", "dummy"))
    monkeypatch.setenv("SENDER_ADDRESS", os.getenv("SENDER_ADDRESS", "dummy@example.com"))

    mock_email_client = MagicMock()
    mock_poller = MagicMock()
    mock_email_client.begin_send.return_value = mock_poller
    mock_poller.result.return_value = {"id": "acs-test-id-456"}
    mock_email_client_cls.from_connection_string.return_value = mock_email_client

    sample_input_data["headers"] = {"Message-ID": "<previous-message-id@carclinch.com>"}
    result = send_email(sample_input_data)

    args, _ = mock_email_client.begin_send.call_args
    message = args[0]

    assert "In-Reply-To" in message["headers"]
    assert message["headers"]["In-Reply-To"] == "<previous-message-id@carclinch.com>"


@patch("function_app.EmailClient")
# this test checks that the send_email function correctly uses the lead's email address as the recipient
# in the outbound email
def test_send_email_uses_lead_email_as_recipient(mock_email_client_cls, sample_input_data, monkeypatch):
    """send_email should address the outbound email to the lead's email"""
    monkeypatch.setenv("ACS_CONNECTION_STRING", os.getenv("ACS_CONNECTION_STRING", "dummy"))
    monkeypatch.setenv("SENDER_ADDRESS", os.getenv("SENDER_ADDRESS", "dummy@example.com"))

    mock_email_client = MagicMock()
    mock_poller = MagicMock()
    mock_email_client.begin_send.return_value = mock_poller
    mock_poller.result.return_value = {"id": "acs-test-id-123"}
    mock_email_client_cls.from_connection_string.return_value = mock_email_client

    send_email(sample_input_data)

    args, _ = mock_email_client.begin_send.call_args
    message = args[0]

    assert message["recipients"]["to"][0]["address"] == sample_input_data["lead"]["email"]

# store_message tests

@patch("function_app.get_cosmos_container")
# this test verifies that the store_message function creates a Cosmos DB item with all the expected fields 
# based on the inputData, including id, conversationId, acsMessageId, source, timestamp, 
# and acsOperationId for tracking. acsInReplyTo is tested separately in the next two tests.
def test_store_message_creates_item_with_expected_fields(mock_get_container, sample_input_data):
    """store_message should create a Cosmos item with all expected fields"""
    mock_container = MagicMock()
    mock_get_container.return_value = mock_container

    store_input = {
        **sample_input_data,
        "acsOperationId": "acs-operation-id-123",
        "messageId": "<testmessageid@carclinch.com>",
        "emailBody": "<html>test body</html>"
    }

    store_message(store_input)

    mock_container.create_item.assert_called_once()
    args, _ = mock_container.create_item.call_args
    doc = args[0] if args else mock_container.create_item.call_args.kwargs["body"]

    assert doc["id"].startswith("msg_")
    assert doc["conversationId"] == "conv_test123"
    assert doc["acsMessageId"] == "<testmessageid@carclinch.com>"
    assert doc["source"] == 0
    assert "timestamp" in doc


@patch("function_app.get_cosmos_container")
# this test checks that when store_message is called with inputData that does not contain headers 
# (indicating a first outbound email), the acsInReplyTo field in the stored Cosmos DB item is 
# set to null, ensuring that new conversations are correctly identified.
def test_store_message_null_acs_in_reply_to_on_first_outbound(mock_get_container, sample_input_data):
    """first outbound (no headers in inputData) should store null acsInReplyTo"""
    mock_container = MagicMock()
    mock_get_container.return_value = mock_container

    store_input = {
        **sample_input_data,
        "acsOperationId": "acs-operation-id-123",
        "messageId": "<testmessageid@carclinch.com>",
        "emailBody": "<html>test body</html>"
    }

    store_message(store_input)

    args, _ = mock_container.create_item.call_args
    doc = args[0] if args else mock_container.create_item.call_args.kwargs["body"]

    assert doc["acsInReplyTo"] is None


@patch("function_app.get_cosmos_container")
# this test checks that when store_message is called with inputData that contains headers with a Message-ID
# (indicating an inbound reply), the acsInReplyTo field in the stored Cosmos DB item is set to the value 
# of that Message-ID, ensuring proper threading of email conversations in the database.
def test_store_message_sets_acs_in_reply_to_from_inbound_headers(mock_get_container, sample_input_data):
    """if inputData has headers with Message-ID, acsInReplyTo should be set"""
    mock_container = MagicMock()
    mock_get_container.return_value = mock_container

    store_input = {
        **sample_input_data,
        "acsOperationId": "acs-operation-id-456",
        "messageId": "<newmessageid@carclinch.com>",
        "emailBody": "<html>reply body</html>",
        "headers": {"Message-ID": "<previous-message-id@carclinch.com>"}
    }

    store_message(store_input)

    args, _ = mock_container.create_item.call_args
    doc = args[0] if args else mock_container.create_item.call_args.kwargs["body"]

    assert doc["acsInReplyTo"] == "<previous-message-id@carclinch.com>"


@patch("function_app.get_cosmos_container")
# this test checks that the store_message function generates a message document ID that starts with "msg_" 
# when creating a new item in Cosmos DB, ensuring that the ID format is consistent with expectations.
def test_store_message_returns_message_doc_id(mock_get_container, sample_input_data):
    """store_message should return the generated message doc id"""
    mock_container = MagicMock()
    mock_get_container.return_value = mock_container

    store_input = {
        **sample_input_data,
        "acsOperationId": "acs-operation-id-123",
        "messageId": "<testmessageid@carclinch.com>",
        "emailBody": "<html>test body</html>"
    }

    result = store_message(store_input)

    assert result.startswith("msg_")


@patch("function_app.get_cosmos_container")
# this test verifies that the store_message function correctly strips HTML tags from the 
# emailBody field before storing it in Cosmos DB, ensuring that the stored message body is plain text.
def test_store_message_body_is_stripped_html(mock_get_container, sample_input_data):
    """store_message should strip HTML tags from emailBody before storing"""
    mock_container = MagicMock()
    mock_get_container.return_value = mock_container

    store_input = {
        **sample_input_data,
        "acsOperationId": "acs-operation-id-123",
        "messageId": "<testmessageid@carclinch.com>",
        "emailBody": "<html><body><p>Hello Alice</p></body></html>"
    }

    store_message(store_input)

    args, _ = mock_container.create_item.call_args
    doc = args[0] if args else mock_container.create_item.call_args.kwargs["body"]

    assert "<html>" not in doc["body"]
    assert "Hello Alice" in doc["body"]