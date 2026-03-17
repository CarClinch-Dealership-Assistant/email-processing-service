import json
from operator import ge
import uuid
import logging
from email.utils import make_msgid, parseaddr
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from app.database.cosmos import CosmosDBClient
from app.email.factory import EmailFactory
from app.assistant.gpt import GPTClient
from app.assistant.template import build_email_template
from app.assistant.prompts import SYSTEM_PROMPT, CONTACT_USER_PROMPT, REPLY_USER_PROMPT


class Assistant(GPTClient):
    def __init__(self):
        super().__init__()

    # helper function to builds message document and stores it in cosmosdb
    def _store_message(
        self, context, response_id, message_id, role, raw_output, subject
    ):
        doc_id = f"msg_{uuid.uuid4().hex[:10]}"
        message_doc = {
            "id": doc_id,
            "conversationId": context.get("conversationId", ""),
            "leadId": context.get("leadId", ""),
            "vehicleId": context.get("vehicleId", ""),
            "dealerId": context.get("dealerId", ""),
            "responseId": response_id,
            "emailMessageId": message_id,
            "role": role,
            "body": raw_output,
            "subject": subject,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        CosmosDBClient().save_message_to_default_container(message_doc)
        logging.info(f"Stored message: {doc_id}")
        return doc_id

    # helper function to build the base message structure w system prompt
    def _get_default_message(self):
        message = []
        system = {"role": "system", "content": SYSTEM_PROMPT}

        message.append(system)
        return message

    # helper function to extract and format all necessary data for prompt
    def _get_formatting_data(self, customer):
        lead = customer["lead"]
        vehicle = customer["vehicle"]
        dealership = customer["dealership"]

        notes = lead.get("notes", "")
        notes_text = (
            notes
            if isinstance(notes, str)
            else " | ".join([n["text"] for n in notes if n.get("text")])
        )

        address = dealership["address1"]
        if dealership.get("address2"):
            address += ", " + dealership["address2"]
            
        data = {
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
        logging.warning(f"Formatting data is: {data}")
        return data

    # helper function to build email content using the subject and body returned from the model and the formatting data
    def _build_email_content(self, customer, subject, content):
        data = self._get_formatting_data(customer)
        return subject.format(**data), build_email_template(content.format(**data))

    # def _strip_html(self, html: str) -> str:
    #     soup = BeautifulSoup(html, "html.parser")
    #     # remove style and script tags entirely
    #     for tag in soup(["style", "script"]):
    #         tag.decompose()
    #     return " ".join(soup.get_text(separator=" ").split())

    # helper function to resolve context for a reply when in_reply_to is present 
    # but there is no chain match based on responseId
    def _resolve_context_from_sender(self, sender: str):
        _, sender_email = parseaddr(sender)
        db = CosmosDBClient()
        leads = db.query_items_from_container(
            "leads",
            "SELECT * FROM c WHERE c.email = @email",
            [{"name": "@email", "value": sender_email.lower()}],
        )
        if not leads:
            logging.warning(f"No lead found for sender: {sender_email}")
            return None
        lead = leads[0]
        conversations = db.query_items_from_container(
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

    # helper function to process the raw text output from the model into subject and body components
    def _process_response(self, text):
        parts = text.split("\n", 1)
        subject = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        body = body.replace("\r\n", "<br />").replace("\n", "<br />")
        return (subject, body)

    # for initial contact from lead form intake
    def contact(self, customer: dict):
        # get data dictionary
        data = self._get_formatting_data(customer)

        # build prompt with context
        user_prompt = CONTACT_USER_PROMPT.format(**data)
        prompts = self._get_default_message()
        prompts.append({"role": "user", "content": user_prompt})
        
        # generate content with AI
        resp = self.chat(prompts)
        raw_output = resp.output_text.strip()

        # check for escalation before processing
        try:
            parsed = json.loads(raw_output)
            if parsed.get("escalate") is True:
                logging.warning(
                    f"Contact skipped; escalation detected. Reason: {parsed.get('reason')} | Lead: {data['customer_email']}"
                )
                return
        except (json.JSONDecodeError, AttributeError):
            pass  # not an escalation response, proceed normally

        # store response_id in the message doc for chaining
        response_id = resp.id

        # build email content
        subject, body = self._process_response(raw_output)
        subject, email_content = self._build_email_content(customer, subject, body)
        
        # call send
        msg_id = make_msgid()
        to = customer["lead"]["email"]
        EmailFactory.get_provider("gmail").send(
            to, subject, email_content, msg_id=msg_id
        )

        # store to db
        context = {
            "conversationId": customer["conversationId"],
            "leadId": customer["lead"]["id"],
            "vehicleId": customer["vehicle"]["id"],
            "dealerId": customer["dealership"]["id"],
        }
        self._store_message(
            context, response_id, msg_id, "assistant", raw_output, subject
        )

    # def _get_email_history(self, conversation_id: str):
    #     query = "SELECT * FROM c WHERE c.conversationId = @conversationId ORDER BY c.timestamp ASC"
    #     params = [{"name": "@conversationId", "value": conversation_id}]
    #     items = CosmosDBClient().query_items_from_default_container(query, params)
    #     messages = []
    #     for item in items:
    #         body = (
    #             "Customer Reply: " + item["body"]
    #             if item["role"] == "user"
    #             else item["body"]
    #         )
    #         messages.append({"role": item["role"], "content": body})
    #     return messages

    # for subsequent replies from lead; main additions is using previous context by responseId when calling .chat()
    def reply(self, received_email):
        
        # query for previous message to get id fields and responseId for chaining
        previous_response_id = None
        context = {}
        in_reply_to = received_email.get("in_reply_to", "")
        if in_reply_to:
            msgs = CosmosDBClient().query_items_from_default_container(
                "SELECT * FROM c WHERE c.emailMessageId = @msgId AND c.role = 'assistant'",
                [{"name": "@msgId", "value": in_reply_to}],
            )
            if msgs:
                previous_response_id = msgs[0].get("responseId")
                context = {
                    "conversationId": msgs[0].get("conversationId", ""),
                    "leadId": msgs[0].get("leadId", ""),
                    "vehicleId": msgs[0].get("vehicleId", ""),
                    "dealerId": msgs[0].get("dealerId", ""),
                }
        # fallback to DB lookup if context not resolved from chain
        if not context:
            logging.warning(
                f"No chain found for in_reply_to: {in_reply_to}, falling back to DB lookup"
            )
            context = self._resolve_context_from_sender(received_email["sender"])
            if not context:
                logging.error(
                    f"DB context resolution failed for sender: {received_email['sender']}. Reply aborted."
                )
                return

        # store the received message in DB for history
        self._store_message(
            context,
            previous_response_id,
            received_email["message_id"],
            "user",
            received_email["body"],
            received_email["subject"],
        )

        # build prompt with context
        prompts = self._get_default_message()
        user_prompt = REPLY_USER_PROMPT.format(received_body=received_email["body"])
        prompts.append({"role": "user", "content": user_prompt})

        # generate content with AI
        resp = self.chat(prompts, previous_response_id=previous_response_id)
        raw_content = resp.output_text.strip()
        
        # check for escalation before processing
        try:
            parsed = json.loads(raw_content)
            if parsed.get("escalate") is True:
                logging.warning(
                    f"Reply skipped; out of scope. Reason: {parsed.get('reason')} | Sender: {received_email['sender']}"
                )
                return  # skip send and store
        except (json.JSONDecodeError, AttributeError):
            pass  # not a guardrail response, proceed normally

        # store response_id in the message doc for chaining
        response_id = resp.id

        # build email content
        subject, body = self._process_response(raw_content)
        email_content = build_email_template(body)
        
        # call reply
        msg_id = make_msgid()
        EmailFactory.get_provider("gmail").reply(
            received_email["sender"],
            received_email["message_id"],
            received_email["subject"],
            email_content,
            msg_id=msg_id,
        )
        
        # store to db
        self._store_message(
            context, response_id, msg_id, "assistant", raw_content, subject
        )
