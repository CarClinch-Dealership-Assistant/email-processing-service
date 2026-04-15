# tests/unit/test_assistant_contact.py
import pytest
from unittest.mock import MagicMock, patch
from app.assistant.assistant import Assistant
from conftest import make_mock_resp

@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        a = Assistant()
        a.dbcli = MagicMock()
        return a

@patch("app.assistant.assistant.EmailFactory")
@patch("app.assistant.escalation.Analysis")
@patch.object(Assistant, "chat")
def test_contact_happy_path(mock_chat, mock_analysis_cls, mock_factory, assistant, sample_customer):
    mock_analysis_cls.return_value.analyze.return_value = {
        "intentCategory": "vehicle_info",
        "intentAction": "inquire",
        "escalate": False,
        "summary": "Asking about fuel economy."
    }
    mock_chat.return_value = make_mock_resp("Subject Line\nThis is a response.")
    mock_factory.get_provider.return_value.send.return_value = True

    assistant.contact(sample_customer)

    mock_chat.assert_called_once()
    mock_factory.get_provider.return_value.send.assert_called_once()
    assert assistant.dbcli.message_container.save_message.call_count >= 1