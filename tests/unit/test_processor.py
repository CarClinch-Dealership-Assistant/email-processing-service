import pytest
from unittest.mock import patch
from app.email.processor import unified_email_processor
from app.email.protocol import StandardEmail

RAW = {
    "id": "abc123",
    "from": "sender@example.com",
    "subject": "Test Subject",
    "content": "Hello world",
    "In-Reply-To": "<prev@mail.com>",
    "Message-ID": "<msg@mail.com>",
}

@patch("app.email.processor.EmailDB.save")
def test_fields_mapped_correctly(mock_save):
    result = unified_email_processor(RAW, source="graph")
    assert result.sender == "sender@example.com"
    assert result.body == "Hello world"
    assert result.source == "graph"
    assert result.in_reply_to == "<prev@mail.com>"

@patch("app.email.processor.EmailDB.save")
def test_optional_fields_default_to_empty_string(mock_save):
    result = unified_email_processor({"id": "1"}, source="smtp")
    assert result.in_reply_to == ""
    assert result.message_id == ""

@patch("app.email.processor.EmailDB.save")
def test_save_called_with_standard_email(mock_save):
    unified_email_processor(RAW, source="graph")
    assert mock_save.call_count == 1
    assert isinstance(mock_save.call_args[0][0], StandardEmail)

@patch("app.email.processor.EmailDB.save", side_effect=Exception("DB down"))
def test_db_failure_propagates(mock_save):
    with pytest.raises(Exception, match="DB down"):
        unified_email_processor(RAW, source="graph")