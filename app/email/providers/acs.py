from typing import List
from ..protocol import StandardEmail
from app.database.models import EmailDB

class AcsProvider:
    def send(self, to: str, subject: str, body: str):
        print(f"Calling Azure ACS API to {to}")
        return True

    def fetch_latest(self) -> List[StandardEmail]:
        return EmailDB.query_by_source("acs")

    def fetch_conversation(self, email_address: str) -> List[StandardEmail]:
        print(f"Querying database for conversations with {email_address}")
        return EmailDB.query_by_address(email_address)

    def search_emails(self, sender_email: str = None, subject_keyword: str = None) -> List[StandardEmail]:
        """ACS 模式：通过数据库进行 SQL 过滤查询"""
        # 逻辑：SELECT * FROM emails WHERE sender = sender_email AND subject LIKE %subject_keyword%
        print(f"Searching DB for sender: {sender_email} and subject keyword: {subject_keyword}")

        return EmailDB.complex_query(
            sender=sender_email,
            keyword=subject_keyword,
            source="acs"
        )