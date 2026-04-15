import logging
import os
from app.assistant.base import BaseAssistant
from app.assistant.escalation import Escalation
from app.assistant.appointment import Appointment
from app.assistant.prompts import CONTACT_USER_PROMPT, REPLY_USER_PROMPT, FOLLOWUP_USER_PROMPT
from app.email.factory import EmailFactory, DEFAULT_EMAIL_PROVIDER
# from email.utils import make_msgid
from app.assistant.template import build_email_template


ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

class Assistant(Escalation, Appointment):
    def __init__(self):
        super().__init__()

        # for initial contact from lead form intake

    def contact(self, customer: dict):
        data = self.get_formatting_data(customer)
        customer_email = data["customer_email"]
        id_context = {
            "conversationId": customer["conversationId"],
            "leadId": customer["lead"]["id"],
            "vehicleId": customer["vehicle"]["id"],
            "dealerId": customer["dealership"]["id"],
        }

        lead_notes = data.get("lead_notes", "").strip()
        logging.warning(f"Initial contact from {customer_email} with lead notes: {lead_notes}")
        if lead_notes:
            self.store_message(id_context, None, None, self.get_LLM_user_role(), lead_notes, "Form Submission")

        # analyze & escalate
        analysis_results, should_abort = self.analyze_and_check_escalation(lead_notes, customer_email, id_context)
        if should_abort: return

        # process booking
        booking_context, is_finalized = self.process_booking_intent(analysis_results, id_context, customer_email)
        logging.warning(f"[BOOKING CONTEXT] '{booking_context}'")
        if is_finalized: return

        # generate AI content
        user_prompt = CONTACT_USER_PROMPT.format(**data) + booking_context
        prompts = self.get_default_message_prompt()

        prompts.append(self.build_user_message_prompt(user_prompt))
        response_id, raw_output, subject, body, raw_body = self.generate_parsed_ai_response(prompts)

        body = self.inject_booking_tables(body)
        
        # final escalation check
        if self.escalate(raw_output, customer_email, id_context): return

        # send and store
        subject, email_content = self.build_email_content(customer, subject, body)
        msg_id = self.make_msgid(id_context["conversationId"])

        EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).send(customer["lead"]["email"], subject, email_content, msg_id=msg_id)
        self.store_message(id_context, response_id, msg_id, self.get_LLM_assistant_role(), raw_body, subject)

        # for subsequent replies from lead

    def reply(self, received_email: dict):
        # query for previous message to get id fields and responseId for chaining
        previous_response_id = None
        id_context = {}
        in_reply_to = received_email.get("in_reply_to", "")

        if in_reply_to:
            logging.info(f"Parsing In-Reply-To header: {in_reply_to}")
            
            # extract conversationId from custom msg_id format: <random.convID@domain>
            try:
                clean_header = in_reply_to.strip("<>")
                local_part = clean_header.split("@")[0]
                if "." in local_part:
                    extracted_conv_id = local_part.split(".")[1]
                    
                    logging.info(f"Extracted conversation ID: {extracted_conv_id}")
                    
                    # fix: single-partition lookup by conversationId
                    conv = self.dbcli.conversation_container.get_item_with_id(extracted_conv_id)
                    
                    if conv:
                         id_context = {
                             "conversationId": conv["id"],
                             "leadId": conv["leadId"],
                             "vehicleId": conv["vehicleId"],
                             "dealerId": conv["dealerId"],
                         }
                         
                         msgs = self.dbcli.message_container.query_assistant_items_with_msg_id(in_reply_to, id_context["conversationId"])
                         if msgs:
                             previous_response_id = msgs[0].get("responseId")
            except Exception as e:
                logging.warning(f"Failed to parse smart msg_id from {in_reply_to}: {e}")
        # fallback to DB lookup if id_context not resolved from chain
        if not id_context:
            logging.warning(
                f"No chain found for in_reply_to: {in_reply_to}, falling back to DB lookup"
            )
            id_context = self.resolve_context_from_sender(received_email["sender"])
            if not id_context:
                logging.error(
                    f"DB id_context resolution failed for sender: {received_email['sender']}. Reply aborted."
                )
                return

        # remove both html and previous quoted replies to get clean message body for analysis and response generation
        stripped_body = self.strip_html(received_email["body"])
        stripped_body = self.strip_quoted_reply(stripped_body)

        # store the received message in DB for history
        self.store_message(
            id_context,
            previous_response_id,
            received_email["message_id"],
            self.get_LLM_user_role(),
            stripped_body,
            received_email["subject"],
        )

        sender_email = received_email["sender"]
        logging.warning(f"Received reply from {sender_email} with body: {stripped_body}")

        # analyze & escalate
        analysis_results, should_abort = self.analyze_and_check_escalation(stripped_body, sender_email, id_context,
                                                                           previous_response_id)
        if should_abort: return

        # process booking
        booking_context, is_finalized = self.process_booking_intent(analysis_results, id_context, sender_email,
                                                                    received_email)
        if is_finalized: return
        logging.warning(f"[BOOKING CONTEXT] '{booking_context}'")

        # generate AI content
        user_prompt = REPLY_USER_PROMPT.format(
            received_body=stripped_body) + booking_context
        prompts = self.get_default_message_prompt()
        prompts.append(self.build_user_message_prompt(user_prompt))

        response_id, raw_output, subject, body, raw_body = self.generate_parsed_ai_response(prompts,
                                                                                            previous_response_id)
        
        body = self.inject_booking_tables(body)
        
        # final escalation check
        if self.escalate(raw_output, sender_email, id_context): return

        # send & store
        email_content = build_email_template(body)
        msg_id = self.make_msgid(id_context["conversationId"])

        EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).reply(sender_email, received_email["message_id"], received_email["subject"],
                                                 email_content, msg_id=msg_id)
        self.store_message(id_context, response_id, msg_id, self.get_LLM_assistant_role(), raw_body, subject)

        return id_context

    # for followup sequence
    def follow_up(self, id_context: dict, sequence: int, start_time: str):
        logging.info(f"Starting follow-up sequence {sequence} for conversation {id_context.get('conversationId')}")
        conversation_id = id_context.get("conversationId")

        # is conversation active still
        convs = self.dbcli.conversation_container.get_item_with_id(conversation_id)
        if not convs or convs[0].get("status") == 0:
            logging.info(f"Conversation {conversation_id} inactive. Aborting follow-up.")
            return False

        # did user reply yet
        reply_count = self.dbcli.message_container.query_user_items_with_conversation_and_time(conversation_id, start_time)
        if len(reply_count) > 0:
            logging.info(f"User replied to {conversation_id}. Aborting follow-up.")
            return False

        customer = self.hydrate_customer_context(id_context)

        # ensure hydration found records
        if not customer or not customer.get("lead"):
            logging.error(f"Failed to hydrate id_context for {conversation_id}")
            return

        # check if the vehicle has been sold (status == 2)
        # if sold, abort the follow-up sequence and close the conversation
        if customer["vehicle"].get("status") == 2:
            logging.info(f"Vehicle {customer['vehicle']['id']} sold. Aborting follow-up.")
            self.set_conversation_status(conversation_id, id_context["leadId"], 0)  # mark conversation inactive
            return

        data = self.get_formatting_data(customer)

        # only suggest alt vehicles in 2nd followup and only if the lead hasn't replied yet
        alt_vehicles_text = "No alternatives required for this sequence."
        if sequence == 2:
            dealer_id = id_context["dealerId"]
            vehicle_id = id_context["vehicleId"]

            alt_vehicles = self.dbcli.vehicle_container.query_items_with_vehicle_and_dealership(vehicle_id, dealer_id)
            if alt_vehicles:
                alt_vehicles_text = ""
                for v in alt_vehicles:
                    alt_vehicles_text += f"- {v.get('year')} {v.get('make')} {v.get('model')} ({v.get('trim', 'Base')})\n"
            else:
                alt_vehicles_text = "No direct alternative vehicles currently available in stock."

        data["sequence"] = sequence
        data["alt_vehicles_text"] = alt_vehicles_text

        # generate ai content
        user_prompt = FOLLOWUP_USER_PROMPT.format(**data)
        prompts = self.get_default_message_prompt()
        prompts.append(self.build_user_message_prompt(user_prompt))

        response_id, raw_output, subject, body, raw_body = self.generate_parsed_ai_response(prompts)

        # send & store
        subject, email_content = self.build_email_content(customer, subject, body)
        msg_id = self.make_msgid(id_context["conversationId"])

        EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).send(customer["lead"]["email"], subject, email_content, msg_id=msg_id)
        self.store_message(id_context, response_id, msg_id, self.get_LLM_assistant_role(), raw_body, subject)

        return True
