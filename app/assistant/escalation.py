import os
import json
import logging
from datetime import datetime, timezone
from email.utils import make_msgid
from app.email.factory import EmailFactory, DEFAULT_EMAIL_PROVIDER
from app.assistant.template import build_escalation_email_template, build_ack_email_template, build_confirmation_email_template, build_dealer_notification_template, build_date_table, build_time_table
from app.assistant.analysis import Analysis
from app.assistant.base import BaseAssistant

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

class Escalation(BaseAssistant):
    """
    The Escalation class handles the logic related to escalating leads to human agents.
    The Escalation class is responsible for:
    - Analyzing the LLM's output to determine if escalation is needed based on intent category, action, and a specific "escalate" flag.
    - Storing a durable escalation record in the database for tracking and auditing purposes.
    - Sending escalation emails to the dealership and optionally to an admin email, including relevant context and conversation history.
    - Acknowledging the customer with a confirmation email to ensure they are not left waiting without feedback.
    """
    def __init__(self):
        super().__init__()

    def escalate(self, output, customer_email: str, id_context: dict) -> bool:
        try:
            parsed = output if isinstance(output, dict) else json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return False

        if not parsed.get("escalate"):
            return False

        conversation_id = id_context.get("conversationId", "")
        category = parsed.get("intentCategory", "unknown")
        logging.warning(f"Escalation triggered - {category} | Sender: {customer_email}")

        # store a durable escalation record
        self.store_message(
            id_context, None, None, "system",
            json.dumps(parsed),
            f"[ESCALATION] {category}",
        )

        # close the conversation to halt any running follow-up timers
        self.set_conversation_status(conversation_id, id_context["leadId"], 0)

        # fetch full thread for the dealership email
        messages = self.dbcli.message_container.query_items_with_conversation(conversation_id)
        if not messages:
            logging.warning(f"No messages found for conversation {conversation_id}; skipping dealership email.")
        else:
            dealer_id = id_context.get("dealerId") or (messages[0].get("dealerId") if messages else None)
            dealer = self.dbcli.dealerships_container.get_item_with_id(dealer_id)

            if not dealer:
                logging.error(f"Dealership not found for id {dealer_id}; skipping dealership email.")
            else:
                dealership_email = dealer.get("email")
                if not dealership_email:
                    logging.error(f"No email on dealership record {dealer_id}.")
                else:
                    subject, email_html = build_escalation_email_template(
                        conversation_id, customer_email, parsed, messages
                    )
                    EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).send(
                        dealership_email, subject, email_html, msg_id=make_msgid()
                    )
                    logging.info(f"Escalation email sent to {dealership_email}.")
            # also send to admin email if provided
            if ADMIN_EMAIL:
                subject, email_html = build_escalation_email_template(
                    conversation_id, customer_email, parsed, messages
                )
                EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).send(
                    ADMIN_EMAIL, subject, email_html, msg_id=make_msgid()
                )
                logging.info(f"Escalation email sent to admin at {ADMIN_EMAIL}.")

        # acknowledge the customer so they are not left waiting
        EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).send(
            customer_email,
            f"Thank you for responding! [ref: {conversation_id}]",
            build_ack_email_template(),
            msg_id=make_msgid(),
        )
        logging.info(f"Customer ack sent to {customer_email}.")
        return True

    def analyze_and_check_escalation(self, text: str, email: str, id_context: dict,
                                     previous_response_id: str = None) -> tuple[dict, bool]:
        """Runs the LLM analysis, checks the escalation matrix, and returns (analysis_results, should_abort)"""
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        text_for_analysis = f"[Current Date Context: {current_date}]\n{text}"

        analysis_results = Analysis().analyze(text_for_analysis, previous_response_id=previous_response_id)
        logging.warning(f"Analysis results: {analysis_results}")

        is_escalated = self.escalate(analysis_results, email, id_context)
        return analysis_results, is_escalated