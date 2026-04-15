# tests/unit/test_email_factory.py
import pytest
from unittest.mock import patch
from app.email.factory import EmailFactory

def test_get_gmail_provider():
    with patch.dict("os.environ", {"GMAIL_USER": "test@gmail.com", "GMAIL_APP_PASSWORD": "x"}):
        provider = EmailFactory.get_provider("gmail")
        from app.email.providers.smtp import GmailProvider
        assert isinstance(provider, GmailProvider)

def test_unknown_provider_raises():
    with pytest.raises((KeyError, TypeError)):
        EmailFactory.get_provider("unknown_provider")

def test_provider_lookup_is_case_insensitive():
    with patch.dict("os.environ", {"GMAIL_USER": "test@gmail.com", "GMAIL_APP_PASSWORD": "x"}):
        p1 = EmailFactory.get_provider("gmail")
        p2 = EmailFactory.get_provider("GMAIL")
        assert type(p1) == type(p2)