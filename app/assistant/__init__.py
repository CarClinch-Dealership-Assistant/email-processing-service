import json
import uuid
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from app.database.cosmos import CosmosDBClient
from app.email.factory import EmailFactory
from app.assistant.gpt import GPTClient
from app.assistant.template import build_email_template

system_prompt = """
# Prompt: Automotive Lead Engagement Generator

## 1. Role & Context
You are an email assistant for a used car dealership. Your tone is friendly, professional, and helpful.
Your only permitted tasks are:
- Answering questions about vehicles, pricing, availability, trade-ins, and financing options
- Scheduling, confirming, rescheduling, and cancelling appointments
- Providing dealership information (hours, location, contact details)
- Moving the lead toward a showroom visit or purchase decision

You must never:
- Answer questions unrelated to the dealership, its vehicles, or the sales process
- Provide legal, financial, or insurance advice beyond general financing inquiry context
- Discuss competitor dealerships or vehicles
- Make promises about or negotiate pricing, availability, or financing approval
- Reveal that you are an AI or reference the underlying technology; if asked, say a team member will follow up
- Respond to anything abusive, threatening, or off-topic
- Deviate from the lead's current vehicle of interest unless they explicitly bring up another vehicle

If the lead's latest message falls outside these boundaries, return exactly:
{"escalate": true, "reason": "out_of_scope"}
and nothing else.

## 2. Variable Dictionary (Data Injection)
The following placeholders (encapsulated in `{}`) represent dynamic data injected via API. **Do not modify the key names.**
* **Customer Identifiers:** `{customer_name}`
* **Vehicle Specifications:** `{vehicle_year}`, `{vehicle_make}`, `{vehicle_model}`, `{vehicle_status}`, `{vehicle_trim}`
* **Dealer Contact Matrix:**
  * Communication: `{dealership_email}`, `{dealership_phone}`
  * Location: `{dealership_address}`, `{dealership_city}`, `{dealership_province}`, `{dealership_postal_code}`

## 3. Task Objective
Generate a **Follow-up or Reply Email** for a lead interested in a specific vehicle. Keep replies under 150 words.
If the lead's tone is frustrated or hostile, open with empathy before the response.
When a lead asks a general suitability question about the vehicle, answer it using specific, factual details about that exact year, make, model, and trim — such as fuel economy, reliability ratings, cargo space, safety scores, or cost of ownership. Directly address the lifestyle or use case they mentioned (e.g. student, family, commuter) and explain why or why not this specific vehicle suits it before offering a visit.
If you can reasonably answer the lead's question, answer it first. Only offer a showroom visit as a follow-up, not as a substitute for a real answer.
If a question is partially in-scope and partially out-of-scope, answer the in-scope portion and politely note that a team member can help with the rest.
Do not pad responses with generic phrases like "we'd love to help you" or "feel free to reach out" unless they add meaning. Be direct.
Match the lead's level of formality. If they write casually, respond warmly but not stiffly. If they write formally, match that register.

## 4. Operational Constraints & Logic
* **Formatting:** Use standard professional email formatting (Subject Line, Salutation, Body, Call to Action, Signature Block).
* Do not include labels like 'Subject:', 'Salutation:', 'Body:', or 'Closing:' in the response.
* If asked about price, you may reference the general market range for the vehicle type and year, but never quote a specific number or negotiate. Direct them to contact the sales team for exact pricing.
* If asked about trade-ins or financing, acknowledge the inquiry and let them know the sales team can walk them through options in person or over the phone — do not speculate on approval odds or values.
"""

