import json
from unittest.mock import MagicMock, patch
import pytest
from function_app import orchestrator_function, sb_trigger, store_message

""" 
COMPONENT TESTS:
this test file contains component tests that cover the interaction 
b/t the Service Bus trigger, the DF orchestrator, and the activity function.
The tests use fake implementations of the Service Bus message 
and Durable orchestration to simulate the flow of data through the system.
"""

# funky azure stuff... durable functions are wrapped in a way 
# that makes it hard to access the actual function 
# for testing, so this helper tries to get the actual function 
# regardless of how it's wrapped by azure functions v2.0
def get_user_fn(fn):
    built = fn.build().get_user_function()

    # service bus triggers use _run
    if hasattr(built, "_run"):
        return built._run

    # orchestrators use orchestrator_function
    if hasattr(built, "orchestrator_function"):
        return built.orchestrator_function

    # activity functions use activity_function
    if hasattr(built, "activity_function"):
        return built.activity_function

    # HTTP triggers use client_function
    if hasattr(built, "client_function"):
        return built.client_function

    return built

@pytest.fixture
# this fixture provides a sample input data dictionary that can be used in the tests below
def sample_input_data():
    return {
        "lead": {
            "fname": "Alice",
            "lname": "Yang",
            "email": "alice@example.com",
        },
        "vehicle": {
            "year": 2022,
            "make": "Toyota",
            "model": "Corolla",
            "trim": "LE",
            "status": 0,
        },
        "dealership": {
            "email": "sales@dealer.com",
            "phone": "555-123-4567",
            "address1": "123 Main St",
            "address2": "Unit 4",
            "city": "Ottawa",
            "province": "ON",
            "postal_code": "K1A0B1",
        },
        "conversationId": "conv_test123"
    }

# mock send_email return value matching the current dict shape
MOCK_SEND_EMAIL_RESULT = {
    "acsOperationId": "acs-operation-id-123",
    "emailBody": "<html>test body</html>",
    "messageId": "<testmessageid@carclinch.com>"
}

# simulate Service Bus messages
class FakeServiceBusMessage:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def get_body(self):
        return self._body

# simulate DF orchestration
class FakeDFOrchestration:
    def __init__(self, input_data):
        self._input = input_data
        self.called_activities = []

    def get_input(self):
        return self._input

    def call_activity(self, name, input_data):
        # record call and return a fake result
        self.called_activities.append((name, input_data))
        # in real durable functions this is yielded; here just simulate
        return MOCK_SEND_EMAIL_RESULT

# sb_trigger test

@pytest.mark.asyncio
# verify that the Service Bus trigger starts the orchestrator w correct input
async def test_sb_trigger_starts_orchestration(sample_input_data):
    # arrange the fake Service Bus message and mock DurableOrchestrationClient
    msg = FakeServiceBusMessage(sample_input_data)
    mock_client = MagicMock()
    
    # simulate starting the orchestrator and returning 
    # an awaitable that resolves to an instance ID
    async def fake_start_new(name, client_input=None):
        return "instance_123"

    # set the side effect of start_new to our fake function 
    mock_client.start_new.side_effect = fake_start_new
    
    # act by calling the trigger function with the fake message and mock client
    real_sb_trigger = get_user_fn(sb_trigger)
    await real_sb_trigger(msg, mock_client)

    # assert that start_new was called once w the correct orchestrator name and input data
    mock_client.start_new.assert_called_once()
    args, kwargs = mock_client.start_new.call_args
    assert args[0] == "orchestrator_function"
    assert kwargs["client_input"] == sample_input_data

# orchestrator_function tests

# helper to drive the orchestrator generator through both yields, 
# simulating the activity calls and their results
def _run_orchestrator(ctx, send_result, store_result="msg_abc123"):
    """helper to drive the orchestrator generator through both yields"""
    real_orchestrator = get_user_fn(orchestrator_function)
    gen = real_orchestrator(ctx)
    next(gen)
    try:
        gen.send(send_result)
    except StopIteration:
        return
    try:
        gen.send(store_result)
    except StopIteration:
        return

# verify that the orchestrator calls the send_email activity 
# as the first activity and passes the original input data to it
def test_orchestrator_calls_send_email_first(sample_input_data):
    ctx = FakeDFOrchestration(sample_input_data)

    def _call_activity(name, input_data):
        ctx.called_activities.append((name, input_data))
        return MOCK_SEND_EMAIL_RESULT

    ctx.call_activity = _call_activity
    _run_orchestrator(ctx, MOCK_SEND_EMAIL_RESULT)

    assert ctx.called_activities[0][0] == "send_email"
    assert ctx.called_activities[0][1] == sample_input_data

# verify that the orchestrator calls the store_message activity as 
# the second activity
def test_orchestrator_calls_store_message_second(sample_input_data):
    ctx = FakeDFOrchestration(sample_input_data)

    def _call_activity(name, input_data):
        ctx.called_activities.append((name, input_data))
        return MOCK_SEND_EMAIL_RESULT

    ctx.call_activity = _call_activity
    _run_orchestrator(ctx, MOCK_SEND_EMAIL_RESULT)

    assert ctx.called_activities[1][0] == "store_message"

