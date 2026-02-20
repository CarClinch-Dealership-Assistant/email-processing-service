import json
from unittest.mock import MagicMock, patch
import pytest
from function_app import orchestrator_function, sb_trigger

""" 
INTEGRATION TESTS:
this test file contains integration tests that cover the interaction 
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
        return "Email sent"

@pytest.mark.asyncio
# first test: verify that the Service Bus trigger starts the orchestrator w correct input
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

# second test: verify that the orchestrator calls the send_email activity w correct input
def test_orchestrator_function_calls_send_email(sample_input_data):
    # arrange a fake orchestration w the sample input data
    ctx = FakeDFOrchestration(sample_input_data)

    # patch the call_activity method to sim calling the send_email activity and returning a result
    def _call_activity(name, input_data):
        ctx.called_activities.append((name, input_data))
        return "Email sent"

    ctx.call_activity = _call_activity

    # act by running the orchestrator function w the fake context; since it's a generator, we need to simulate the yields
    real_orchestrator = get_user_fn(orchestrator_function)
    gen = real_orchestrator(ctx)

    # in Durable Functions, orchestrator is a generator; we simulate the yields for call_activity
    result = next(gen)  
    # sim the activity function returning "Email sent"
    try:
        final = gen.send("Email sent")
    except StopIteration as e:
        final = e.value

    # assert that the orchestrator called the send_email activity w the correct input data 
    # and that the final result is "Email sent"
    assert ctx.called_activities[0][0] == "send_email"
    assert ctx.called_activities[0][1] == sample_input_data
    assert final == "Email sent"

@patch("function_app.send_email")
# this test combines orchestrator & activity; like mini e2e test
def test_orchestrator_and_activity_integration(mock_send_email, sample_input_data):
    mock_send_email.return_value = "Email sent"

    ctx = FakeDFOrchestration(sample_input_data)

    def _call_activity(name, input_data):
        return mock_send_email(input_data)

    ctx.call_activity = _call_activity

    real_orchestrator = get_user_fn(orchestrator_function)
    gen = real_orchestrator(ctx)
    _ = next(gen)
    try:
        final = gen.send("Email sent")
    except StopIteration as e:
        final = e.value

    mock_send_email.assert_called_once_with(sample_input_data)
    assert final == "Email sent"
