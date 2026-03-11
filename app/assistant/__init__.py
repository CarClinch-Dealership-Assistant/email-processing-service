import uuid
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from app.database.cosmos import CosmosDBClient
from app.email.factory import EmailFactory
from .gpt import GPTClient
from .template import build_email_template

system_prompt = """
# Prompt: Automotive Lead Engagement Generator

## 1. Role & Context
You are an **Automotive Digital Sales Specialist**. Your goal is to draft high-conversion, professional correspondence for potential car buyers. You must maintain a tone that is sophisticated, helpful, and brand-aligned.

## 2. Variable Dictionary (Data Injection)
The following placeholders (encapsulated in `{}`) represent dynamic data injected via API. **Do not modify the key names.** Ensure these are naturally integrated into the output:
* **Customer Identifiers:** `{customer_name}`
* **Vehicle Specifications:** `{vehicle_year}`, `{vehicle_make}`, `{vehicle_model}`, `{vehicle_status}`, `{vehicle_trim}`
* **Dealer Contact Matrix:** * Communication: `{dealership_email}`, `{dealership_phone}`
* Location: `{dealership_address}`, `{dealership_city}`, `{dealership_province}`, `{dealership_postal_code}`

## 3. Task Objective
Generate a **Follow-up Email** for a lead interested in a specific vehicle. The content should confirm the availability of the `{vehicle_year} {vehicle_make} {vehicle_model}` and highlight its specific trim (`{vehicle_trim}`).

## 4. Operational Constraints & Logic
* **Formatting:** Use standard professional email formatting (Subject Line, Salutation, Body, Call to Action, Signature Block).
"""


class Assistant(GPTClient):
    def __init__(self):
        GPTClient.__init__(self)

    def store_message(self, data: dict):
        message_doc = {
            "id": f"msg_{uuid.uuid4().hex[:10]}",
            "conversationId": data.get("conversationId", ""),
            "body": data.get("body", ""),
            "customer": data.get("customer", ""),
            "source": 0,
            "messageID": data.get("messageId", ""),  # this email's Message-ID, for inbound to match against
            "inReplyTo": data.get("Message-ID", ""),
            "role": data.get("role", ""),
            # inbound's Message-ID, null for first outbound
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        CosmosDBClient().save_message_to_default_container(message_doc)
        logging.info(f"Stored message: {message_doc['id']}")
        return message_doc["id"]

    def _get_default_message(self):
        message = []
        system = {
            "role": "system",
            "content": system_prompt
        }

        message.append(system)
        return message

    def _build_email_content(self, customer, content):
        lead = customer["lead"]
        vehicle = customer["vehicle"]
        dealership = customer["dealership"]
        address = dealership["address1"]
        if dealership["address2"] != "":
            address += ", " + dealership["address2"]
        data = {
            "customer_name": lead["fname"],
            "vehicle_year": vehicle["year"],
            "vehicle_make": vehicle["make"],
            "vehicle_model": vehicle["model"],
            "vehicle_status": "new" if vehicle["status"] == 0 else "used",
            "vehicle_trim": vehicle["trim"],
            "dealership_email": dealership["email"],
            "dealership_phone": dealership["phone"],
            "dealership_address": address,
            "dealership_city": dealership["city"],
            "dealership_province": dealership["province"],
            "dealership_postal_code": dealership["postal_code"],
        }
        return build_email_template(content.format(**data))

    def _strip_html(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        # remove style and script tags entirely
        for tag in soup(["style", "script"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())

    def contact(self, customer: dict):
        # generate content with AI
        user_prompt = """Please generate the email content.
Expected Output Structure:
```
Subject: Update regarding your inquiry: {vehicle_year} {vehicle_make} {vehicle_model}
Salutation: Dear {customer_name},
Body: Thank you for contacting us at our {dealership_city} location... [Incorporate vehicle details here] ...
Closing: Best regards,
The Sales Team at {dealership_city}
Contact Info Block:
{dealership_phone} | {dealership_email}
{dealership_address}
{dealership_city}, {dealership_province} {dealership_postal_code}
```"""
        prompts = self._get_default_message()
        prompts.append({"role": "user", "content": user_prompt})
        resp = self.chat(prompts)
        # build email content
        subject, body = self._process_response(resp["choices"][0]["message"]["content"])
        email_content = self._build_email_content(customer, body)
        # call send
        to = customer["lead"]["email"]
        EmailFactory.get_provider("gmail").send(to, subject, email_content)
        # store to db
        msg = {
            "customer": to,
            "conversationId": "",
            "body": self._strip_html(email_content),
            "messageId": "",
            "Message-ID": "",
            "role": "assistant"
        }
        self.store_message(msg)

    def _process_response(self, text):
        parts = text.split('\n', 1)
        subject = parts[0]
        if subject.startswith("Subject:"):
            subject = parts[0].split(":", 1)[1].strip()
        body = parts[1] if len(parts) > 1 else ""
        body = body.replace("\r\n", "<br />").replace("\n", "<br />")
        return (subject, body)

    def _get_email_history(self, customer: str):
        query = "SELECT * FROM c WHERE c.customer = @address"
        params = [
            {"name": "@address", "value": customer}
        ]

        items = CosmosDBClient().query_items_from_default_container(query, params)
        messages = []

        for item in items:
            body = "Customer Reply: " + item["body"] if item["role"] == "user" else item["body"]
            messages.append({
                "role": item["role"], "content": body,
            })

        return messages

    def _save_received_messages(self, received_email):
        msg = {
            "customer": received_email["sender"],
            "conversationId": "",
            "body": self._strip_html(received_email["body"]),
            "messageId": "",
            "Message-ID": received_email["message_id"],
            "role": "user"
        }
        self.store_message(msg)

    def reply(self, received_email):
        prompts = self._get_default_message()
        # fetch history
        history = self._get_email_history(received_email["sender"])
        prompts.extend(history)
        user_prompt = "Please generate the email content for replying. no variables could be replaced."
        prompts.append({"role": "user", "content": user_prompt})
        # generate content with AI
        resp = self.chat(prompts)
        # build email content

        subject, body = self._process_response(resp["choices"][0]["message"]["content"])
        email_content = build_email_template(body)
        # call reply
        EmailFactory.get_provider("gmail").reply(received_email["sender"], received_email["message_id"], received_email["subject"], email_content)
        # store to db
        msg = {
            "customer": received_email["sender"],
            "conversationId": "",
            "body": email_content,
            "messageId": "",
            "Message-ID": received_email["message_id"],
            "role": "assistant"
        }
        self.store_message(msg)
