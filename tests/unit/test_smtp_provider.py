import pytest
from unittest.mock import patch, MagicMock, call
from app.email.providers.smtp import SmtpProvider, GmailProvider

@pytest.fixture
def provider():
    p = SmtpProvider()
    p.smtp_host = "smtp.test.com"
    p.smtp_port = 587
    p.user = "test@test.com"
    p.password = "secret"
    return p



@patch("app.email.providers.smtp.smtplib.SMTP")
def test_send_returns_true_on_success(mock_smtp, provider):
    assert provider.send("to@example.com", "Subject", "<p>Body</p>") is True

@patch("app.email.providers.smtp.smtplib.SMTP", side_effect=Exception("Connection refused"))
def test_send_returns_false_on_failure(mock_smtp, provider):
    assert provider.send("to@example.com", "Subject", "<p>Body</p>") is False

@patch("app.email.providers.smtp.smtplib.SMTP")
def test_send_sets_message_id_header(mock_smtp, provider):
    ctx = mock_smtp.return_value.__enter__.return_value
    provider.send("to@example.com", "Subj", "Body", msg_id="<custom@id>")
    sent_msg = ctx.send_message.call_args[0][0]
    assert sent_msg["Message-ID"] == "<custom@id>"



@patch("app.email.providers.smtp.smtplib.SMTP")
def test_reply_prefixes_re_to_subject(mock_smtp, provider):
    ctx = mock_smtp.return_value.__enter__.return_value
    provider.reply("to@example.com", "<orig@id>", "Civic Inquiry", "Body")
    sent_msg = ctx.send_message.call_args[0][0]
    assert sent_msg["Subject"].startswith("Re:")

@patch("app.email.providers.smtp.smtplib.SMTP")
def test_reply_does_not_double_prefix_re(mock_smtp, provider):
    ctx = mock_smtp.return_value.__enter__.return_value
    provider.reply("to@example.com", "<orig@id>", "Re: Civic Inquiry", "Body")
    sent_msg = ctx.send_message.call_args[0][0]
    assert sent_msg["Subject"].lower().count("re:") == 1

@patch("app.email.providers.smtp.smtplib.SMTP")
def test_reply_sets_in_reply_to_header(mock_smtp, provider):
    ctx = mock_smtp.return_value.__enter__.return_value
    provider.reply("to@example.com", "<orig@id>", "Subj", "Body")
    sent_msg = ctx.send_message.call_args[0][0]
    assert sent_msg["In-Reply-To"] == "<orig@id>"



def test_gmail_raises_on_missing_env():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="missing"):
            GmailProvider()

def test_gmail_raises_on_non_gmail_address():
    with patch.dict("os.environ", {"GMAIL_USER": "user@outlook.com", "GMAIL_APP_PASSWORD": "x"}):
        with pytest.raises(ValueError, match="Invalid gmail"):
            GmailProvider()



def test_parse_mail_body_plain_text(provider):
    import email
    raw = email.message_from_string(
        "Content-Type: text/plain\r\n\r\nHello world"
    )
    assert provider.parse_mail_body(raw) == "Hello world"