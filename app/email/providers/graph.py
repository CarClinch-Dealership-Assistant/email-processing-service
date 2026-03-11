from typing import List
from app.email.protocol import StandardEmail
import msal
import requests

class GraphProvider:
    def send(self, to: str, subject: str, body: str):
        print(f"Executing Graph.send to {to}")
        return True

    def fetch_latest(self) -> List[StandardEmail]:
        print("Polling IMAP server...")
        return [StandardEmail("1", "test@me.com", "Hello", "Body", "smtp")]

    def fetch_conversation(self, email_address: str) -> List[StandardEmail]:
        print(f"Querying for conversations with {email_address}")
        return [StandardEmail("1", "test@me.com", "Hello", "Body", "smtp")]