class Assistant(GPTClient):
    def __init__(self):
        super().__init__()

    def store_message(self, data: dict):
        message_doc = {
            "id": f"msg_{uuid.uuid4().hex[:10]}",
            "conversationId": data.get("conversationId", ""),
            "leadId": data.get("leadId", ""),
            "vehicleId": data.get("vehicleId", ""),
            "dealerId": data.get("dealerId", ""),
            "emailMessageId": data.get("emailMessageId", ""),
            "role": data.get("role", ""),
            "body": data.get("body", ""),
            "subject": data.get("subject", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        CosmosDBClient().save_message_to_container("messages", message_doc)
        logging.info(f"Stored message: {message_doc['id']}")
        return message_doc["id"]

    def save_received_message(self, data: dict, context: dict):
        message_doc = {
            "id": f"msg_{uuid.uuid4().hex[:10]}",
            "conversationId": context.get("conversationId", ""),
            "leadId": context.get("leadId", ""),
            "vehicleId": context.get("vehicleId", ""),
            "dealerId": context.get("dealerId", ""),
            "emailMessageId": data.get("message_id", ""),
            "role": "user",
            "body": data.get("body", ""),
            "subject": data.get("subject", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        CosmosDBClient().save_message_to_container("messages", message_doc)
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

    def _build_email_content(self, customer, subject, content):
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
            "vehicle_mileage": vehicle["mileage"],
            "vehicle_transmission": vehicle["transmission"],
            "vehicle_comments": vehicle["comments"],
            "dealership_email": dealership["email"],
            "dealership_phone": dealership["phone"],
            "dealership_address": address,
            "dealership_city": dealership["city"],
            "dealership_province": dealership["province"],
            "dealership_postal_code": dealership["postal_code"],
        }
        return subject.format(**data), build_email_template(content.format(**data))

    def _strip_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        # remove style and script tags entirely
        for tag in soup(["style", "script"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())

    def contact(self, customer: dict):
        # generate content with AI
        vehicle = customer["vehicle"]
        dealership = customer["dealership"]
        lead = customer["lead"]
        notes = lead.get("notes", [])
        notes_text = " | ".join([n["text"] for n in notes if n.get("text")]) if isinstance(notes, list) else str(notes)
        vehicle_context = f"""
    Vehicle on file:
    - Year/Make/Model/Trim: {vehicle["year"]} {vehicle["make"]} {vehicle["model"]} {vehicle["trim"]}
    - Status: {"new" if vehicle["status"] == 0 else "used"}
    - Mileage: {vehicle["mileage"]}
    - Transmission: {vehicle["transmission"]}
    - Additional notes: {vehicle["comments"]}
    - Lead name: {lead["fname"]}
    - Lead notes: {notes_text}
    - Dealership: {dealership["name"]} | {dealership["city"]} | {dealership["phone"]} | {dealership["email"]}
    """
        user_prompt = f"""Please generate the email content. 
Do not include any labels, brackets, or section markers such as [Subject:], [Salutation:], [Body:], [Closing:], or any similar tags anywhere in the output. Write it as a natural, flowing email.
Be sure to use the "Lead notes" to guide the primary motivation for answering questions.
{vehicle_context}
Expected Output Structure:
```
[Subject:] Inquiry: {{vehicle_year}} {{vehicle_make}} {{vehicle_model}}
[Salutation:] Dear {{customer_name}},
[Body:] Thank you for contacting us at our {{dealership_city}} location... [Incorporate vehicle details here] ...
[Closing:] Best regards,
The Sales Team at {{dealership_city}}
Contact Info Block:
{{dealership_phone}} | {{dealership_email}}
{{dealership_address}}
{{dealership_city}}, {{dealership_province}} {{dealership_postal_code}}
```
"""
        prompts = self._get_default_message()
        prompts.append({"role": "user", "content": user_prompt})
        resp = self.chat(prompts)
        # build email content
        subject, body = self._process_response(resp["choices"][0]["message"]["content"])
        subject, email_content = self._build_email_content(customer, subject, body)
        # call send
        to = customer["lead"]["email"]
        EmailFactory.get_provider("gmail").send(to, subject, email_content)
        # store to db
        msg = {
            "conversationId": customer["conversationId"],
            "leadId": customer["lead"]["id"],
            "vehicleId": customer["vehicle"]["id"],
            "dealerId": customer["dealership"]["id"],
            "emailMessageId": "",
            "role": "assistant",
            "body": self._strip_html(email_content),
            "subject": subject
        }
        self.store_message(msg)

    def _process_response(self, text):
        parts = text.split('\n', 1)
        subject = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        body = body.replace("\r\n", "<br />").replace("\n", "<br />")
        return (subject, body)

    def _get_email_history(self, conversation_id: str):
        query = "SELECT * FROM c WHERE c.conversationId = @conversationId ORDER BY c.timestamp ASC"
        params = [{"name": "@conversationId", "value": conversation_id}]
        items = CosmosDBClient().query_items_from_default_container(query, params)
        messages = []
        for item in items:
            body = "Customer Reply: " + item["body"] if item["role"] == "user" else item["body"]
            messages.append({"role": item["role"], "content": body})
        return messages

    def reply(self, received_email: dict, context: dict):
        self.save_received_message(received_email, context)
        prompts = self._get_default_message()
        # fetch history
        history = self._get_email_history(context["conversationId"])
        prompts.extend(history)
        vehicle = context.get("vehicle")
        dealership = context.get("dealership")
        vehicle_context = f"""
Vehicle on file:
- Year/Make/Model/Trim: {vehicle["year"]} {vehicle["make"]} {vehicle["model"]} {vehicle["trim"]}
- Status: {"new" if vehicle["status"] == 0 else "used"}
- Mileage: {vehicle["mileage"]}
- Transmission: {vehicle["transmission"]}
- Additional notes: {vehicle["comments"]}
- Dealership: {dealership["city"]} | {dealership["phone"]} | {dealership["email"]}
"""
        user_prompt = f"""Please generate the email content for replying. no variables need to be replaced.
{vehicle_context}
Use the vehicle details above when answering any questions about the vehicle. Do not invent specs not listed here."""
        prompts.append({"role": "user", "content": user_prompt})
        # generate content with AI
        resp = self.chat(prompts)
        raw_content = resp["choices"][0]["message"]["content"].strip()
        try:
            parsed = json.loads(raw_content)
            if parsed.get("escalate") is True:
                logging.warning(
                    f"Reply skipped — out of scope. Reason: {parsed.get('reason')} | Sender: {received_email['sender']}"
                )
                return  # skip send and store
        except (json.JSONDecodeError, AttributeError):
            pass  # not a guardrail response, proceed normally

        # build email content

        subject, body = self._process_response(raw_content)
        email_content = build_email_template(body)
        # call reply
        EmailFactory.get_provider("gmail").reply(received_email["sender"], received_email["message_id"], received_email["subject"], email_content)
        # store to db
        msg ={
            "conversationId": context.get("conversationId", ""),
            "leadId": context.get("leadId", ""),
            "vehicleId": context.get("vehicleId", ""),
            "dealerId": context.get("dealerId", ""),
            "emailMessageId": received_email.get("message_id", ""),
            "role": "assistant",
            "body": self._strip_html(email_content),
            "subject": subject
        }
        self.store_message(msg)