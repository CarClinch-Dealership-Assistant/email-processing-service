import logging
import ast
import os
import uuid
from app.email.factory import EmailFactory, DEFAULT_EMAIL_PROVIDER
from app.assistant.base import BaseAssistant
from datetime import datetime, timezone, timedelta, date
from app.assistant.template import build_confirmation_email_template, build_dealer_notification_template, build_date_table, build_time_table
from email.utils import make_msgid
from dateutil import parser

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

class Appointment(BaseAssistant):
    def __init__(self):
       super().__init__()

   # ==========================================
   # APPOINTMENT & BOOKING SYSTEM
   # ==========================================
    def get_available_timeslots(self, dealer_id: str, date_str: str, time_range: list = None) -> list[int]:
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
                    pass  # Failsafe: if the LLM passed garbage, skip the filter

        return available

    def get_candidate_dates(self, date_range_str: str = "") -> list[str]:
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

    def build_request_date_context(self, action: str, analysis_results: dict):
        dates_str_from_llm = analysis_results.get("appointmentDate", "")
        candidates = self.get_candidate_dates(dates_str_from_llm)

        # check if they provided an integer time with a date range
        requested_time_int = analysis_results.get("appointmentTime")
        logging.warning(f"[BOOKING CONTEXT] action: {action}, date(s): {candidates}, time: {requested_time_int}")
        time_context = ""
        if requested_time_int is not None:
            formatted_time = self.fmt_time(requested_time_int)
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

    def build_request_time_context(self, dealer_id: str, analysis_results: dict):
        date_str = analysis_results.get("appointmentDate")
        time_range = analysis_results.get("preferredTimeRange")  # <-- EXTRACT IT HERE

        # PASS IT HERE
        avail_slots = self.get_available_timeslots(dealer_id, date_str, time_range)

        time_labels = [self.fmt_time(s) for s in avail_slots] if avail_slots else []
        slots_str = ", ".join(time_labels) if time_labels else "No available timeslots for this date."

        table_html = build_time_table(time_labels).replace("\n", "") if time_labels else ""

        # Format the time range into a readable string for the LLM context if it exists
        pref_text = ""
        if time_range and isinstance(time_range, list) and len(time_range) == 2:
            pref_text = f" between {self.fmt_time(int(time_range[0]))} and {self.fmt_time(int(time_range[1]))}"

        return (
            f"\n\n[SYSTEM NOTIFICATION: The user requested an appointment on {date_str}{pref_text}. "
            f"Available timeslots: {slots_str}. "
            f"You MUST suggest ONLY the available timeslots listed above and NO OTHERS. "
            f"If the user requests a time that is not in the list or asks for a time that is not on the exact hour, you MUST tell them it is unavailable. "
            f"{'Include this table exactly as-is in your reply: ' + table_html if table_html else 'Inform the lead there are no available times on this date and ask them to choose another date.'}]"
        )

    def build_booking_context(self, action: str, dealer_id: str, analysis_results: dict) -> str:
        if action in ["request_date", "request_date_range"]:
            return self.build_request_date_context(action, analysis_results)

        if action == "request_time" and analysis_results.get("appointmentDate"):
            return self.build_request_time_context(dealer_id, analysis_results)

        return ""

    def generate_ics(self, dealership: dict, vehicle: dict, date_str: str, timeslot_int: int) -> str:
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

    def finalize_booking(self, id_context: dict, parsed_output: dict, customer_email: str,
                         received_email: dict = None):
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

        self.set_conversation_status(id_context["conversationId"], 0)

        leads = self.db.query_items("leads", "SELECT * FROM c WHERE c.id=@id",
                                    [{"name": "@id", "value": id_context["leadId"]}])
        if leads:
            lead_doc = leads[0]
            lead_doc["status"] = 1
            self.db.update_item_in_container("leads", lead_doc)

        customer = self.hydrate_customer_context(id_context)
        vehicle = customer["vehicle"]
        dealership = customer["dealership"]

        ics_content = self.generate_ics(dealership, vehicle, date_str, int(timeslot))
        subject = f"Appointment Confirmation: {vehicle['year']} {vehicle['make']} {vehicle['model']}"
        time_am_pm = self.fmt_time(int(timeslot))

        body_text = f"You are all set for a test drive on {date_str} at {time_am_pm}. A calendar invitation is attached to this email. We look forward to seeing you!"
        email_content = build_confirmation_email_template(vehicle, date_str, time_am_pm)

        msg_id = make_msgid()

        if received_email:
            EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).reply(
                received_email["sender"],
                received_email["message_id"],
                subject,
                email_content,
                msg_id=msg_id,
                attachments=[("invite.ics", ics_content, "text/calendar")]
            )
        else:
            EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).send(
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
            EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).send(
                dealer_email,
                dealer_subject,
                dealer_body,
                msg_id=make_msgid(),
                attachments=[("invite.ics", ics_content, "text/calendar")]
            )
            logging.info(f"Appointment confirmation forwarded to dealership at {dealer_email}.")
        body_text = f"Test drive confirmed for {date_str} at {time_am_pm}."
        self.store_message(id_context, None, msg_id, "assistant", body_text, subject)
        logging.warning(f"Booking completely finalized for lead {id_context['leadId']}.")

        if ADMIN_EMAIL:
            admin_subject = f"[Admin Notification] New Appointment Booked - {vehicle['year']} {vehicle['make']} {vehicle['model']} on {date_str} at {time_am_pm}"
            admin_body = f"A new appointment has been booked.\n\nLead ID: {id_context['leadId']}\nVehicle: {vehicle['year']} {vehicle['make']} {vehicle['model']}\nDate & Time: {date_str} at {time_am_pm}\nConversation ID: {id_context['conversationId']}"
            EmailFactory.get_provider(DEFAULT_EMAIL_PROVIDER).send(
                ADMIN_EMAIL,
                admin_subject,
                admin_body,
                msg_id=make_msgid(),
                attachments=[("invite.ics", ics_content, "text/calendar")]
            )
            logging.info(f"Appointment notification sent to admin at {ADMIN_EMAIL}.")

    def process_booking_intent(self, analysis_results: dict, id_context: dict, email_address: str,
                               raw_email_data: dict = None) -> tuple[str, bool]:
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
                logging.warning(
                    f"[SAFEGUARD] Prevented multi-date booking for {date_str}. Downgrading to request_date_range.")
                action = "request_date_range"
                analysis_results["intentAction"] = "request_date_range"

        # SAFEGUARD 2: catch invalid times combined with a date range
        if action == "request_time" and date_str and "," in date_str:
            logging.warning(
                f"[SAFEGUARD] Caught date range combined with invalid time. Downgrading to request_date_range.")
            action = "request_date_range"
            analysis_results["intentAction"] = "request_date_range"

        # Finalize Booking
        if action == "confirm_booking" and analysis_results.get("appointmentDate") and analysis_results.get(
                "appointmentTime") is not None:
            parsed = {
                "date": analysis_results.get("appointmentDate"),
                "timeslot": analysis_results.get("appointmentTime")
            }
            logging.warning(f"[BOOKING FLOW] Confirmed booking for {parsed['date']} at {parsed['timeslot']}:00.")

            if raw_email_data:
                self.finalize_booking(id_context, parsed, email_address, raw_email_data)  # Reply
            else:
                self.finalize_booking(id_context, parsed, email_address)  # Contact
            return "", True

        # Build Context Array
        booking_context = self.build_booking_context(action, id_context["dealerId"], analysis_results)
        return booking_context, False
