import os
import logging
import requests


class PIIClient:
    def __init__(self):
        self.endpoint = os.getenv("AZURE_LANGUAGE_ENDPOINT", "").rstrip("/")
        self.api_key = os.getenv("AZURE_LANGUAGE_KEY")
        self.url = f"{self.endpoint}/language/:analyze-text?api-version=2025-11-15-preview"
        self.headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def sanitize(self, text: str) -> str:
        if not text or not text.strip():
            return text

        payload = {
            "kind": "PiiEntityRecognition",
            "parameters": {
                "modelVersion": "latest",
                "redactionPolicy": {"policyKind": "characterMask", "redactionCharacter": "*"}
            },
            "analysisInput": {"documents": [{"id": "1", "language": "en", "text": text}]},
        }

        try:
            response = requests.post(self.url, json=payload, headers=self.headers)
            response.raise_for_status()
            
            results = response.json().get("results", {})
            return results.get("documents", [{}])[0].get("redactedText", text)

        except Exception as e:
            logging.error(f"PII sanitization failed: {e}")
            return text