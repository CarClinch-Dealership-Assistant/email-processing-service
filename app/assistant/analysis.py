import json
import logging
import re
from app.assistant.gpt import GPTClient
from app.assistant.prompts import ANALYSIS_SYSTEM_PROMPT, ANALYSIS_USER_PROMPT

class Analysis(GPTClient):
    """
    The Analysis class is responsible for generating analytics for received lead notes/messages to determine intent, sentiment, tone, urgency, and whether escalation is needed.
    """
    def __init__(self):
        super().__init__()
    
    def analyze(self, received_body: str, previous_response_id: str = None) -> dict:
        """
        Analyzes the received lead message using the LLM and returns a structured dictionary of analysis results.
        
        Args:
            received_body (str): The raw body content of the lead message to be analyzed.
            previous_response_id (str, optional): The ID of the previous response to maintain context.
        
        Returns:
            dict: A structured dictionary of analysis results, including:
                - intentCategory (str): The high-level category of the lead's intent (e.g., "appointment", "pricing", "general_inquiry", "out_of_scope").
                - intentAction (str): The specific action within the intent category (e.g., "request_date", "request_time", "confirm_booking" for appointment intents).
                - appointmentDate (str or None): The date mentioned in the lead's message if applicable, in YYYY-MM-DD format.
                - preferredTimeRange (str or None): The preferred time range mentioned by the lead if applicable (e.g., "morning", "afternoon", "evening").
                - sentimentLabel (str): The sentiment of the message (e.g., "positive", "negative", "neutral").
                - tone (str): The tone of the message (e.g., "formal", "informal", "friendly", "urgent").
                - urgency (str): The urgency level of the lead's request (e.g., "low", "medium", "high").
                - intentConfidence (str): The confidence level of the intent classification (e.g., "low", "medium", "high").
                - escalate (bool): Whether this message should be escalated to a human agent.
                - summary (str): A brief summary of the lead's message.
        """
        user_prompt = ANALYSIS_USER_PROMPT.format(received_body=received_body)
        response = self.chat(
            [self.build_system_message_prompt(ANALYSIS_SYSTEM_PROMPT),
             self.build_user_message_prompt(user_prompt)],
            previous_response_id=previous_response_id
        )
        raw_content = response.output_text.strip()
        
        try:
            # clean the LLM output to extract only the JSON object
            json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
            
            if json_match:
                clean_json = json_match.group(0)
                parsed = json.loads(clean_json)
                return parsed
            else:
                raise ValueError("No JSON object found in the LLM response.")
                
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            logging.error(f"Failed to parse analysis response: {e} | Raw content: {raw_content}")
            return {
                "intentCategory": "out_of_scope",
                "intentAction": "out_of_scope",
                "appointmentDate": None,
                "appointmentTime": None,
                "sentimentLabel": "neutral",
                "tone": "neutral",
                "urgency": "low",
                "intentConfidence": "low",
                "escalate": True,  # default to escalate if analysis fails, since we don't want to miss important messages
                "summary": "Unable to analyze lead message"
            }