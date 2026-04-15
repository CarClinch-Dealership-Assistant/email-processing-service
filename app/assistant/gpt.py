import os
from openai import OpenAI
from app.assistant.prompts import SYSTEM_PROMPT

LLM_ROLE_USER = "user"
LLM_ROLE_ASSISTANT = "assistant"
LLM_ROLE_SYSTEM = "system"
LLM_MESSAGE_KEY_ROLE = "role"
LLM_MESSAGE_KEY_CONTENT = "content"

class GPTClient:
    def __init__(self):
        self.model = os.getenv("OPENAI_MODEL_NAME")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL")
        self.init_client()

    def init_client(self):
        self.cli = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, messages: list[dict[str, str]], previous_response_id: str = None):
        # extract system prompt from messages if present
        instructions = None
        input_messages = []
        for msg in messages:
            if msg[LLM_MESSAGE_KEY_ROLE] == LLM_ROLE_SYSTEM:
                instructions = msg[LLM_MESSAGE_KEY_CONTENT]
            else:
                input_messages.append(msg)

        kwargs = {
            "model": self.model,
            "input": input_messages,
        }
        if instructions:
            kwargs["instructions"] = instructions
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id

        resp = self.cli.responses.create(**kwargs)
        return resp

    def build_message_prompt(self, role, content):
        return {LLM_MESSAGE_KEY_ROLE: role, LLM_MESSAGE_KEY_CONTENT: content}

    def build_assistant_message_prompt(self, content):
        return self.build_message_prompt(LLM_ROLE_ASSISTANT, content)

    def build_user_message_prompt(self, content):
        return self.build_message_prompt(LLM_ROLE_USER, content)

    def build_system_message_prompt(self, content):
        return self.build_message_prompt(LLM_ROLE_SYSTEM, content)

    def get_LLM_user_role(self):
        return LLM_ROLE_USER

    def get_LLM_assistant_role(self):
        return LLM_ROLE_ASSISTANT

    def get_default_message_prompt(self):
        return [self.build_message_prompt(LLM_ROLE_SYSTEM, SYSTEM_PROMPT)]