import os
from openai import OpenAI
from app.assistant.prompts import SYSTEM_PROMPT

LLM_ROLE_USER = "user"
LLM_ROLE_ASSISTANT = "assistant"
LLM_ROLE_SYSTEM = "system"
LLM_MESSAGE_KEY_ROLE = "role"
LLM_MESSAGE_KEY_CONTENT = "content"

class GPTClient:
    """ 
    The GPTClient class is a wrapper around the OpenAI API client to facilitate interactions with the language model.
    The GPTClient class is responsible for:
    - Initializing the OpenAI client with the appropriate API key and base URL.
    - Providing a `chat` method to send messages to the LLM and receive responses, with support for system instructions and maintaining conversation context through previous response IDs.
    - Building message prompts in the format expected by the OpenAI API, including system, user, and assistant roles.
    - Abstracting away the details of the OpenAI API to provide a simple interface for the rest of the assistant's functionality.
    """
    
    def __init__(self):
        self.model = os.getenv("OPENAI_MODEL_NAME")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL")
        self.init_client()

    def init_client(self):
        self.cli = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, messages: list[dict[str, str]], previous_response_id: str = None):
        """
        Sends a message to the LLM and returns the response.
        
        Args:
            messages (list[dict[str, str]]): A list of message dictionaries, each containing a "role" (e.g., "system", "user", "assistant") and "content" (the text of the message).
            previous_response_id (str, optional): The ID of the previous response to maintain conversation context. Defaults to None.
            
        Returns:
            The response from the LLM, which includes the generated text and metadata.
        """
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
        """
        Builds a message prompt dictionary in the format expected by the OpenAI API.
        """
        return {LLM_MESSAGE_KEY_ROLE: role, LLM_MESSAGE_KEY_CONTENT: content}

    def build_assistant_message_prompt(self, content):
        """
        Builds an assistant message prompt dictionary.
        """
        return self.build_message_prompt(LLM_ROLE_ASSISTANT, content)

    def build_user_message_prompt(self, content):
        """ 
        Builds a user message prompt dictionary.
        """
        return self.build_message_prompt(LLM_ROLE_USER, content)

    def build_system_message_prompt(self, content):
        """
        Builds a system message prompt dictionary.
        """
        return self.build_message_prompt(LLM_ROLE_SYSTEM, content)

    def get_LLM_user_role(self):
        """
        Returns the role identifier for the user in the LLM.
        """
        return LLM_ROLE_USER

    def get_LLM_assistant_role(self):
        """
        Returns the role identifier for the assistant in the LLM.
        """
        return LLM_ROLE_ASSISTANT

    def get_default_message_prompt(self):
        """
        Returns a default message prompt list containing only the system prompt. This is used as a starting point for building prompts for the LLM.
        """
        return [self.build_message_prompt(LLM_ROLE_SYSTEM, SYSTEM_PROMPT)]