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
    try:
        Assistant().contact(inputData)
        return True
    except Exception as e:
        logging.error(f"Error in send_email: {e}")
        return False


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
        Assistant().reply(email)
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