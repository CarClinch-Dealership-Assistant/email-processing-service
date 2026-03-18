from typing import List
from app.email.protocol import StandardEmail

class EmailDB:
    @staticmethod
    def save(email: StandardEmail):
        print(f"Saving email from {email.source} to DB: {email.subject}")

    @staticmethod
    def query_by_source(source: str) -> List[StandardEmail]:
        print(f"Querying DB for {source} emails")
        return []