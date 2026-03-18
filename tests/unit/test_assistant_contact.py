import pytest
from unittest.mock import patch, MagicMock, call
from app.assistant import Assistant
from conftest import make_mock_resp

@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        return Assistant()

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_contact_happy_path(mock_chat, mock_factory, mock_db, assistant, sample_customer):
    mock_chat.return_value = make_mock_resp("Re: 2021 Honda Civic\nHi Alice, thanks for reaching out!")
    mock_factory.get_provider.return_value.send.return_value = True

    assistant.contact(sample_customer)

    mock_factory.get_provider.assert_called_once_with("gmail")
    mock_factory.get_provider.return_value.send.assert_called_once()
    mock_db.return_value.save_message_to_default_container.assert_called_once()

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_contact_escalation_skips_send_and_store(mock_chat, mock_factory, mock_db, assistant, sample_customer):
    mock_chat.return_value = make_mock_resp('{"escalate": true, "reason": "pricing_inquiry"}')

    assistant.contact(sample_customer)

    mock_factory.get_provider.assert_not_called()
    mock_db.return_value.save_message_to_default_container.assert_not_called()

@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch.object(Assistant, "chat")
def test_contact_malformed_json_proceeds_normally(mock_chat, mock_factory, mock_db, assistant, sample_customer):
    """A response that looks like JSON but isn't an escalation should send normally."""
    mock_chat.return_value = make_mock_resp('{"some_key": "value"}\nHi Alice!')
    mock_factory.get_provider.return_value.send.return_value = True

    assistant.contact(sample_customer)

    # escalate key absent → should still send
    mock_factory.get_provider.return_value.send.assert_called_once()