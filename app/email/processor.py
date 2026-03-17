from msgraph.generated.models.todo import Todo

from app.database.models import EmailDB
from .protocol import StandardEmail


def unified_email_processor(raw_data: dict, source: str):
    email_obj = StandardEmail(
        id=raw_data.get("id"),
        sender=raw_data.get("from"),
        subject=raw_data.get("subject"),
        body=raw_data.get("content"),
        source=source,
        in_reply_to=raw_data.get("In-Reply-To", ""),
        message_id=raw_data.get("Message-ID", ""),
    )
    EmailDB.save(email_obj)
    return email_obj
