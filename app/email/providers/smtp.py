import os
import logging
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.utils import parseaddr
from email.header import decode_header
from typing import List
from app.email.protocol import StandardEmail

class SmtpProvider:
    def __init__(self):
        self.smtp_host = ""
        self.smtp_port = None
        self.imap_host = None
        self.user = None
        self.password = None

    def send(self, to: str, subject: str, body: str, msg_id: str = None) -> bool:
        """Sending with SMTP"""
        try:
            msg = MIMEText(body,"html", "utf-8")
            msg["Subject"] = subject
            msg["From"] = self.user
            msg["To"] = to
            if msg_id:
                msg["Message-ID"] = msg_id

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.user, self.password)
                ret = server.send_message(msg)
                logging.info(f"SMTP Send successfully: {ret}")
            return True
        except Exception as e:
            logging.error(f"SMTP Send Error: {e}")
            return False

    """Use IMAP to poll the latest unread emails"""
    def fetch_latest(self) -> List[StandardEmail]:
        standard_emails = []
        mail = imaplib.IMAP4_SSL(self.imap_host)
        try:
            mail.login(self.user, self.password)
            mail.select("inbox")
            # Search all unread (UNSEEN) emails
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                return []

            # Get the mailing list ID
            mail_ids = messages[0].split()

            latest_ids = reversed(mail_ids[-5:])

            for m_id in latest_ids:
                # Get the specific content of the email
                res, msg_data = mail.fetch(m_id, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        # Parse the mail byte stream
                        raw_email = email.message_from_bytes(response_part[1])

                        # Parse the subject
                        msg_id = raw_email.get("Message-ID", "")
                        subject = raw_email["Subject"]

                        # Parse the sender
                        sender = raw_email.get("From")

                        # Parse the text (simple processing)
                        body = self.parse_mail_body(raw_email)

                        in_reply_to = raw_email.get("In-Reply-To", "")
                        
                        # Convert to a general model
                        standard_emails.append(StandardEmail(
                            id=m_id.decode(),
                            message_id=str(msg_id),
                            sender=sender,
                            subject=subject,
                            body=body,
                            source="smtp",
                            in_reply_to=in_reply_to
                        ))


        except Exception as e:
            print(f"IMAP Fetch Error: {e}")
        finally:
            mail.close()
            mail.logout()

        return standard_emails

    def parse_mail_body(self, raw_email):
        body = ""
        if raw_email.is_multipart():
            for part in raw_email.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if content_type == "text/plain" and "attachment" not in content_disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                    break
        else:
            payload = raw_email.get_payload(decode=True)
            if payload:
                charset = raw_email.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")

        return body

    def fetch_conversation(self, email_address: str) -> List[StandardEmail]:
        conversation = []
        try:
            mail = imaplib.IMAP4_SSL(self.imap_host)
            mail.login(self.user, self.password)
            mail.select("inbox")


            search_criterion = f'(OR FROM "{email_address}" TO "{email_address}")'
            status, messages = mail.search(None, search_criterion)

            if status == "OK":
                for m_id in messages[0].split():
                    res, msg_data = mail.fetch(m_id, "(RFC822)")
                    standard_mail = self._parse_raw_mail(m_id, msg_data)
                    if standard_mail:
                        conversation.append(standard_mail)

            mail.logout()
        except Exception as e:
            print(f"IMAP Conversation Fetch Error: {e}")

        return conversation

    def _parse_raw_mail(self, m_id, msg_data) -> StandardEmail:
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                raw_email = email.message_from_bytes(response_part[1])
                subject, encoding = decode_header(raw_email["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8")

                sender = raw_email.get("From")
                msg_id = raw_email.get("Message-ID")
                in_reply_to = raw_email.get("In-Reply-To", "")


                return StandardEmail(
                    id=m_id.decode(),
                    message_id=msg_id,
                    sender=sender,
                    subject=subject,
                    body=self.parse_mail_body(raw_email),
                    source="smtp",
                    in_reply_to=in_reply_to
                )
        return None

    def _parse_sender(self, sender: str) -> str:
        name, email = parseaddr(sender)
        return email

    def search_emails(self, sender_email: str = None, subject_keyword: str = None) -> List[StandardEmail]:
        results = []
        try:
            mail = imaplib.IMAP4_SSL(self.imap_host)
            mail.login(self.user, self.password)
            mail.select("inbox")

            # eg: (FROM "user@test.com" SUBJECT "Invoice")
            search_criteria = []
            if sender_email:
                search_criteria.append(f'FROM "{sender_email}"')
            if subject_keyword:
                search_criteria.append(f'SUBJECT "{subject_keyword}"')

            if not search_criteria:
                return []

            # eg：'FROM "a@b.com" SUBJECT "hello"'
            search_str = " ".join(search_criteria)

            status, messages = mail.search(None, search_str)

            if status == "OK":
                for m_id in messages[0].split():
                    res, msg_data = mail.fetch(m_id, "(RFC822)")
                    standard_mail = self._parse_raw_mail(m_id, msg_data)
                    if standard_mail:
                        results.append(standard_mail)

            mail.logout()
        except Exception as e:
            print(f"IMAP Search Error: {e}")

        return results

    def reply(self, sender: str, message_id: str, subject: str, body: str, msg_id: str = None) -> bool:
        """
        :param sender: email receiver
        :param message_id: original Message-ID
        :param subject: original subject
        :param body: The content of the reply
        """
        try:
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            msg = MIMEText(body,"html", "utf-8")
            msg["Subject"] = subject
            msg["From"] = self.user
            msg["To"] = sender
            if msg_id:
                msg["Message-ID"] = msg_id

            if message_id:
                if not message_id.startswith("<"):
                    message_id = f"<{message_id}>"

                msg["In-Reply-To"] = message_id
                msg["References"] = message_id

            # 3. 发送邮件
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(msg)

            print(f"Reply sent to {sender} for message {message_id}")
            return True
        except Exception as e:
            print(f"SMTP Reply Error: {e}")
            return False


class GmailProvider(SmtpProvider):
    def __init__(self):
        super().__init__()
        self.smtp_host = "smtp.gmail.com"
        self.imap_host = "imap.gmail.com"
        self.smtp_port = 587

        self.user = os.getenv("GMAIL_USER")
        self.password = os.getenv("GMAIL_APP_PASSWORD")
        self._validate_gmail(self.user)

    def _validate_gmail(self, gmail_address: str):
        if gmail_address is None:
            raise ValueError("Gmail address is missing! Check your environment variables.")
        if not gmail_address.endswith("@gmail.com"):
            raise ValueError(f"Invalid gmail address: {gmail_address}")

class OutlookProvider(SmtpProvider):
    def __init__(self):
        super().__init__()
        self.smtp_host = "smtp.outlook.com"
        self.imap_host = "outlook.office365.com"
        self.user = "xxx@hotmail.com"
        self.password = ""