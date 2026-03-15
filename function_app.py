from email.utils import parseaddr
from app.database.cosmos import CosmosDBClient
import azure.functions as func
import azure.durable_functions as df
from dataclasses import asdict
import logging
import json
from dotenv import load_dotenv
from app.email.factory import EmailFactory
from app.assistant import Assistant
load_dotenv()


myApp = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

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
    # ret is now the response id, email body, and message id
    yield context.call_activity("send_email", input_data)


@myApp.activity_trigger(input_name="inputData")
def send_email(inputData: dict):
    Assistant().contact(inputData)


@myApp.timer_trigger(schedule="0 */1 * * * *", arg_name="myTimer")
@myApp.durable_client_input(client_name="client")
async def timer_imap_polling(myTimer: func.TimerRequest, client: df.DurableOrchestrationClient) -> None:
    # 启动编排器
    instance_id = await client.start_new("reply_email_orchestrator")
    logging.info(f"Started orchestration with ID = '{instance_id}'.")


@myApp.orchestration_trigger(context_name="context")
def reply_email_orchestrator(context: df.DurableOrchestrationContext):
    data = yield context.call_activity("fetch_emails_activity", None)
    emails = json.loads(data)
    if emails is None or len(emails) == 0:
        return "No emails to process."
    tasks = []
    for email in emails:
        task = context.call_activity("process_and_reply_activity", email)
        tasks.append(task)

    results = yield context.task_all(tasks)
    return f"Processed {len(results)} emails."


@myApp.activity_trigger(input_name="dummy")
def fetch_emails_activity(dummy):
    provider = EmailFactory.get_provider("gmail")
    data =  provider.fetch_latest()
    ret = json.dumps([asdict(e) for e in data], ensure_ascii=False, indent=4)
    return ret


@myApp.activity_trigger(input_name="email")
def process_and_reply_activity(email):
    if email is None or isinstance(email, str):
        return email
    logging.info(f"Processing email from: {email['sender']}")
    try:
        _, sender_email = parseaddr(email["sender"])
        db = CosmosDBClient()

        # 1. find lead by email
        leads = db.query_items_from_container("leads",
            "SELECT * FROM c WHERE c.email = @email",
            [{"name": "@email", "value": sender_email.lower()}]
        )
        if not leads:
            logging.warning(f"No lead found for sender: {sender_email}")
            return False
        lead = leads[0]

        # 2. find most recent active conversation for lead
        conversations = db.query_items_from_container("conversations",
            "SELECT * FROM c WHERE c.leadId = @leadId AND c.status = 1 ORDER BY c.timestamp DESC OFFSET 0 LIMIT 1",
            [{"name": "@leadId", "value": lead["id"]}]
        )
        if not conversations:
            logging.warning(f"No active conversation found for lead: {lead['id']}")
            return False
        conversation = conversations[0]

        # 3. fetch vehicle
        vehicles = db.query_items_from_container("vehicles",
            "SELECT * FROM c WHERE c.id = @id",
            [{"name": "@id", "value": conversation["vehicleId"]}]
        )
        if not vehicles:
            logging.warning(f"Vehicle not found: {conversation['vehicleId']}")
            return False

        # 4. fetch dealership
        dealerships = db.query_items_from_container("dealerships",
            "SELECT * FROM c WHERE c.id = @id",
            [{"name": "@id", "value": conversation["dealerId"]}]
        )
        if not dealerships:
            logging.warning(f"Dealership not found: {conversation['dealerId']}")
            return False

        context = {
            "conversationId": conversation["id"],
            "leadId": lead["id"],
            "vehicleId": conversation["vehicleId"],
            "dealerId": conversation["dealerId"],
            "vehicle": vehicles[0],
            "dealership": dealerships[0]
        }

        Assistant().reply(email, context)
        return True

    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return False


# 2. ACS: Webhook reception (called by Logic App)
# @myApp.route(route="webhook/acs", methods=["POST"])
# def http_acs_receiver(req: func.HttpRequest) -> func.HttpResponse:
#     payload = req.get_json()
#     unified_email_processor(payload, source="acs")
#     return func.HttpResponse("ACS Message Received", status_code=200)

# 3. Graph: Webhook reception (M365 subscription push)
# @myApp.route(route="webhook/graph", methods=["POST"])
# def http_graph_receiver(req: func.HttpRequest) -> func.HttpResponse:
#     payload = req.get_json()
#     unified_email_processor(payload, source="graph")
#     return func.HttpResponse("Graph Message Received", status_code=200)