from email.utils import parseaddr
from app.database.cosmos import CosmosDBClient
import azure.functions as func
import azure.durable_functions as df
from dataclasses import asdict
import logging
import json
import os
from datetime import timedelta
from dotenv import load_dotenv
from app.email.factory import EmailFactory
from app.assistant import Assistant
load_dotenv()

# env variables for follow-up timer configuration
TIMER_CONFIG = os.getenv("FOLLOWUP_TIMER", "24,48,72")
TIME_STRUCTURE = os.getenv("FOLLOWUP_TIME_STRUCTURE", "hours") # can be hours, minutes, or seconds for testing

myApp = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@myApp.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="leads",
    connection="AzureWebJobsServiceBus"
)
@myApp.durable_client_input(client_name="client")
async def lead_intake_sb_trigger(msg: func.ServiceBusMessage,
    client: df.DurableOrchestrationClient):
    data = json.loads(msg.get_body())
    logging.info(f"New message: {data} ")

    # Start the orchestrator (same concept as Week 4's client.start_new)
    instance_id = await client.start_new(
        "contact_email_orchestrator",
        client_input=data
    )
    logging.info(f"Started orchestration {instance_id}")


@myApp.orchestration_trigger(context_name="context")
def contact_email_orchestrator(context):
    # Get the input data passed from the blob trigger
    input_data = context.get_input()
    logging.info(f"Orchestrator started for: {input_data}")
    # ret is now the response id, email body, and message id
    yield context.call_activity("send_contact_email_activity", input_data)
    
    # start follow-up sequence
    id_context = {
        "conversationId": input_data.get("conversationId"),
        "leadId": input_data["lead"]["id"],
        "vehicleId": input_data["vehicle"]["id"],
        "dealerId": input_data["dealership"]["id"]
    }
    yield context.call_sub_orchestrator("followup_orchestrator", id_context)


@myApp.activity_trigger(input_name="inputData")
def send_contact_email_activity(inputData: dict):
    try:
        Assistant().contact(inputData)
        return True
    except Exception as e:
        logging.error(f"Error in send_contact_email: {e}")
        raise


@myApp.timer_trigger(schedule="0 */1 * * * *", arg_name="myTimer")
@myApp.durable_client_input(client_name="client")
async def imap_polling_timer_trigger(myTimer: func.TimerRequest, client: df.DurableOrchestrationClient) -> None:
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
        task = context.call_activity("send_reply_email_activity", email)
        tasks.append(task)

    results = yield context.task_all(tasks)
    
    # only grab valid id_context dictionaries
    id_contexts_list = [
        res for res in results 
        if isinstance(res, dict) and "conversationId" in res
    ]
    
    # start all follow-up sequences at the same time
    if id_contexts_list:
        unique_contexts = {ctx["conversationId"]: ctx for ctx in id_contexts_list}.values()
        followup_tasks = [
            context.call_sub_orchestrator("followup_orchestrator", ctx) 
            for ctx in unique_contexts
        ]
        yield context.task_all(followup_tasks)
        
    return f"Processed {len(results)} emails."


@myApp.activity_trigger(input_name="dummy")
def fetch_emails_activity(dummy):
    provider = EmailFactory.get_provider("gmail")
    data =  provider.fetch_latest()
    ret = json.dumps([asdict(e) for e in data], ensure_ascii=False, indent=4)
    return ret


@myApp.activity_trigger(input_name="email")
def send_reply_email_activity(email):
    if email is None or isinstance(email, str):
        return email
    logging.info(f"Processing email from: {email['sender']}")
    try:
        # updated Assistant().reply to return the id_context
        id_context = Assistant().reply(email)
        return id_context
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return False

# ------

@myApp.orchestration_trigger(context_name="context")
def followup_orchestrator(context: df.DurableOrchestrationContext):
    id_context = context.get_input()
    if not id_context or not isinstance(id_context, dict):
        return
    conversation_id = id_context.get("conversationId")
    # get exact time this follow-up sequence started
    sequence_start_time = context.current_utc_datetime.isoformat()
    
    followup_intervals = [int(h.strip()) for h in TIMER_CONFIG.split(",")]

    for sequence_index, hours in enumerate(followup_intervals):
        next_wakeup = context.current_utc_datetime + timedelta(**{TIME_STRUCTURE: hours})
        yield context.create_timer(next_wakeup)

        # build the combined payload
        payload = {
            "id_context": id_context, 
            "sequence": sequence_index + 1,
            "startTime": sequence_start_time
        }
        
        # call the single merged activity
        sequence_continues = yield context.call_activity("send_followup_email_activity", payload)
        
        # if the activity decided it shouldn't send (user replied or inactive), break the loop
        if not sequence_continues:
            logging.info(f"Sequence aborted for {conversation_id}.")
            break
        
@myApp.activity_trigger(input_name="payload")
def send_followup_email_activity(payload: dict):
    return Assistant().follow_up(
        payload["id_context"], 
        payload["sequence"], 
        payload["startTime"]
    )

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