# verify that the orchestrator passes the acsOperationId, messageId, and emailBody
# from the send_email result into the input of store_message
def test_orchestrator_passes_acs_fields_to_store_message(sample_input_data):
    """orchestrator should pass acsOperationId, messageId, emailBody from send_email into store_message input"""
    ctx = FakeDFOrchestration(sample_input_data)

    def _call_activity(name, input_data):
        ctx.called_activities.append((name, input_data))
        return MOCK_SEND_EMAIL_RESULT

    ctx.call_activity = _call_activity
    _run_orchestrator(ctx, MOCK_SEND_EMAIL_RESULT)

    store_input = ctx.called_activities[1][1]
    assert store_input["acsOperationId"] == MOCK_SEND_EMAIL_RESULT["acsOperationId"]
    assert store_input["messageId"] == MOCK_SEND_EMAIL_RESULT["messageId"]
    assert store_input["emailBody"] == MOCK_SEND_EMAIL_RESULT["emailBody"]

# verify that the store_message input includes the original input_data fields (lead, vehicle, etc.) 
# in addition to the ACS fields
def test_orchestrator_store_message_input_includes_original_data(sample_input_data):
    """store_message input should include the original input_data fields (lead, vehicle, etc.)"""
    ctx = FakeDFOrchestration(sample_input_data)

    def _call_activity(name, input_data):
        ctx.called_activities.append((name, input_data))
        return MOCK_SEND_EMAIL_RESULT

    ctx.call_activity = _call_activity
    _run_orchestrator(ctx, MOCK_SEND_EMAIL_RESULT)

    store_input = ctx.called_activities[1][1]
    assert "lead" in store_input
    assert "vehicle" in store_input
    assert "dealership" in store_input
    assert store_input["conversationId"] == "conv_test123"

# send_email activity tests

@patch("function_app.send_email")
# this test verifies that the orchestrator calls the send_email activity w 
# the correct input data
def test_orchestrator_and_activity_integration(mock_send_email, sample_input_data):
    mock_send_email.return_value = MOCK_SEND_EMAIL_RESULT

    ctx = FakeDFOrchestration(sample_input_data)
    activities_called = []

    def _call_activity(name, input_data):
        activities_called.append((name, input_data))
        if name == "send_email":
            return mock_send_email(input_data)
        return "msg_abc123"

    ctx.call_activity = _call_activity
    _run_orchestrator(ctx, MOCK_SEND_EMAIL_RESULT)

    mock_send_email.assert_called_once_with(sample_input_data)
    assert activities_called[0][0] == "send_email"
    assert activities_called[1][0] == "store_message"

# store_message activity tests

@patch("function_app.get_cosmos_container")
# this test verifies that the store_message function creates a Cosmos DB item with all the expected fields
# assembled by orchestrator
def test_store_message_receives_correct_data_from_orchestrator(mock_get_container, sample_input_data):
    """store_message should correctly handle the data assembled by the orchestrator"""
    mock_container = MagicMock()
    mock_get_container.return_value = mock_container

    # simulate what the orchestrator assembles and passes to store_message
    store_input = {
        **sample_input_data,
        "acsOperationId": MOCK_SEND_EMAIL_RESULT["acsOperationId"],
        "messageId": MOCK_SEND_EMAIL_RESULT["messageId"],
        "emailBody": MOCK_SEND_EMAIL_RESULT["emailBody"]
    }

    result = store_message(store_input)

    mock_container.create_item.assert_called_once()
    assert result.startswith("msg_")

    args, _ = mock_container.create_item.call_args
    doc = args[0] if args else mock_container.create_item.call_args.kwargs["body"]

    assert doc["conversationId"] == "conv_test123"
    assert doc["acsMessageId"] == MOCK_SEND_EMAIL_RESULT["messageId"]
    assert doc["acsInReplyTo"] is None  # first outbound, no headers
    assert doc["source"] == 0


@patch("function_app.get_cosmos_container")
# this test checks that when store_message is called with inputData that contains headers with a Message-ID
# (indicating an inbound reply), the acsInReplyTo field in the stored Cosmos
def test_store_message_handles_inbound_reply_from_orchestrator(mock_get_container, sample_input_data):
    mock_container = MagicMock()
    mock_get_container.return_value = mock_container

    # simulate inbound reply flow — inputData would have headers from the inbound email
    store_input = {
        **sample_input_data,
        "headers": {"Message-ID": "<previous-outbound@carclinch.com>"},
        "acsOperationId": MOCK_SEND_EMAIL_RESULT["acsOperationId"],
        "messageId": MOCK_SEND_EMAIL_RESULT["messageId"],
        "emailBody": MOCK_SEND_EMAIL_RESULT["emailBody"]
    }

    store_message(store_input)

    args, _ = mock_container.create_item.call_args
    doc = args[0] if args else mock_container.create_item.call_args.kwargs["body"]

    assert doc["acsInReplyTo"] == "<previous-outbound@carclinch.com>"
    assert doc["acsMessageId"] == MOCK_SEND_EMAIL_RESULT["messageId"]