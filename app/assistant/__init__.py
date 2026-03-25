import json
from operator import ge
import re
import uuid
import logging
from email.utils import make_msgid, parseaddr
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from app.database.cosmos import CosmosDBClient
from app.email.factory import EmailFactory
from app.assistant.gpt import GPTClient
from app.assistant.template import build_email_template
from app.assistant.prompts import SYSTEM_PROMPT, CONTACT_USER_PROMPT, REPLY_USER_PROMPT, FOLLOWUP_USER_PROMPT
from app.assistant.analysis import Analysis


class Assistant(GPTClient):
    def __init__(self):
        super().__init__()
        self.db = CosmosDBClient()

    # helper function to builds message document and stores it in cosmosdb
    def _store_message(
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
        self.db.save_message_to_default_container(message_doc)
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
            "refId": customer["conversationId"],
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

    # helper function to build email content using the subject and body returned from the model and the formatting data
    def _build_email_content(self, customer, subject, content):
        data = self._get_formatting_data(customer)
        resolved_subject = subject.format(**data) if "{" in subject else subject
        return resolved_subject, build_email_template(content) 
    
    # helper function to remove html tags and extract text content from the email body for analysis and response generation
    def _strip_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        # remove style and script tags entirely
        for tag in soup(["style", "script"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())

    # helper function to remove quoted previous replies from the message body using common email reply patterns
    def _strip_quoted_reply(self, body: str) -> str:
        cleaned = re.split(r'On .+?wrote:', body, flags=re.DOTALL, maxsplit=1)[0]
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith(">")]
        result = "\n".join(lines)
        result = re.split(r'-{5,}', result, maxsplit=1)[0]
        result = re.split(r'\n--\s*\n', result, maxsplit=1)[0]
        return result.strip()

    # helper function to resolve id (ex. vehicleId, dealerId, etc.) id_context for a reply when in_reply_to is present 
    # but there is no chain match based on responseId
    def _resolve_context_from_sender(self, sender: str):
        _, sender_email = parseaddr(sender)
        leads = self.db.query_items_from_container(
            "leads",
            "SELECT * FROM c WHERE c.email = @email",
            [{"name": "@email", "value": sender_email.lower()}],
        )
        if not leads:
            logging.warning(f"No lead found for sender: {sender_email}")
            return None
        lead = leads[0]
        conversations = self.db.query_items_from_container(
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
        
    def _set_conversation_status(self, conversation_id: str, status: int):
        conversation = self.db.get_item_by_id(conversation_id, "conversations")
        if conversation:
            conversation["status"] = status
            self.db.update_item_in_container("conversations", conversation)
            logging.info(f"Updated conversation {conversation_id} to status {status}")
        else:
            logging.error(f"Conversation not found for ID: {conversation_id}")

    # helper function to process the raw text output from the model into subject and body components
    def _process_response(self, text):
        parts = text.split("\n", 1)
        subject = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        body = body.replace("\r\n", "<br />").replace("\n", "<br />")
        return (subject, body)
    
    def _escalation_check(self, output, email, conversationId):
        try:
            parsed = json.loads(output)
            if parsed.get("escalate") is True:
                logging.warning(
                    f"Email skipped; escalation detected. Reason: {parsed.get('intentCategory') }| Sender: {email}"
                )
                self._set_conversation_status(conversationId, status=0)
                return True
        except (json.JSONDecodeError, AttributeError):
            return False  # not an escalation response, proceed normally
    
    # helper to pull the data back out of Cosmos to hydrate the prompt context for the follow-up sequence 
    # since it runs independently of the reply chain and won't have the previous responseId to pull id_context from
    def _hydrate_customer_context(self, id_context: dict) -> dict:
        lead_id = id_context["leadId"]
        vehicle_id = id_context["vehicleId"]
        dealer_id = id_context["dealerId"]
        
        lead = self.db.query_items_from_container("leads", "SELECT * FROM c WHERE c.id=@id", [{"name":"@id","value":lead_id}])
        vehicle = self.db.query_items_from_container("vehicles", "SELECT * FROM c WHERE c.id=@id AND c.dealerId=@did", [{"name":"@id","value":vehicle_id}, {"name":"@did","value":dealer_id}])
        dealer = self.db.query_items_from_container("dealerships", "SELECT * FROM c WHERE c.id=@id", [{"name":"@id","value":dealer_id}])
        
        return {
            "conversationId": id_context["conversationId"],
            "lead": lead[0] if lead else {},
            "vehicle": vehicle[0] if vehicle else {},
            "dealership": dealer[0] if dealer else {}
        }
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
    
# ------------- MAIN METHODS -------------

    # for initial contact from lead form intake
    def contact(self, customer: dict):
        # get data dictionary
        data = self._get_formatting_data(customer)
        
        # FIRST: analyze the lead notes
        analysis_results = Analysis().analyze(data["lead_notes"])
        logging.warning(f"Analysis results: {analysis_results}")
        if self._escalation_check(json.dumps(analysis_results), data["customer_email"], data["refId"]):
            return  # skip send and store if escalation needed based on analysis

        # build prompt with context
        user_prompt = CONTACT_USER_PROMPT.format(**data)
        prompts = self._get_default_message()
        prompts.append({"role": "user", "content": user_prompt})
        
        # generate content with AI
        resp = self.chat(prompts)
        raw_output = resp.output_text.strip()

        # check for escalation before processing
        if self._escalation_check(raw_output, data['customer_email'], data["refId"]):
            return  # skip send and store

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
        id_context = {
            "conversationId": customer["conversationId"],
            "leadId": customer["lead"]["id"],
            "vehicleId": customer["vehicle"]["id"],
            "dealerId": customer["dealership"]["id"],
        }
        
        raw_body = raw_output.split("\n", 1)[1] if "\n" in raw_output else ""
        
        self._store_message(
            id_context, response_id, msg_id, "assistant", raw_body, subject
        )

    # for subsequent replies from lead; main additions is using previous context by responseId when calling .chat()
    def reply(self, received_email):
        
        # query for previous message to get id fields and responseId for chaining
        previous_response_id = None
        id_context = {}
        in_reply_to = received_email.get("in_reply_to", "")
        if in_reply_to:
            msgs = self.db.query_items_from_default_container(
                "SELECT * FROM c WHERE c.emailMessageId = @msgId AND c.role = 'assistant'",
                [{"name": "@msgId", "value": in_reply_to}],
            )
            if msgs:
                previous_response_id = msgs[0].get("responseId")
                id_context = {
                    "conversationId": msgs[0].get("conversationId", ""),
                    "leadId": msgs[0].get("leadId", ""),
                    "vehicleId": msgs[0].get("vehicleId", ""),
                    "dealerId": msgs[0].get("dealerId", ""),
                }
        # fallback to DB lookup if id_context not resolved from chain
        if not id_context:
            logging.warning(
                f"No chain found for in_reply_to: {in_reply_to}, falling back to DB lookup"
            )
            id_context = self._resolve_context_from_sender(received_email["sender"])
            if not id_context:
                logging.error(
                    f"DB id_context resolution failed for sender: {received_email['sender']}. Reply aborted."
                )
                return

        # remove both html and previous quoted replies to get clean message body for analysis and response generation
        stripped_body = self._strip_html(received_email["body"])
        stripped_body = self._strip_quoted_reply(stripped_body)
        
        # store the received message in DB for history
        self._store_message(
            id_context,
            previous_response_id,
            received_email["message_id"],
            "user",
            stripped_body,
            received_email["subject"],
        )
        
        # FIRST: analyze the lead notes
        analysis_results = Analysis().analyze(stripped_body)
        logging.warning(f"Analysis results: {analysis_results}")
        if self._escalation_check(json.dumps(analysis_results), received_email["sender"], id_context["conversationId"]):
            return  # skip send and store if escalation needed based on analysis

        # build prompt with context
        prompts = self._get_default_message()
        user_prompt = REPLY_USER_PROMPT.format(received_body=stripped_body)
        prompts.append({"role": "user", "content": user_prompt})

        # generate content with AI
        resp = self.chat(prompts, previous_response_id=previous_response_id)
        raw_output = resp.output_text.strip()
        
        # check for escalation before processing
        if self._escalation_check(raw_output, received_email["sender"], id_context["conversationId"]):
            return  # skip send and store

        # store response_id in the message doc for chaining
        response_id = resp.id

        # build email content
        subject, body = self._process_response(raw_output)
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
        
        raw_body = raw_output.split("\n", 1)[1] if "\n" in raw_output else ""
        
        # store to db
        self._store_message(
            id_context, response_id, msg_id, "assistant", raw_body, subject
        )
        
        return id_context

    # for followup sequence, which is similar to reply but with added logic to check for alternatives 
    # in the 2nd follow-up and inject that into the prompt
    def follow_up(self, id_context: dict, sequence: int):
        logging.info(f"Starting follow-up sequence {sequence} for conversation {id_context.get('conversationId')}")
        conversation_id = id_context.get("conversationId")
        customer = self._hydrate_customer_context(id_context)
        
        # ensure hydration found records
        if not customer or not customer.get("lead"): 
            logging.error(f"Failed to hydrate id_context for {conversation_id}")
            return
        
        # check if the vehicle has been sold (status == 0)
        # if sold, abort the follow-up sequence and close the conversation
        if customer["vehicle"].get("status") == 0:
            logging.info(f"Vehicle {customer['vehicle']['id']} sold. Aborting follow-up.")
            self._set_conversation_status(conversation_id, 0) # mark conversation inactive
            return

        data = self._get_formatting_data(customer)
        
        # only suggest alt vehicles in 2nd followup and only if the lead hasn't replied yet
        alt_vehicles_text = "No alternatives required for this sequence."
        if sequence == 2:
            dealer_id = id_context["dealerId"]
            vehicle_id = id_context["vehicleId"]
            
            alt_vehicles = self.db.query_items_from_container(
                "vehicles",
                "SELECT TOP 3 * FROM c WHERE c.dealerId = @did AND c.id != @vid AND c.status = 1",
                [{"name": "@did", "value": dealer_id},
                 {"name": "@vid", "value": vehicle_id}]
            )
            
            if alt_vehicles:
                alt_vehicles_text = ""
                for v in alt_vehicles:
                    alt_vehicles_text += f"- {v.get('year')} {v.get('make')} {v.get('model')} ({v.get('trim', 'Base')})\n"
            else:
                alt_vehicles_text = "No direct alternative vehicles currently available in stock."

        # add sequence and alternatives into the data dictionary for the prompt formatter
        data["sequence"] = sequence
        data["alt_vehicles_text"] = alt_vehicles_text

        # build prompt w the FOLLOWUP_USER_PROMPT
        user_prompt = FOLLOWUP_USER_PROMPT.format(**data)
        prompts = self._get_default_message()
        prompts.append({"role": "user", "content": user_prompt})
        
        # rest of this is the same as a usual reply
        resp = self.chat(prompts)
        raw_output = resp.output_text.strip()
        
        subject, body = self._process_response(raw_output)
        subject, email_content = self._build_email_content(customer, subject, body)
        
        msg_id = make_msgid()
        EmailFactory.get_provider("gmail").send(customer["lead"]["email"], subject, email_content, msg_id=msg_id)
        
        raw_body = raw_output.split("\n", 1)[1] if "\n" in raw_output else ""
        self._store_message(id_context, resp.id, msg_id, "assistant", raw_body, subject)
        
    # helper to if we need to followup 
    # check if conv status is still active or not
    # check who sent the last message -
    # if the LAST message in the thread is from the user, they replied
    # if its from us, they ignored us and we need to follow up
    def needs_followup(self, conversation_id: str, start_time: str) -> bool:
        # is the conversation still active?
        conv_query = "SELECT * FROM c WHERE c.id = @id"
        convs = self.db.query_items_from_container(
            "conversations", 
            conv_query, 
            [{"name": "@id", "value": conversation_id}]
        )
        
        # if the conversation doesn't exist or its status is 0 (inactive), stop the timer.
        if not convs or convs[0].get("status") == 0:
            logging.info(f"Conversation {conversation_id} is inactive or missing. Aborting follow-up.")
            return False
        
        query = """
            SELECT VALUE COUNT(1) 
            FROM c 
            WHERE c.conversationId = @convId 
              AND c.role = 'user' 
              AND c.timestamp > @startTime
        """
        params = [
            {"name": "@convId", "value": conversation_id},
            {"name": "@startTime", "value": start_time}
        ]
        
        try:
            result = self.db.query_items_from_default_container(query, params)
            count = result[0] if result else 0
            
            # if count is 0, they haven't replied, so we need to follow up.
            return count == 0
        except Exception as e:
            logging.error(f"Error checking follow-up status: {e}")
            # default to False (don't send) to prevent spamming on DB errors
            return False