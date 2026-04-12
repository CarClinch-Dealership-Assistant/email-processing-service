import json
import re
import uuid
import logging
import os
import ast
from dateutil import parser
from email.utils import make_msgid, parseaddr
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta, date
from app.database.cosmos import CosmosDBClient
from app.email.factory import EmailFactory
from app.assistant.gpt import GPTClient
from app.assistant.template import build_email_template, build_escalation_email_template, build_ack_email_template, build_confirmation_email_template, build_dealer_notification_template, build_date_table, build_time_table
from app.assistant.prompts import SYSTEM_PROMPT, CONTACT_USER_PROMPT, REPLY_USER_PROMPT, FOLLOWUP_USER_PROMPT
from app.assistant.analysis import Analysis
from app.assistant.daterange import get_candidate_dates

load_dotenv()

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

class Assistant(GPTClient):
    def __init__(self):
        super().__init__()
        self.db = CosmosDBClient()

    # ==========================================
    # DATABASE & CONTEXT MANAGEMENT
    # ==========================================

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
        self.db.save_message(message_doc)
        logging.info(f"Stored message: {doc_id}")
        return doc_id

    # helper function to resolve id (ex. vehicleId, dealerId, etc.) id_context for a reply when in_reply_to is present 
    # but there is no chain match based on responseId
    def _resolve_context_from_sender(self, sender: str):
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
        
    def _set_conversation_status(self, conversation_id: str, status: int):
        conversation = self.db.get_item_by_id(conversation_id, "conversations")
        if conversation:
            conversation["status"] = status
            self.db.update_item_in_container("conversations", conversation)
            logging.info(f"Updated conversation {conversation_id} to status {status}")
        else:
            logging.error(f"Conversation not found for ID: {conversation_id}")

    # helper to pull the data back out of Cosmos to hydrate the prompt context for the follow-up sequence 
    # since it runs independently of the reply chain and won't have the previous responseId to pull id_context from
    def _hydrate_customer_context(self, id_context: dict) -> dict:
        lead_id = id_context["leadId"]
        vehicle_id = id_context["vehicleId"]
        dealer_id = id_context["dealerId"]
        
        lead = self.db.query_items("leads", "SELECT * FROM c WHERE c.id=@id", [{"name":"@id","value":lead_id}])
        vehicle = self.db.query_items("vehicles", "SELECT * FROM c WHERE c.id=@id AND c.dealerId=@did", [{"name":"@id","value":vehicle_id}, {"name":"@did","value":dealer_id}])
        dealer = self.db.query_items("dealerships", "SELECT * FROM c WHERE c.id=@id", [{"name":"@id","value":dealer_id}])
        
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

    # helper function to process the raw text output from the model into subject and body components
    def _process_response(self, text):
        parts = text.split("\n", 1)
        subject = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        body = body.replace("\r\n", "<br />").replace("\n", "<br />")
        return (subject, body)

    def _fmt_time(self, h: int) -> str:
        if h < 12:
            return f"{h}:00 AM"
        elif h == 12:
            return "12:00 PM"
        else:
            return f"{h - 12}:00 PM"


    # ==========================================
    # APPOINTMENT & BOOKING SYSTEM
    # ==========================================

    def _get_available_timeslots(self, dealer_id: str, date_str: str, time_range: list = None) -> list[int]:
        # if a comma-separated list, just grab the very first date 
        if date_str and "," in date_str:
            date_str = date_str.split(",")[0].strip()

        # sanitize the LLM's date output into strict YYYY-MM-DD
        try:
            parsed_date = parser.parse(date_str)
            strict_date_str = parsed_date.strftime("%Y-%m-%d")
        except Exception as e:
            logging.error(f"Could not parse date string from LLM: {date_str} - {e}")
            return []

        query = "SELECT * FROM c WHERE c.dealerId = @did AND c.appointmentDate = @date"
        params = [
            {"name": "@did", "value": dealer_id},
            {"name": "@date", "value": strict_date_str}
        ]
        
        appointments = self.db.query_items("appointments", query, params) 
        booked_slots = [int(appt["timeslot"]) for appt in appointments]
        
        # base hours (9 AM to 5 PM)
        all_slots = list(range(9, 18)) 
        available = [slot for slot in all_slots if slot not in booked_slots]

        # filter based on the array provided by the LLM
        if time_range:
            # Safely convert from string if the LLM hallucinated quotes
            if isinstance(time_range, str):
                try:
                    time_range = ast.literal_eval(time_range)
                except Exception:
                    time_range = []

            # if it's a valid list, apply the filter
            if isinstance(time_range, list) and len(time_range) >= 2:
                try:
                    start_hr, end_hr = int(time_range[0]), int(time_range[1])
                    available = [s for s in available if start_hr <= s <= end_hr]

                    # fallback: if their requested window is fully booked
                    if not available:
                        logging.warning("Requested time window is fully booked. Falling back to all available slots.")
                        available = [slot for slot in all_slots if slot not in booked_slots]
                except (ValueError, TypeError):
                    pass # Failsafe: if the LLM passed garbage, skip the filter

        return available

    def _get_candidate_dates(self, date_range_str: str = "") -> list[str]:
        candidates = []
        
        # if the LLM passed a string split and clean it
        if date_range_str:
            try:
                # split by comma remove whitespace/newlines and ignore empty strings
                raw_dates = [d.strip() for d in date_range_str.split(",") if d.strip()]
                
                for d in raw_dates:
                    # ensure it looks like YYYY-MM-DD before appending
                    if len(d) == 10:
                        date.fromisoformat(d) 
                        candidates.append(d)
                        
                if candidates:
                    return candidates
            except Exception as e:
                logging.error(f"Failed to parse LLM date string '{date_range_str}': {e}")
        
        # fallback: Next 5 business days if string is empty or unparsable
        d = date.today()
        while len(candidates) < 5:
            d += timedelta(days=1)
            if d.weekday() < 5:
                candidates.append(d.isoformat())
        return candidates

    def _build_booking_context(self, action: str, dealer_id: str, analysis_results: dict) -> str:
        if action in ["request_date", "request_date_range"]:
            # pass the comma-separated string if it exists
            dates_str_from_llm = analysis_results.get("appointmentDate", "")
            candidates = self._get_candidate_dates(dates_str_from_llm)
            
            # check if they provided an integer time with a date range
            requested_time_int = analysis_results.get("appointmentTime")
            logging.warning(f"[BOOKING CONTEXT] action: {action}, date(s): {candidates}, time: {requested_time_int}")
            time_context = ""
            if requested_time_int is not None:
                formatted_time = self._fmt_time(requested_time_int)
                time_context = f" The user specifically requested {formatted_time}. Only suggest dates from the list below where {formatted_time} is available."
            
            display_labels = [date.fromisoformat(d).strftime("%A, %B %d") for d in candidates]
            dates_str = ", ".join(display_labels)
            
            # remove newlines so _process_response doesn't inject <br> tags inside the table HTML
            table_html = build_date_table(candidates).replace("\n", "")
            
            return (
                f"\n\n[SYSTEM NOTIFICATION: The lead wants to book a test drive.{time_context} "
                f"You MUST suggest ONLY the following dates and no others: {dates_str}. "
                f"Do not suggest today or any date not on this list. "
                f"Include this table exactly as-is in your reply: {table_html}]"
            )

        elif action == "request_time" and analysis_results.get("appointmentDate"):
            date_str = analysis_results.get("appointmentDate")
            time_range = analysis_results.get("preferredTimeRange") # <-- EXTRACT IT HERE
            
            # PASS IT HERE
            avail_slots = self._get_available_timeslots(dealer_id, date_str, time_range) 
            
            time_labels = [self._fmt_time(s) for s in avail_slots] if avail_slots else []
            slots_str = ", ".join(time_labels) if time_labels else "No available timeslots for this date."
            
            table_html = build_time_table(time_labels).replace("\n", "") if time_labels else ""
            
            # Format the time range into a readable string for the LLM context if it exists
            pref_text = ""
            if time_range and isinstance(time_range, list) and len(time_range) == 2:
                pref_text = f" between {self._fmt_time(int(time_range[0]))} and {self._fmt_time(int(time_range[1]))}"
            
            return (
                f"\n\n[SYSTEM NOTIFICATION: The user requested an appointment on {date_str}{pref_text}. "
                f"Available timeslots: {slots_str}. "
                f"You MUST suggest ONLY the available timeslots listed above and NO OTHERS. "
                f"If the user requests a time that is not in the list or asks for a time that is not on the exact hour, you MUST tell them it is unavailable. "
                f"{'Include this table exactly as-is in your reply: ' + table_html if table_html else 'Inform the lead there are no available times on this date and ask them to choose another date.'}]"
            )
            
        return ""

    def _generate_ics(self, dealership: dict, vehicle: dict, date_str: str, timeslot_int: int) -> str:
        dt_start = datetime.strptime(f"{date_str} {timeslot_int:02d}:00", "%Y-%m-%d %H:%M")
        dt_end = dt_start + timedelta(hours=1)

        # Generating floating local time (no 'Z' at the end)
        dt_start_str = dt_start.strftime("%Y%m%dT%H%M%S")
        dt_end_str = dt_end.strftime("%Y%m%dT%H%M%S")
        
        now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        uid = uuid.uuid4().hex
        
        address = f"{dealership.get('address1', '')}, {dealership.get('city', '')}"
        summary = f"Test Drive - {vehicle.get('year')} {vehicle.get('make')} {vehicle.get('model')}"
        
        # Outlook strictly requires \r\n for line breaks and the METHOD property
        ics_content = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//CarClinch//Dealership Appointment//EN\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{now_str}\r\n"
            f"DTSTART:{dt_start_str}\r\n"
            f"DTEND:{dt_end_str}\r\n"
            f"SUMMARY:{summary}\r\n"
            f"LOCATION:{dealership.get('name')} - {address}\r\n"
            f"DESCRIPTION:Test drive appointment for the {summary}.\r\n"
            "CLASS:PUBLIC\r\n"
            "STATUS:CONFIRMED\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR"
        )
        return ics_content

    def _finalize_booking(self, id_context: dict, parsed_output: dict, customer_email: str, received_email: dict = None):
        date_str = parsed_output.get("date")
        timeslot = parsed_output.get("timeslot")
        
        appt_id = f"appt_{uuid.uuid4().hex[:10]}"
        appt_doc = {
            "id": appt_id,
            "dealerId": id_context["dealerId"],
            "vehicleId": id_context["vehicleId"],
            "leadId": id_context["leadId"],
            "conversationId": id_context["conversationId"],
            "appointmentDate": date_str,
            "timeslot": str(timeslot)
        }
        self.db.update_item_in_container("appointments", appt_doc) 
        logging.warning(f"[BOOKING SUCCESS] Appointment written to DB for {date_str} at {timeslot}.")

        self._set_conversation_status(id_context["conversationId"], 0)

        leads = self.db.query_items("leads", "SELECT * FROM c WHERE c.id=@id", [{"name": "@id", "value": id_context["leadId"]}])
        if leads:
            lead_doc = leads[0]
            lead_doc["status"] = 1
            self.db.update_item_in_container("leads", lead_doc)

        customer = self._hydrate_customer_context(id_context)
        vehicle = customer["vehicle"]
        dealership = customer["dealership"]
        
        ics_content = self._generate_ics(dealership, vehicle, date_str, int(timeslot))
        subject = f"Appointment Confirmation: {vehicle['year']} {vehicle['make']} {vehicle['model']}"
        time_am_pm = self._fmt_time(int(timeslot))
        
        body_text = f"You are all set for a test drive on {date_str} at {time_am_pm}. A calendar invitation is attached to this email. We look forward to seeing you!"
        email_content = build_confirmation_email_template(vehicle, date_str, time_am_pm)

        msg_id = make_msgid()
        
        if received_email:
            EmailFactory.get_provider("gmail").reply(
                received_email["sender"],
                received_email["message_id"],
                subject,
                email_content,
                msg_id=msg_id,
                attachments=[("invite.ics", ics_content, "text/calendar")] 
            )
        else:
            EmailFactory.get_provider("gmail").send(
                customer_email,
                subject,
                email_content,
                msg_id=msg_id,
                attachments=[("invite.ics", ics_content, "text/calendar")] 
            )
        
        # send to dealership and admin email (if provided) as well
        dealer_email = dealership.get("email")
        if dealer_email:
            dealer_subject = f"[New Appointment] {vehicle['year']} {vehicle['make']} {vehicle['model']} — {date_str} at {time_am_pm}"
            dealer_body = build_dealer_notification_template(
                customer["lead"], vehicle, date_str, time_am_pm, id_context["conversationId"]
            )
            EmailFactory.get_provider("gmail").send(
                dealer_email,
                dealer_subject,
                dealer_body,
                msg_id=make_msgid(),
                attachments=[("invite.ics", ics_content, "text/calendar")]
            )
            logging.info(f"Appointment confirmation forwarded to dealership at {dealer_email}.")
        body_text = f"Test drive confirmed for {date_str} at {time_am_pm}."
        self._store_message(id_context, None, msg_id, "assistant", body_text, subject)
        logging.warning(f"Booking completely finalized for lead {id_context['leadId']}.")
        
        if ADMIN_EMAIL:
            admin_subject = f"[Admin Notification] New Appointment Booked - {vehicle['year']} {vehicle['make']} {vehicle['model']} on {date_str} at {time_am_pm}"
            admin_body = f"A new appointment has been booked.\n\nLead ID: {id_context['leadId']}\nVehicle: {vehicle['year']} {vehicle['make']} {vehicle['model']}\nDate & Time: {date_str} at {time_am_pm}\nConversation ID: {id_context['conversationId']}"
            EmailFactory.get_provider("gmail").send(
                ADMIN_EMAIL,
                admin_subject,
                admin_body,
                msg_id=make_msgid(),
                attachments=[("invite.ics", ics_content, "text/calendar")]
            )
            logging.info(f"Appointment notification sent to admin at {ADMIN_EMAIL}.")


    # ==========================================
    # AI PIPELINE & ORCHESTRATION HELPERS
    # ==========================================

    def _get_default_message(self):
        message = []
        system = {"role": "system", "content": SYSTEM_PROMPT}

        message.append(system)
        return message

    # helper function to build email content using the subject and body returned from the model and the formatting data
    def _build_email_content(self, customer, subject, content):
        data = self._get_formatting_data(customer)
        resolved_subject = subject.format(**data) if "{" in subject else subject
        return resolved_subject, build_email_template(content) 

    # for escalation; log it, close convo, email the dealership with the full thread, and ack the customer
    def _escalate(self, output, customer_email: str, id_context: dict) -> bool:
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
        self._store_message(
            id_context, None, None, "system",
            json.dumps(parsed),
            f"[ESCALATION] {category}",
        )

        # close the conversation to halt any running follow-up timers
        self._set_conversation_status(conversation_id, status=0)

        # fetch full thread for the dealership email
        messages = self.db.query_items(
            "messages",
            "SELECT * FROM c WHERE c.conversationId = @convId ORDER BY c.timestamp ASC",
            [{"name": "@convId", "value": conversation_id}],
        )
        if not messages:
            logging.warning(f"No messages found for conversation {conversation_id}; skipping dealership email.")
        else:
            dealer_id = id_context.get("dealerId") or (messages[0].get("dealerId") if messages else None)
            dealers = self.db.query_items(
                "dealerships",
                "SELECT * FROM c WHERE c.id = @id",
                [{"name": "@id", "value": dealer_id}],
            ) if dealer_id else []

            if not dealers:
                logging.error(f"Dealership not found for id {dealer_id}; skipping dealership email.")
            else:
                dealership_email = dealers[0].get("email")
                if not dealership_email:
                    logging.error(f"No email on dealership record {dealer_id}.")
                else:
                    subject, email_html = build_escalation_email_template(
                        conversation_id, customer_email, parsed, messages
                    )
                    EmailFactory.get_provider("gmail").send(
                        dealership_email, subject, email_html, msg_id=make_msgid()
                    )
                    logging.info(f"Escalation email sent to {dealership_email}.")
            # also send to admin email if provided
            if ADMIN_EMAIL:
                subject, email_html = build_escalation_email_template(
                    conversation_id, customer_email, parsed, messages
                )
                EmailFactory.get_provider("gmail").send(
                    ADMIN_EMAIL, subject, email_html, msg_id=make_msgid()
                )
                logging.info(f"Escalation email sent to admin at {ADMIN_EMAIL}.")
                    
        # acknowledge the customer so they are not left waiting
        EmailFactory.get_provider("gmail").send(
            customer_email,
            f"Thank you for responding! [ref: {conversation_id}]",
            build_ack_email_template(),
            msg_id=make_msgid(),
        )
        logging.info(f"Customer ack sent to {customer_email}.")
        return True

    def _analyze_and_check_escalation(self, text: str, email: str, id_context: dict, previous_response_id: str = None) -> tuple[dict, bool]:
        """Runs the LLM analysis, checks the escalation matrix, and returns (analysis_results, should_abort)"""
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        text_for_analysis = f"[Current Date Context: {current_date}]\n{text}"
        
        analysis_results = Analysis().analyze(text_for_analysis, previous_response_id=previous_response_id)
        logging.warning(f"Analysis results: {analysis_results}")
        
        is_escalated = self._escalate(analysis_results, email, id_context)
        return analysis_results, is_escalated

    def _process_booking_intent(self, analysis_results: dict, id_context: dict, email_address: str, raw_email_data: dict = None) -> tuple[str, bool]:
        """Runs safeguards, handles confirm_booking, and returns (booking_context_string, is_finalized)"""
        booking_context = ""
        if analysis_results.get("intentCategory") != "appointment":
            return booking_context, False
            
        action = analysis_results.get("intentAction")
        date_str = analysis_results.get("appointmentDate", "")
        
        # SAFEGUARD 1: prevent multi-date booking
        if action == "confirm_booking":
            logging.warning("Checking for multi-date input in confirm_booking action: " + date_str)
            if date_str and "," in date_str:
                logging.warning(f"[SAFEGUARD] Prevented multi-date booking for {date_str}. Downgrading to request_date_range.")
                action = "request_date_range"
                analysis_results["intentAction"] = "request_date_range"

        # SAFEGUARD 2: catch invalid times combined with a date range
        if action == "request_time" and date_str and "," in date_str:
            logging.warning(f"[SAFEGUARD] Caught date range combined with invalid time. Downgrading to request_date_range.")
            action = "request_date_range"
            analysis_results["intentAction"] = "request_date_range"

        # Finalize Booking
        if action == "confirm_booking" and analysis_results.get("appointmentDate") and analysis_results.get("appointmentTime") is not None:
            parsed = {
                "date": analysis_results.get("appointmentDate"),
                "timeslot": analysis_results.get("appointmentTime")
            }
            logging.warning(f"[BOOKING FLOW] Confirmed booking for {parsed['date']} at {parsed['timeslot']}:00.")
            
            if raw_email_data:
                self._finalize_booking(id_context, parsed, email_address, raw_email_data) # Reply
            else:
                self._finalize_booking(id_context, parsed, email_address) # Contact
            return "", True
            
        # Build Context Array
        booking_context = self._build_booking_context(action, id_context["dealerId"], analysis_results)
        return booking_context, False

    def _generate_parsed_ai_response(self, prompts: list, previous_response_id: str = None) -> tuple[str, str, str, str, str]:
        """Calls the LLM, fixes table HTML, parses subject/body, and returns all needed strings."""
        resp = self.chat(prompts, previous_response_id=previous_response_id)
        
        # Clean HTML tables
        raw_output = re.sub(r'\s+<table', '<br><br><table', resp.output_text.strip())
        
        # Parse Subject and Body
        subject, body = self._process_response(raw_output)
        raw_body = raw_output.split("\n", 1)[1] if "\n" in raw_output else ""
        
        return resp.id, raw_output, subject, body, raw_body

