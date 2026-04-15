# tests/unit/test_assistant_gpt.py
import pytest
from unittest.mock import patch, MagicMock
from app.assistant.gpt import GPTClient

@pytest.fixture
def gpt():
    with patch("app.assistant.gpt.OpenAI"):
        return GPTClient()

def test_build_message_prompts(gpt):
    user_msg = gpt.build_user_message_prompt("Hello!")
    assert user_msg == {"role": "user", "content": "Hello!"}
    
    sys_msg = gpt.build_system_message_prompt("System rules")
    assert sys_msg == {"role": "system", "content": "System rules"}
    
    ast_msg = gpt.build_assistant_message_prompt("Hi there!")
    assert ast_msg == {"role": "assistant", "content": "Hi there!"}

def test_chat_extracts_system_prompt_to_instructions(gpt):
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of Canada?"}
    ]
    
    gpt.chat(messages)
    
    create_kwargs = gpt.cli.responses.create.call_args[1]
    
    # The system prompt should be stripped from the input array and passed as instructions
    assert create_kwargs["instructions"] == "You are a helpful assistant."
    assert len(create_kwargs["input"]) == 1
    assert create_kwargs["input"][0]["role"] == "user"

def test_chat_passes_previous_response_id(gpt):
    messages = [{"role": "user", "content": "Another question"}]
    
    gpt.chat(messages, previous_response_id="resp_12345")
    
    create_kwargs = gpt.cli.responses.create.call_args[1]
    assert create_kwargs["previous_response_id"] == "resp_12345"