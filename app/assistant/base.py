import uuid
import logging
import re
from datetime import datetime, timezone
from app.database.cosmos import CosmosDBClient
from email.utils import parseaddr
from bs4 import BeautifulSoup
from app.assistant.template import build_email_template
from app.assistant.gpt import GPTClient

class BaseAssistant(GPTClient):
    def __init__(self):
        super().__init__()
        self.db = CosmosDBClient()

    # helper function to builds message document and stores it in cosmosdb
    def store_message(
        self, id_context, response_id, message_id, role, raw_output, subject
    ):
        doc_id = f"msg_{uuid.uuid4().hex[:10]}"
        message_doc = {
            "id": doc_id,
            "conversationId": id_context.get("conversationId", ""),
            "leadId": id_context.get("leadId", ""),
            "vehicleId": id_context.get("vehicleId", ""),
            "dealerId": id_context.get("dealerId", ""),
            "responseId": response_id,
            "emailMessageId": message_id,
            "role": role,
            "body": raw_output,
            "subject": subject,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.db.save_message(message_doc)
        logging.info(f"Stored message: {doc_id}")
        return doc_id

    # helper function to resolve id (ex. vehicleId, dealerId, etc.) id_context for a reply when in_reply_to is present
    # but there is no chain match based on responseId
    def resolve_context_from_sender(self, sender: str):
        _, sender_email = parseaddr(sender)
        leads = self.db.query_items(
            "leads",
            "SELECT * FROM c WHERE c.email = @email",
            [{"name": "@email", "value": sender_email.lower()}],
        )
        if not leads:
            logging.warning(f"No lead found for sender: {sender_email}")
            return None
        lead = leads[0]
        conversations = self.db.query_items(
            "conversations",
            "SELECT * FROM c WHERE c.leadId = @leadId AND c.status = 1 ORDER BY c.timestamp DESC OFFSET 0 LIMIT 1",
            [{"name": "@leadId", "value": lead["id"]}],
        )
        if not conversations:
            logging.warning(f"No active conversation for lead: {lead['id']}")
            return None
        conversation = conversations[0]
        return {
            "conversationId": conversation["id"],
            "leadId": lead["id"],
            "vehicleId": conversation["vehicleId"],
            "dealerId": conversation["dealerId"],
        }

    def set_conversation_status(self, conversation_id: str, status: int):
        conversation = self.db.get_item_by_id(conversation_id, "conversations")
        if conversation:
            conversation["status"] = status
            self.db.update_item_in_container("conversations", conversation)
            logging.info(f"Updated conversation {conversation_id} to status {status}")
        else:
            logging.error(f"Conversation not found for ID: {conversation_id}")

    # helper to pull the data back out of Cosmos to hydrate the prompt context for the follow-up sequence
    # since it runs independently of the reply chain and won't have the previous responseId to pull id_context from
    def hydrate_customer_context(self, id_context: dict) -> dict:
        lead_id = id_context["leadId"]
        vehicle_id = id_context["vehicleId"]
        dealer_id = id_context["dealerId"]

        lead = self.db.query_items("leads", "SELECT * FROM c WHERE c.id=@id", [{"name": "@id", "value": lead_id}])
        vehicle = self.db.query_items("vehicles", "SELECT * FROM c WHERE c.id=@id AND c.dealerId=@did",
                                      [{"name": "@id", "value": vehicle_id}, {"name": "@did", "value": dealer_id}])
        dealer = self.db.query_items("dealerships", "SELECT * FROM c WHERE c.id=@id",
                                     [{"name": "@id", "value": dealer_id}])

        return {
            "conversationId": id_context["conversationId"],
            "lead": lead[0] if lead else {},
            "vehicle": vehicle[0] if vehicle else {},
            "dealership": dealer[0] if dealer else {}
        }

    # ==========================================
    # TEXT PROCESSING & DATA FORMATTING
    # ==========================================

    # helper function to extract and format all necessary data for prompt
    def get_formatting_data(self, customer):
        lead = customer["lead"]
        vehicle = customer["vehicle"]
        dealership = customer["dealership"]

        notes = lead.get("notes", "")
        notes_text = (
            notes
            if isinstance(notes, str)
            else " | ".join([n["text"] for n in notes if n.get("text")])
        )

        address = dealership.get("address1", "")
        if dealership.get("address2"):
            address += ", " + dealership["address2"]

        data = {
            "conversationId": customer["conversationId"],
            "customer_name": lead["fname"],
            "customer_email": lead["email"],
            "vehicle_year": vehicle["year"],
            "vehicle_make": vehicle["make"],
            "vehicle_model": vehicle["model"],
            "vehicle_status": "new" if vehicle["status"] == 0 else "used",
            "vehicle_trim": vehicle["trim"],
            "vehicle_mileage": vehicle["mileage"],
            "vehicle_transmission": vehicle["transmission"],
            "vehicle_comments": vehicle["comments"],
            "lead_notes": notes_text,
            "dealership_name": dealership["name"],
            "dealership_email": dealership["email"],
            "dealership_phone": dealership["phone"],
            "dealership_address": address,
            "dealership_city": dealership["city"],
            "dealership_province": dealership["province"],
            "dealership_postal_code": dealership["postal_code"],
        }
        return data

    # helper function to remove html tags and extract text content from the email body for analysis and response generation
    def strip_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        # remove style and script tags entirely
        for tag in soup(["style", "script"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())

    # helper function to remove quoted previous replies from the message body using common email reply patterns
    def strip_quoted_reply(self, body: str) -> str:
        cleaned = re.split(r'On .+?wrote:', body, flags=re.DOTALL, maxsplit=1)[0]
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith(">")]
        result = "\n".join(lines)
        result = re.split(r'-{5,}', result, maxsplit=1)[0]
        result = re.split(r'\n--\s*\n', result, maxsplit=1)[0]
        return result.strip()

    # helper function to process the raw text output from the model into subject and body components
    def process_response(self, text):
        parts = text.split("\n", 1)
        subject = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        body = body.replace("\r\n", "<br />").replace("\n", "<br />")
        return (subject, body)

    def fmt_time(self, h: int) -> str:
        if h < 12:
            return f"{h}:00 AM"
        elif h == 12:
            return "12:00 PM"
        else:
            return f"{h - 12}:00 PM"

    # helper function to build email content using the subject and body returned from the model and the formatting data
    def build_email_content(self, customer, subject, content):
        data = self.get_formatting_data(customer)
        resolved_subject = subject.format(**data) if "{" in subject else subject
        return resolved_subject, build_email_template(content)

    def generate_parsed_ai_response(self, prompts: list, previous_response_id: str = None) -> tuple[
        str, str, str, str, str]:
        """Calls the LLM, fixes table HTML, parses subject/body, and returns all needed strings."""
        resp = self.chat(prompts, previous_response_id=previous_response_id)

        # Clean HTML tables
        raw_output = re.sub(r'\s+<table', '<br><br><table', resp.output_text.strip())

        # Parse Subject and Body
        subject, body = self.process_response(raw_output)
        raw_body = raw_output.split("\n", 1)[1] if "\n" in raw_output else ""

        return resp.id, raw_output, subject, body, raw_body
