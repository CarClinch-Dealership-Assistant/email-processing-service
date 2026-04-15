import uuid
import socket
import logging
import re
from datetime import datetime, timezone
from app.database.cosmos import CosmosDBClient
from email.utils import parseaddr
from bs4 import BeautifulSoup
from app.assistant.template import build_email_template, build_date_table, build_time_table
from app.assistant.gpt import GPTClient

class BaseAssistant(GPTClient):
    """
    BaseAssistant provides common utilities for handling email conversations, including:
    - Storing messages in the database
    - Resolving context from email senders
    - Hydrating customer context for prompt generation
    - Processing and formatting LLM responses into email content
    """
    def __init__(self):
        super().__init__()
        self.dbcli = CosmosDBClient()

    def make_msgid(self, conversation_id: str) -> str:
        """
        Generates a unique Message-ID for email threading, incorporating the conversation ID and a random hex string.
        Args:
            conversation_id (str): The ID of the conversation to include in the Message-ID for threading.
            
        Returns:
            str: A unique Message-ID in the format <randomhex.conversationId@domain.com>
        """
        # generates: <randomhex.convID@domain.com>
        domain = socket.getfqdn()
        random_hex = uuid.uuid4().hex[:15]
        return f"<{random_hex}.{conversation_id}@{domain}>"
    
    def store_message(
        self, id_context, response_id, message_id, role, raw_output, subject
    ):
        """
        Persists a message (user, assistant, or system) into the Cosmos DB message container.

        Args:
            id_context (dict): Requires 'conversationId', 'leadId', 'vehicleId', and 'dealerId'.
            response_id (str): The OpenAI response ID for conversation chaining (nullable).
            message_id (str): The email Message-ID for thread tracking.
            role (str): 'user', 'assistant'.
            raw_output (str): The message body.
            subject (str): The message subject line.

        Returns:
            str: The generated unique document ID for the stored message.
        """
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
        self.dbcli.message_container.save_message(message_doc)
        logging.info(f"Stored message: {doc_id}")
        return doc_id

    def resolve_context_from_sender(self, sender: str):
        """
        A fallback mechanism to resolve conversation context when email thread headers are broken.
        
        It looks up the sender's email in the leads container and attempts to find an 
        active conversation associated with that lead.

        Args:
            sender (str): The raw sender string (e.g., "John Doe <john@example.com>").

        Returns:
            dict | None: The resolved id_context dictionary, or None if no active match is found.
        """
        _, sender_email = parseaddr(sender)
        leads = self.dbcli.leads_container.query_items_with_email(sender_email.lower())
        if not leads:
            logging.warning(f"No lead found for sender: {sender_email}")
            return None
        lead = leads[0]
        conversations = self.dbcli.conversation_container.query_items_with_lead(lead["id"])
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

    def set_conversation_status(self, conversation_id: str, lead_id: str, status: int):
        """
        Updates the status of a conversation.

        Args:
            conversation_id (str): The ID of the conversation to update.
            lead_id (str): The ID of the lead associated with the conversation.
            status (int): The new status for the conversation.

        Returns:
            None
        """
        conversation = self.dbcli.conversation_container.get_conversation_by_lead(conversation_id, lead_id)
        
        if conversation:
            conversation["status"] = status
            self.dbcli.conversation_container.update_item(conversation)
            logging.info(f"Updated conversation {conversation_id} to status {status}")
        else:
            logging.error(f"Conversation not found for ID: {conversation_id}")
    
    def hydrate_customer_context(self, id_context: dict) -> dict:
        """
        Retrieves full entity records from Cosmos DB to populate prompt contexts.
        
        This is primarily utilized by independent processes like the follow-up timer 
        that only possess ID strings and need the complete data payload.

        Args:
            id_context (dict): Contains leadId, vehicleId, dealerId, and conversationId.

        Returns:
            dict: The hydrated context containing:
                - conversationId (str)
                - lead (dict)
                - vehicle (dict)
                - dealership (dict)
        """
        lead_id = id_context["leadId"]
        vehicle_id = id_context["vehicleId"]
        dealer_id = id_context["dealerId"]

        lead = self.dbcli.leads_container.get_item_with_id(lead_id)
        # vehicle returns a list because it uses query_items
        vehicle = self.dbcli.vehicle_container.query_items_with_vehicle_and_dealership(vehicle_id, dealer_id) 
        dealer = self.dbcli.dealerships_container.get_item_with_id(dealer_id)
        logging.info(f"Hydrated context for lead {lead}, vehicle {vehicle}, dealer {dealer}")
        return {
            "conversationId": id_context["conversationId"],
            "lead": lead if lead else {},                  
            "vehicle": vehicle[0] if vehicle else {},      
            "dealership": dealer if dealer else {}        
        }

    def get_formatting_data(self, customer):
        """
        Extracts and formats all necessary data for the prompt.
        
        Args:
            customer (dict): The customer context containing lead, vehicle, and dealership data.
        
        Returns:
            dict: A flattened dictionary with all relevant fields for prompt formatting.
        """
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
    
    def strip_html(self, html: str) -> str:
        """
        Removes HTML tags, inline styles, and scripts from an email body.
        
        This prepares inbound email payloads for LLM intent analysis and 
        database storage, ensuring the AI does not process raw markup.

        Args:
            html (str): The raw HTML string from the inbound email.

        Returns:
            str: The cleaned, plain-text string.
        """
        soup = BeautifulSoup(html, "html.parser")
        # remove style and script tags entirely
        for tag in soup(["style", "script"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())
    
    def strip_quoted_reply(self, body: str) -> str:
        """
        Removes historical quoted replies from an email body using common email client patterns.
        
        This ensures the LLM only analyzes the lead's newest message, preventing 
        hallucinations based on the assistant's own previous replies.

        Args:
            body (str): The cleaned text of the inbound email.

        Returns:
            str: The isolated text of the newest reply.
        """
        cleaned = re.split(r'On .+?wrote:', body, flags=re.DOTALL, maxsplit=1)[0]
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith(">")]
        result = "\n".join(lines)
        result = re.split(r'-{5,}', result, maxsplit=1)[0]
        result = re.split(r'\n--\s*\n', result, maxsplit=1)[0]
        return result.strip()

    def process_response(self, text):
        """
        Processes the raw text output from the model into subject and body components.
        
        Args:
            text (str): The raw output from the LLM, expected to have the subject on the first line and body following.
        
        Returns:
            tuple: (subject, body) where subject is the first line and body is the rest
        """
        parts = text.split("\n", 1)
        subject = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        body = body.replace("\r\n", "<br />").replace("\n", "<br />")
        return (subject, body)

    def fmt_time(self, h: int) -> str:
        """
        Helper function to format an integer hour (0-23) into a 12-hour time string with AM/PM.
        
        Args:
            h (int): The hour in 24-hour format (0-23).
            
        Returns:
            str: The formatted time string (e.g., "2:00 PM").
        """
        if h == 0:
            return "12:00 AM"
        elif h < 12:
            return f"{h}:00 AM"
        elif h == 12:
            return "12:00 PM"
        else:
            return f"{h - 12}:00 PM"

    def build_email_content(self, customer, subject, content):
        """
        Builds the email content using the subject and body returned from the model and the formatting data.
        
        Args:
            customer (dict): The hydrated customer context for formatting.
            subject (str): The raw subject line from the LLM, potentially containing placeholders.
            content (str): The raw body content from the LLM, potentially containing placeholders.
            
        Returns:
            tuple: (resolved_subject, email_html) where:
                - resolved_subject: The subject line with placeholders filled in.
                - email_html: The final HTML content for the email body.
        """
        data = self.get_formatting_data(customer)
        resolved_subject = subject.format(**data) if "{" in subject else subject
        return resolved_subject, build_email_template(content)

    def generate_parsed_ai_response(self, prompts: list, previous_response_id: str = None) -> tuple[
        str, str, str, str, str]:
        """
        Generates a parsed response from the AI model.
        
        Args:
            prompts (list): A list of message prompts to send to the LLM.
            previous_response_id (str): The ID of the previous LLM response for conversation chaining (optional).
        
        Returns:
            tuple: (response_id, raw_output, subject, body, raw_body) where:
                - response_id: The ID of the LLM response.
                - raw_output: The unprocessed text output from the LLM.
                - subject: The extracted subject line from the LLM output.
                - body: The extracted body from the LLM output, with newlines converted to <br />.
                - raw_body: The body text without newline conversion, for any further processing needs.
        """
        resp = self.chat(prompts, previous_response_id=previous_response_id)

        # Clean HTML tables
        raw_output = re.sub(r'\s+<table', '<br><br><table', resp.output_text.strip())

        # Parse Subject and Body
        subject, body = self.process_response(raw_output)
        raw_body = raw_output.split("\n", 1)[1] if "\n" in raw_output else ""

        return resp.id, raw_output, subject, body, raw_body
    
    def inject_booking_tables(self, email_body: str) -> str:
        """
        Injects booking tables into the email body if they exist.
        This is used in the appointment booking flow where the LLM returns available date and time slots as JSON arrays.
        
        Args:
            email_body (str): The email body content that may contain placeholders for date and time tables
            
        Returns:
            str: The email body with any necessary tables injected in place of placeholders.
        """
        if hasattr(self, "_pending_date_candidates") and self._pending_date_candidates:
            table_html = build_date_table(self._pending_date_candidates)
            email_body = email_body.replace("[[DATE_TABLE]]", table_html)
            self._pending_date_candidates = None

        if hasattr(self, "_pending_time_labels") and self._pending_time_labels:
            table_html = build_time_table(self._pending_time_labels)
            email_body = email_body.replace("[[TIME_TABLE]]", table_html)
            self._pending_time_labels = None

        return email_body
