import logging
import ast
import os
import uuid
from app.email.factory import EmailFactory, DEFAULT_EMAIL_PROVIDER
from app.assistant.base import BaseAssistant
from app.assistant.prompts import BOOKING_DATE_NOTIFICATION, BOOKING_TIME_NOTIFICATION, BOOKING_TIME_HAS_SLOTS, BOOKING_TIME_NO_SLOTS
from datetime import datetime, timezone, timedelta, date
from app.assistant.template import build_confirmation_email_template, build_dealer_notification_template, build_date_table, build_time_table
# from email.utils import make_msgid
from dateutil import parser

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

class Appointment(BaseAssistant):
    """
    The Appointment class handles the logic related to scheduling appointments.
    The Appointment class is responsible for:
    - Parsing the LLM's output to extract requested appointment dates and times.
    - Querying the database for existing appointments to determine available timeslots.
    - Building context strings to guide the LLM in requesting dates, times, or confirming bookings.
    - Finalizing the booking by writing to the database, sending confirmation emails, and updating conversation status.
    - Generating ICS calendar invites for confirmed appointments.
    - Implementing safeguards to handle cases where the LLM may provide incomplete information (e.g., a time without a date) and prompting accordingly.
    """
    def __init__(self):
       super().__init__()

    def get_available_timeslots(self, dealer_id: str, date_str: str, time_range: list = None) -> list[int]:
        """
        Queries the database for existing appointments to calculate available timeslots.

        Args:
            dealer_id (str): The dealership's unique identifier.
            date_str (str): The requested date in YYYY-MM-DD format.
            time_range (list, optional): A two-item list representing [start_hour, end_hour].

        Returns:
            list[int]: A list of available integers representing 24-hour clock times.
        """
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

        appointments = self.dbcli.appointments_container.query_appointments_with_dealer_and_date(dealer_id, strict_date_str)
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
        """ 
        Parses the date string from the LLM and returns a list of candidate dates in YYYY-MM-DD format.
        
        Args:
            date_range_str (str): The raw date string from the LLM, which could be a single date, a comma-separated list of dates, or an empty string.
            
        Returns:
            list[str]: A list of candidate date strings in YYYY-MM-DD format. If parsing fails, returns the next 5 business days.
        """
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
        """
        Builds the date context for the appointment request based on the LLM's analysis.
        
        Args:
            action (str): The intent action determined by the analysis (e.g., "request_date" or "request_date_range").
            analysis_results (dict): The full analysis results from the LLM, which may contain the raw date string and requested time.
        
        Returns:
            str: The formatted context string to be included in the LLM prompt for requesting dates.
        """
        dates_str_from_llm = analysis_results.get("appointmentDate", "")
        candidates = self.get_candidate_dates(dates_str_from_llm)

        requested_time_int = analysis_results.get("appointmentTime")
        time_context = ""
        if requested_time_int is not None:
            formatted_time = self.fmt_time(requested_time_int)
            time_context = f" The user specifically requested {formatted_time}. Only suggest dates where {formatted_time} is available."

        display_labels = [date.fromisoformat(d).strftime("%A, %B %d") for d in candidates]
        dates_str = ", ".join(display_labels)

        # store candidates for post-processing injection
        self._pending_date_candidates = candidates

        return BOOKING_DATE_NOTIFICATION.format(
            time_context=time_context,
            dates_str=dates_str,
        )

    def build_request_time_context(self, dealer_id: str, analysis_results: dict):
        """
        Builds the time context for the appointment request based on the LLM's analysis.
        
        Args:
            dealer_id (str): The ID of the dealer for which to check availability.
            analysis_results (dict): The full analysis results from the LLM, which may contain the requested date and time range.
        
        Returns:
            str: The formatted context string to be included in the LLM prompt for requesting times.
        """
        date_str = analysis_results.get("appointmentDate")
        time_range = analysis_results.get("preferredTimeRange")
        avail_slots = self.get_available_timeslots(dealer_id, date_str, time_range)
        time_labels = [self.fmt_time(s) for s in avail_slots] if avail_slots else []
        slots_str = ", ".join(time_labels) if time_labels else "No available timeslots for this date."

        pref_text = ""
        if time_range and isinstance(time_range, list) and len(time_range) == 2:
            pref_text = f" between {self.fmt_time(int(time_range[0]))} and {self.fmt_time(int(time_range[1]))}"

        # store for post-processing injection
        self._pending_time_labels = time_labels

        return BOOKING_TIME_NOTIFICATION.format(
            date_str=date_str,
            pref_text=pref_text,
            slots_str=slots_str if slots_str else "No available timeslots for this date.",
            slot_instruction=BOOKING_TIME_NO_SLOTS if not time_labels else BOOKING_TIME_HAS_SLOTS,
        )

    def build_booking_context(self, action: str, dealer_id: str, analysis_results: dict) -> str:
        """ 
        Builds the appropriate context string for the LLM based on the booking intent action and analysis results.
        
        Args:
            action (str): The intent action determined by the analysis (e.g., "request_date", "request_time", "confirm_booking").
            dealer_id (str): The ID of the dealer for which to check availability if needed.
            analysis_results (dict): The full analysis results from the LLM, which may contain requested dates, times, and intent category and action.
        Returns:
            str: The formatted context string to be included in the LLM prompt for guiding the booking flow.
        """
        if action in ["request_date", "request_date_range"]:
            return self.build_request_date_context(action, analysis_results)

        if action == "request_time" and analysis_results.get("appointmentDate"):
            return self.build_request_time_context(dealer_id, analysis_results)

        return ""

    def generate_ics(self, dealership: dict, vehicle: dict, date_str: str, timeslot_int: int) -> str:
        """
        Generates an ICS calendar invite string for the appointment.
        
        Args:
            dealership (dict): The dealership information, expected to contain 'name' and 'address1' and 'city'.
            vehicle (dict): The vehicle information, expected to contain 'year', 'make', and 'model'.
            date_str (str): The appointment date in YYYY-MM-DD format.
            timeslot_int (int): The appointment time as an integer hour in 24-hour format (e.g., 14 for 2 PM).
        
         Returns:
            str: The generated ICS calendar invite string.
        """
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
        """ 
        Finalizes the appointment booking by writing to the database, sending confirmation emails, and updating conversation status.
        
        Args:
            id_context (dict): The conversation context containing leadId, dealerId, vehicleId, and conversationId.
            parsed_output (dict): The parsed output containing the appointment date and time.
            customer_email (str): The email address of the customer.
            received_email (dict, optional): The received email information for replying.
        
        Returns:
            None
        """
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
        self.dbcli.appointments_container.update_item(appt_doc)
        logging.warning(f"[BOOKING SUCCESS] Appointment written to DB for {date_str} at {timeslot}.")

        self.set_conversation_status(id_context["conversationId"], id_context["leadId"], 0)

        lead_doc = self.dbcli.leads_container.get_item_with_id(id_context["leadId"])
        if lead_doc:
            lead_doc["status"] = 1
            logging.warning(f"Updating lead {lead_doc} status to 1 (booked)")
            self.dbcli.leads_container.update_item(lead_doc)

        customer = self.hydrate_customer_context(id_context)
        vehicle = customer["vehicle"]
        dealership = customer["dealership"]

        ics_content = self.generate_ics(dealership, vehicle, date_str, int(timeslot))
        subject = f"Appointment Confirmation: {vehicle['year']} {vehicle['make']} {vehicle['model']}"
        time_am_pm = self.fmt_time(int(timeslot))

        body_text = f"You are all set for a test drive on {date_str} at {time_am_pm}. A calendar invitation is attached to this email. We look forward to seeing you!"
        email_content = build_confirmation_email_template(vehicle, date_str, time_am_pm)

        msg_id = self.make_msgid(id_context["conversationId"])

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
                msg_id=self.make_msgid(id_context["conversationId"]),
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
                msg_id=self.make_msgid(id_context["conversationId"]),
                attachments=[("invite.ics", ics_content, "text/calendar")]
            )
            logging.info(f"Appointment notification sent to admin at {ADMIN_EMAIL}.")

    def process_booking_intent(self, analysis_results: dict, id_context: dict, email_address: str,
                               raw_email_data: dict = None) -> tuple[str, bool]:
        """
        Processes the booking intent from the LLM's analysis results and determines the appropriate context to return for the next prompt.
        
        Args:
            analysis_results (dict): The full analysis results from the LLM, which should contain the intent category, intent action, and any extracted entities such as appointmentDate and appointmentTime.
            id_context (dict): The conversation context containing leadId, dealerId, vehicleId, and conversationId.
            email_address (str): The customer's email address for sending any necessary emails during the booking flow
            raw_email_data (dict, optional): The raw email data if this is being called from a reply flow, which may be needed for replying to the correct email thread.
        
        Returns:
            tuple: (booking_context, booking_finalized) where:
                - booking_context (str): The context string to be included in the next LLM prompt to guide the booking flow. This could be instructions for requesting dates, times, or confirming the booking.
                - booking_finalized (bool): A boolean indicating whether the booking was finalized in this step (i.e., the LLM provided all necessary information and the system was able to finalize the booking). If True, the context can be ignored as the flow is complete.
        """
        booking_context = ""
        if analysis_results.get("intentCategory") != "appointment":
            return booking_context, False

        action = analysis_results.get("intentAction")
        date_str = analysis_results.get("appointmentDate", "")
        time_int = analysis_results.get("appointmentTime")

        # safeguard: auto-upgrade to confirm_booking if we have a single date and a valid time
        if action == "request_time" and time_int is not None and date_str and "," not in date_str:
            logging.warning(f"[SAFEGUARD] Auto-upgraded request_time to confirm_booking for {date_str} at {time_int}:00.")
            action = "confirm_booking"
            analysis_results["intentAction"] = "confirm_booking"
            
        # safeguard: auto-correct single dates incorrectly classified as ranges
        if action == "request_date_range" and date_str and "," not in date_str:
            logging.warning(f"[SAFEGUARD] Auto-corrected request_date_range to request_time for single date {date_str}.")
            action = "request_time"
            analysis_results["intentAction"] = "request_time"

        # safeguard 1: prevent multi-date booking
        if action == "confirm_booking":
            logging.warning("Checking for multi-date input in confirm_booking action: " + date_str)
            if date_str and "," in date_str:
                logging.warning(
                    f"[SAFEGUARD] Prevented multi-date booking for {date_str}. Downgrading to request_date_range.")
                action = "request_date_range"
                analysis_results["intentAction"] = "request_date_range"

        # safeguard: catch invalid times combined with a date range
        if action == "request_time" and date_str and "," in date_str:
            logging.warning(
                f"[SAFEGUARD] Caught date range combined with invalid time. Downgrading to request_date_range.")
            action = "request_date_range"
            analysis_results["intentAction"] = "request_date_range"

        # finalize booking check
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

        # build context array
        booking_context = self.build_booking_context(action, id_context["dealerId"], analysis_results)
        return booking_context, False
