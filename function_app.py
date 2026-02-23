import azure.functions as func
import azure.durable_functions as df
import logging
import json
import os
from dotenv import load_dotenv
from azure.communication.email import EmailClient
from azure.cosmos import CosmosClient
from datetime import datetime, timezone
import uuid
from bs4 import BeautifulSoup

from mail_template import build_email_template

load_dotenv()


myApp = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# initiate and access messages container from Cosmos DB
def get_cosmos_container():
    client = CosmosClient.from_connection_string(
        os.getenv("COSMOS_CONNECTION_STRING"),
        connection_verify=False
    )
    db = client.get_database_client(os.getenv("COSMOS_DB_NAME"))
    return db.get_container_client("messages")

# utl to strip html tags for storing clean text in Cosmos DB
def strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # remove style and script tags entirely
    for tag in soup(["style", "script"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())

def build_email_body(data: dict):
    lead = data["lead"]
    vehicle = data["vehicle"]
    dealership = data["dealership"]
    data = {
        "name": lead["fname"],
        "vehicle_year": vehicle["year"],
        "vehicle_make": vehicle["make"],
        "vehicle_model": vehicle["model"],
        "vehicle_status": "new" if vehicle["status"] == 0 else "used",
        "vehicle_trim": vehicle["trim"],
        "dealership_email": dealership["email"],
        "dealership_phone": dealership["phone"],
        "dealership_address1": dealership["address1"],
        "dealership_address2": dealership["address2"],
        "dealership_city": dealership["city"],
        "dealership_province": dealership["province"],
        "dealership_postal_code": dealership["postal_code"],
    }

    customer = """<p>Hello {name}</p>
        <p>Thanks for reaching out about the {vehicle_year} {vehicle_make} {vehicle_model} {vehicle_trim} you viewed on our site. It’s a {vehicle_status} model, and it’s a solid option if you’re looking for something reliable.</p>
        <p>If you’d like to come by and see it in person or take it for a quick drive, I’d be happy to set that up between you and the dealership. I can also walk you through pricing or answer any questions you have about the vehicle.</p>
        """.format(**data)
    dealership = """<p>If interested, you can reach the dealership directly at <a href="mailto:{dealership_email}">{dealership_email}</a> or <a href="tel:{dealership_phone}">{dealership_phone}</a>.  </p>
        <p>They're located at:</br>
        {dealership_address1}</br>
        {dealership_address2}</br>
        {dealership_city}, {dealership_province} {dealership_postal_code}</p>
        """.format(**data)

    return build_email_template(customer, dealership)


@myApp.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="leads",
    connection="AzureWebJobsServiceBus"
)
@myApp.durable_client_input(client_name="client")
async def sb_trigger(msg: func.ServiceBusMessage,
    client: df.DurableOrchestrationClient):
    data = json.loads(msg.get_body())
    logging.info(f"New message: {data} ")

    # Start the orchestrator (same concept as Week 4's client.start_new)
    instance_id = await client.start_new(
        "orchestrator_function",
        client_input=data
    )

    logging.info(f"Started orchestration {instance_id}")


@myApp.orchestration_trigger(context_name="context")
def orchestrator_function(context):
    # Get the input data passed from the blob trigger
    input_data = context.get_input()

    logging.info(f"Orchestrator started for: {input_data}")

    # ret is now the response id and email body
    ret = yield context.call_activity("send_email", input_data)

    messages_data = {
        **input_data,
        'acsEmailId': ret["acsEmailId"],
        "emailBody": ret["emailBody"]
    }
    
    # store the message in Cosmos DB
    message_id = yield context.call_activity("store_message", messages_data)
    
    logging.info(f"Message stored with id: {message_id}")
    
    return message_id


@myApp.activity_trigger(input_name="inputData")
def send_email(inputData: dict):
    email_client = EmailClient.from_connection_string(
        os.getenv("ACS_CONNECTION_STRING")
    )

    body = build_email_body(inputData)

    # if inputData has headers, its an inbound reply so grab In-Reply-To from it
    # if not, it's a form submission; no threading needed bc we are starting it
    in_reply_to = inputData.get("headers", {}).get("Message-ID")

    message = {
        "senderAddress": os.getenv("SENDER_ADDRESS"),
        "content": {
            "subject": "Re. Inquiry about {} {} {}".format(
                inputData["vehicle"]["year"],
                inputData["vehicle"]["make"],
                inputData["vehicle"]["model"]),
            "html": body
        },
        "recipients": {
            "to": [
                {
                    "address": inputData["lead"]["email"],
                    "displayName": "{} {}".format(inputData["lead"]["fname"], inputData["lead"]["lname"])
                    # "address": "carclinch-dev@outlook.com",
                    # "displayName": "CarClinch Dev"
                }
            ]
        },
        **({"headers": {"In-Reply-To": in_reply_to}} if in_reply_to else {})
    }

    poller = email_client.begin_send(message)
    result = poller.result()
    
    # result is the response body which we get "id" from
    acs_email_id = result.get("id")
    logging.info(f"Email sent, ACS ID: {acs_email_id}")
    return {"acsEmailId": acs_email_id, "emailBody": body}

# activity: store the sent message in Cosmos DB messages container
@myApp.activity_trigger(input_name="inputData")
def store_message(inputData: dict):
    container = get_cosmos_container()
    
    message_doc = {
        "id": f"msg_{uuid.uuid4().hex[:10]}",
        "conversationId": inputData["conversationId"],
        "body": strip_html(inputData.get("emailBody", "")),
        "source": 0,
        "acsEmailId": inputData["acsEmailId"],
        "inReplyTo": inputData.get("headers", {}).get("Message-ID"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    container.create_item(body=message_doc)
    logging.info(f"Stored message: {message_doc['id']}")
    return message_doc["id"]