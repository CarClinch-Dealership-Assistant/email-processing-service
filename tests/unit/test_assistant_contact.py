import pytest
from unittest.mock import patch, MagicMock, call
from app.assistant import Assistant
from conftest import make_mock_resp


@pytest.fixture
def assistant():
    with patch("app.assistant.gpt.OpenAI"):
        return Assistant()


def _routine_analysis():
    return {
        "intentCategory": "appointment", "intentAction": "request",
        "sentimentLabel": "positive", "tone": "positive",
        "urgency": "low", "intentConfidence": "high",
        "escalate": False, "summary": "Wants a test drive.",
    }


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_contact_happy_path(mock_chat, mock_analysis_cls, mock_factory, mock_db, assistant, sample_customer):
    mock_analysis_cls.return_value.analyze.return_value = _routine_analysis()
    mock_chat.return_value = make_mock_resp("Re: 2021 Honda Civic\nHi Alice, thanks for reaching out!")
    mock_factory.get_provider.return_value.send.return_value = True

    assistant.contact(sample_customer)

    mock_factory.get_provider.assert_called_once_with("gmail")
    mock_factory.get_provider.return_value.send.assert_called_once()
    # one store for user form submission (notes non-empty) + one for outgoing assistant message
    assert mock_db.return_value.save_message.call_count == 2


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_contact_escalation_skips_send_and_store(mock_chat, mock_analysis_cls, mock_factory, mock_db, assistant, sample_customer):
    # escalation triggered by analysis pre-check, before chat is ever called
    mock_analysis_cls.return_value.analyze.return_value = {
        **_routine_analysis(), "escalate": True, "intentCategory": "pricing",
    }
    mock_db.return_value.query_items.return_value = []
    mock_db.return_value.get_item_by_id.return_value = {"id": "conv_001", "status": 1}

    assistant.contact(sample_customer)

    mock_chat.assert_not_called()
    mock_factory.get_provider.assert_not_called()
    # _store_message for the user form submission fires before analysis, so 1 call is expected
    assert mock_db.return_value.save_message.call_count == 1


@patch("app.assistant.CosmosDBClient")
@patch("app.assistant.EmailFactory")
@patch("app.assistant.Analysis")
@patch.object(Assistant, "chat")
def test_contact_malformed_json_proceeds_normally(mock_chat, mock_analysis_cls, mock_factory, mock_db, assistant, sample_customer):
    """A chat response that looks like JSON but has no escalate key should send normally."""
    mock_analysis_cls.return_value.analyze.return_value = _routine_analysis()
    mock_chat.return_value = make_mock_resp('{"some_key": "value"}\nHi Alice!')
    mock_factory.get_provider.return_value.send.return_value = True

    assistant.contact(sample_customer)

    mock_factory.get_provider.return_value.send.assert_called_once()