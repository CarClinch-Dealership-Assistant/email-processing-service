import os
import logging
import requests


class PIIClient:
    def __init__(self):
        self.endpoint = os.getenv("AZURE_LANGUAGE_ENDPOINT", "").rstrip("/")
        self.api_key = os.getenv("AZURE_LANGUAGE_KEY")
        self.url = f"{self.endpoint}/language/:analyze-text?api-version=2024-11-01"
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
                "redactionPolicy": {
                    "policyKind": "characterMask",
                    "redactionCharacter": "*"
                },
                "piiCategories": [
                    "Email",
                    "PhoneNumber",
                    "Person",
                    "Address",
                    "Organization",
                    "IPAddress",
                    "URL",
                    "BankAccountNumber",
                    "PassportNumber",
                    "DriversLicenseNumber",
                ],
            },
            "analysisInput": {
                "documents": [{"id": "1", "language": "en", "text": text}]
            },
        }

        try:
            logging.warning(f"PII request URL: {self.url}")
            logging.warning(f"PII input text: {text}")

            response = requests.post(self.url, json=payload, headers=self.headers)

            logging.warning(f"PII raw status: {response.status_code}")
            logging.warning(f"PII raw response: {response.text}")

            if not response.ok:
                logging.error(f"PII API error {response.status_code}: {response.text}")
                return text

            body = response.json()

            errors = body.get("results", {}).get("errors", [])
            if errors:
                logging.error(f"PII API returned document errors: {errors}")
                return text

            docs = body.get("results", {}).get("documents", [])
            if not docs:
                logging.warning("PII sanitization returned no documents; using original text.")
                return text

            doc = docs[0]

            entities = doc.get("entities", [])
            if entities:
                detected = [
                    (e.get("text"), e.get("category"), round(e.get("confidenceScore", 0), 2))
                    for e in entities
                ]
                logging.warning(f"PII entities detected: {detected}")
            else:
                logging.warning("PII: no entities detected in text.")

            redacted = doc.get("redactedText", text)
            logging.warning(f"PII redacted result: {redacted}")
            return redacted

        except Exception as e:
            logging.error(f"PII sanitization failed: {e}; using original text.")
            return text