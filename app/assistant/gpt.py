import os
from openai import OpenAI


class GPTClient():
    def __init__(self):
        self.model= os.getenv("OPENAI_MODEL_NAME")
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
            if msg["role"] == "system":
                instructions = msg["content"]
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