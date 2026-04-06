import pytest
from unittest.mock import MagicMock, patch
from app.email.protocol import StandardEmail
import app.assistant.gpt
import app.assistant
from app.assistant import Assistant

def _patched_init(self):
    app.assistant.gpt.GPTClient.__init__(self)

Assistant.__init__ = _patched_init

@property
def lazy_db(self):
    if not hasattr(self, "_lazy_db"):
        self._lazy_db = app.assistant.CosmosDBClient()
    return self._lazy_db

Assistant.db = lazy_db

@pytest.fixture(autouse=True)
def mock_cosmos():
    with patch("app.database.cosmos.CosmosDBClient._init_client"):
        yield

@pytest.fixture
def sample_customer():
    return {
        "conversationId": "conv_001",
        "lead": {
            "id": "lead_001",
            "fname": "Alice",
            "email": "alice@example.com",
            "notes": "Interested in fuel economy for city commuting.",
        },
        "vehicle": {
            "id": "veh_001",
            "year": 2021,
            "make": "Honda",
            "model": "Civic",
            "status": 1,           # used
            "trim": "LX",
            "mileage": 45000,
            "transmission": "Automatic",
            "comments": "Clean carfax, one owner.",
        },
        "dealership": {
            "id": "dealer_001",
            "name": "City Honda",
            "email": "sales@cityhonda.com",
            "phone": "613-555-0100",
            "address1": "123 Main St",
            "address2": None,
            "city": "Ottawa",
            "province": "ON",
            "postal_code": "K1A 0A1",
        },
    }

@pytest.fixture
def sample_received_email():
    return {
        "id": "imap_42",
        "sender": "alice@example.com",
        "subject": "Re: 2021 Honda Civic",
        "body": "Can I come in Saturday for a test drive?",
        "message_id": "<reply_001@mail.com>",
        "in_reply_to": "<original_001@mail.com>",
        "source": "smtp",
    }

@pytest.fixture
def make_standard_email():
    def _make(**overrides):
        defaults = dict(
            id="1",
            message_id="<msg@mail.com>",
            sender="alice@example.com",
            subject="Test Subject",
            body="Hello",
            source="smtp",
            in_reply_to="",
        )
        return StandardEmail(**{**defaults, **overrides})
    return _make

def make_mock_resp(text="Subject line\nBody of the email.", resp_id="resp_abc123"):
    resp = MagicMock()
    resp.output_text = text
    resp.id = resp_id
    return resp