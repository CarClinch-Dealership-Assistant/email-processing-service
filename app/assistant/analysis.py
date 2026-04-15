import json
import logging
import re
from app.assistant.gpt import GPTClient
from app.assistant.prompts import ANALYSIS_SYSTEM_PROMPT, ANALYSIS_USER_PROMPT

class Analysis(GPTClient):
    def __init__(self):
        super().__init__()
        
    # generate analytics for a received lead note/message to determine intent, sentiment, tone, urgency, and whether escalation is needed
    def analyze(self, received_body: str, previous_response_id: str = None) -> dict:
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