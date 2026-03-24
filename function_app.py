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
    
    # start follow-up sequence
    conversation_id = input_data.get("conversationId")
    yield context.call_sub_orchestrator("followup_sequence_orchestrator", conversation_id)


@myApp.activity_trigger(input_name="inputData")
def send_email(inputData: dict):
    try:
        Assistant().contact(inputData)
        return True
    except Exception as e:
        logging.error(f"Error in send_email: {e}")
        raise


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
    
    # only grab valid conversation ID strings
    results = [
        res for res in results 
        if isinstance(res, str) and res.startswith("conv_")
    ]
    
    # start all follow-up sequences at the same time
    if results:
        followup_tasks = [
            context.call_sub_orchestrator("followup_sequence_orchestrator", conv_id) 
            for conv_id in set(results)
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
def process_and_reply_activity(email):
    if email is None or isinstance(email, str):
        return email
    logging.info(f"Processing email from: {email['sender']}")
    try:
        # updated Assistant().reply to return the conversationId
        conv_id = Assistant().reply(email)
        return conv_id
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return False

# ------

@myApp.orchestration_trigger(context_name="context")
def followup_sequence_orchestrator(context: df.DurableOrchestrationContext):
    conversation_id = context.get_input()
    if not conversation_id:
        return

    # get exact time this follow-up sequence started
    sequence_start_time = context.current_utc_datetime.isoformat()
    
    followup_intervals = [int(h.strip()) for h in TIMER_CONFIG.split(",")]

    for sequence_index, hours in enumerate(followup_intervals):
        next_wakeup = context.current_utc_datetime + timedelta(**{TIME_STRUCTURE: hours})
        yield context.create_timer(next_wakeup)

        # pass the conversation id and the start time to the checker
        check_payload = {
            "convId": conversation_id, 
            "startTime": sequence_start_time
        }
        needs_followup = yield context.call_activity("check_needs_followup", check_payload)
        
        if not needs_followup:
            logging.info(f"User replied to {conversation_id}. Ending follow-up sequence.")
            break 

        payload = {"convId": conversation_id, "sequence": sequence_index + 1}
        yield context.call_activity("send_followup_activity", payload)

@myApp.activity_trigger(input_name="payload")
def check_needs_followup(payload: dict) -> bool:
    # update the activity to accept the new payload
    return Assistant().needs_followup(payload["convId"], payload["startTime"])

@myApp.activity_trigger(input_name="payload")
def send_followup_activity(payload: dict):
    Assistant().follow_up(payload["convId"], payload["sequence"])
    return True

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