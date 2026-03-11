import os
from openai import OpenAI


class GPTClient():
    def __init__(self):
        self.model="gpt-4.1"
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL")
        self.init_client()

    def init_client(self):
         self.cli = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, messages: list[dict[str, str]]):
        resp = self.cli.chat.completions.create(model=self.model, messages=messages)
        return resp.model_dump()