# ------------- MAIN METHODS -------------

    # for initial contact from lead form intake
    def contact(self, customer: dict):
        data = self._get_formatting_data(customer)
        customer_email = data["customer_email"]
        id_context = {
            "conversationId": customer["conversationId"],
            "leadId": customer["lead"]["id"],
            "vehicleId": customer["vehicle"]["id"],
            "dealerId": customer["dealership"]["id"],
        }
        
        lead_notes = data.get("lead_notes", "").strip()
        if lead_notes:
            self._store_message(id_context, None, None, "user", lead_notes, "Form Submission")
            
        # analyze & escalate
        analysis_results, should_abort = self._analyze_and_check_escalation(lead_notes, customer_email, id_context)
        if should_abort: return

        # process booking
        booking_context, is_finalized = self._process_booking_intent(analysis_results, id_context, customer_email)
        if is_finalized: return

        # generate AI content
        user_prompt = analysis_results.get("summary", "") + CONTACT_USER_PROMPT.format(**data) + booking_context
        prompts = self._get_default_message()
        prompts.append({"role": "user", "content": user_prompt})
        
        response_id, raw_output, subject, body, raw_body = self._generate_parsed_ai_response(prompts)

        # final escalation check
        if self._escalate(raw_output, customer_email, id_context): return 

        # send and store
        subject, email_content = self._build_email_content(customer, subject, body)
        msg_id = make_msgid()
        
        EmailFactory.get_provider("gmail").send(customer["lead"]["email"], subject, email_content, msg_id=msg_id)
        self._store_message(id_context, response_id, msg_id, "assistant", raw_body, subject)


    # for subsequent replies from lead
    def reply(self, received_email: dict):         
        # query for previous message to get id fields and responseId for chaining
        previous_response_id = None
        id_context = {}

        in_reply_to = received_email.get("in_reply_to", "")

        if in_reply_to:
            msgs = self.db.query_items(
                "messages",
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
        
        sender_email = received_email["sender"]
        
        # analyze & escalate
        analysis_results, should_abort = self._analyze_and_check_escalation(stripped_body, sender_email, id_context, previous_response_id)
        if should_abort: return

        # process booking
        booking_context, is_finalized = self._process_booking_intent(analysis_results, id_context, sender_email, received_email)
        if is_finalized: return

        # generate AI content
        user_prompt = analysis_results.get("summary", "") + REPLY_USER_PROMPT.format(received_body=stripped_body) + booking_context
        prompts = self._get_default_message()
        prompts.append({"role": "user", "content": user_prompt})

        response_id, raw_output, subject, body, raw_body = self._generate_parsed_ai_response(prompts, previous_response_id)
        
        # final escalation check
        if self._escalate(raw_output, sender_email, id_context): return

        # send & store
        email_content = build_email_template(body)
        msg_id = make_msgid()
        
        EmailFactory.get_provider("gmail").reply(sender_email, received_email["message_id"], received_email["subject"], email_content, msg_id=msg_id)
        self._store_message(id_context, response_id, msg_id, "assistant", raw_body, subject)
        
        return id_context


    # for followup sequence
    def follow_up(self, id_context: dict, sequence: int, start_time: str):
        logging.info(f"Starting follow-up sequence {sequence} for conversation {id_context.get('conversationId')}")
        conversation_id = id_context.get("conversationId")
        
        # is conversation active still
        conv_query = "SELECT * FROM c WHERE c.id = @id"
        convs = self.db.query_items("conversations", conv_query, [{"name": "@id", "value": conversation_id}])
        if not convs or convs[0].get("status") == 0:
            logging.info(f"Conversation {conversation_id} inactive. Aborting follow-up.")
            return False
        
        # did user reply yet
        reply_query = "SELECT VALUE COUNT(1) FROM c WHERE c.conversationId = @convId AND c.role = 'user' AND c.timestamp > @startTime"
        params = [{"name": "@convId", "value": conversation_id}, {"name": "@startTime", "value": start_time}]
        reply_count = self.db.query_items("messages", reply_query, params)
        if reply_count and reply_count[0] > 0:
            logging.info(f"User replied to {conversation_id}. Aborting follow-up.")
            return False
        
        customer = self._hydrate_customer_context(id_context)
        
        # ensure hydration found records
        if not customer or not customer.get("lead"): 
            logging.error(f"Failed to hydrate id_context for {conversation_id}")
            return
        
        # check if the vehicle has been sold (status == 2)
        # if sold, abort the follow-up sequence and close the conversation
        if customer["vehicle"].get("status") == 2:
            logging.info(f"Vehicle {customer['vehicle']['id']} sold. Aborting follow-up.")
            self._set_conversation_status(conversation_id, 0) # mark conversation inactive
            return

        data = self._get_formatting_data(customer)
        
        # only suggest alt vehicles in 2nd followup and only if the lead hasn't replied yet
        alt_vehicles_text = "No alternatives required for this sequence."
        if sequence == 2:
            dealer_id = id_context["dealerId"]
            vehicle_id = id_context["vehicleId"]
            
            alt_vehicles = self.db.query_items(
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

        data["sequence"] = sequence
        data["alt_vehicles_text"] = alt_vehicles_text

        # generate ai content
        user_prompt = FOLLOWUP_USER_PROMPT.format(**data)
        prompts = self._get_default_message()
        prompts.append({"role": "user", "content": user_prompt})
        
        response_id, raw_output, subject, body, raw_body = self._generate_parsed_ai_response(prompts)
        
        # send & store
        subject, email_content = self._build_email_content(customer, subject, body)
        msg_id = make_msgid()
        
        EmailFactory.get_provider("gmail").send(customer["lead"]["email"], subject, email_content, msg_id=msg_id)
        self._store_message(id_context, response_id, msg_id, "assistant", raw_body, subject)
        
        return True