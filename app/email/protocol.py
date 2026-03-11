from typing import Protocol, List, Optional, runtime_checkable
from dataclasses import dataclass

@dataclass
class StandardEmail:
    id: str
    message_id: str
    sender: str
    subject: str
    body: str
    source: str  # 'smtp', 'acs', 'graph'



@runtime_checkable
class EmailProvider(Protocol):
    def send(self, to: str, subject: str, body: str) -> bool: ...
    def fetch_latest(self) -> List[StandardEmail]: ...
    def fetch_conversation(self, email_address: str) -> List[StandardEmail]: ...
    def search_emails(self, sender_email: str = None, subject_keyword: str = None) -> List[StandardEmail]: ...
    def reply(self, sender: str, message_id: str, subject: str, body: str) -> bool: ...

