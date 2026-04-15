# CarClinch Dealership Assistant: Email Processing Service

A serverless, AI-driven email processing engine to automate dealership-lead email conversations. This microservice serves as the core of the **CarClinch Dealership Assistant** project, utilizing LLMs hosted on Microsoft Foundry to analyze inbound communications, draft context-aware responses, manage appointment scheduling, and escalate complex or out-of-scope negotiations to human sales personnel.

## Key Features

* **Sentiment/intent Analysis**: Processes inbound messages via the `Analysis` class to detect sentiment, urgency, and specific intents (ex., pricing inquiries, trade-in requests) before invoking the core conversational AI.
* **Appointment Booking:** A booking engine that parses requested dates and times, verifies availability against existing database records, and generates standard `.ics` calendar attachments.
* **Escalation Logic:** Automatically routes sensitive conversations to dealerships with full escalation reason and conversation thread.
* **Serverless & Cloud-Native:** Architected for **Azure Durable Functions**, persisting conversational state and interaction history in **Azure Cosmos DB (NoSQL)**.

## Folder Structure

```text
email-processing-service/
├── .github/workflows/          # CI/CD pipelines (Pytest and Azure Deployment)
├── app/
│   ├── assistant/              # Core Artificial Intelligence and Business Logic
│   │   ├── analysis.py         # Intent and sentiment extraction
│   │   ├── appointment.py      # Scheduling logic and .ics generation
│   │   ├── escalation.py       # Human hand-off protocols
│   │   ├── gpt.py              # OpenAI API client wrapper
│   │   ├── prompts.py          # System instructions for the LLM
│   │   └── assistant.py        # The unified Assistant facade
│   ├── database/
│   │   ├── cosmos.py           # Azure Cosmos DB client and container queries
│   │   └── models.py           # Data schemas
│   └── email/                  # Inbound and Outbound Email Management
│       ├── factory.py          # Email Provider Factory pattern
│       ├── processor.py        # Normalizes inbound email payloads
│       ├── protocol.py         # Standardized email data models
│       └── providers/          # SMTP, Graph, and ACS implementations
├── tests/unit/                 # Pytest suite with isolated, mocked dependencies
├── function_app.py             # Azure Functions HTTP and Timer Triggers
├── Dockerfile                  # Containerized deployment definition
└── requirements.txt            # Python dependencies
```

> ❗**Important**❗: Before continuing to manual deployment below, I instead highly recommend you review the Deployment instructions in documentation [here](https://docs.google.com/document/d/1wHahfUJDdmyAKJxrRkTXH2aZyR6RQWlMjBsrmCD3_W8/edit?tab=t.qbxwcmre6wum) to locally deploy via **Docker Compose**.

## Prerequisites

To execute this service in a local environment, the following are required:
* **Python 3.12**
* **Azure Functions Core Tools** (v4)
* **Azure Cosmos DB NoSQL** resource
* **Azure Service Bus** resource
* **Microsoft Foundry** & model deployment
* **Gmail** Provider email address & app password

## Environment Variables

Establish a `local.settings.json` file (for Azure Functions execution) or a `.env` file in the root directory containing the following configuration parameters:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    
    "FOLLOWUP_TIMER": "24,24,24",
    "FOLLOWUP_TIME_STRUCTURE": "hours",
    "ADMIN_EMAIL": "<admin email of choice; optional>",
    
    "AzureWebJobsServiceBus__fullyQualifiedNamespace": "<your-namespace>.servicebus.windows.net",
    "SB_NAMESPACE": "<your-namespace>.servicebus.windows.net",
    
    "COSMOS_ENDPOINT": "https://<your-cosmos-account>.documents.azure.com:443/",
    "COSMOS_DB_NAME": "CarClinchDB",
    "COSMOS_VERIFY_SSL": "true",
    
    "STORAGE_ACCOUNT_NAME": "<your-storage-account-name>",
    
    "GMAIL_USER": "<sender email of choice>",
    "GMAIL_APP_PASSWORD": "<sender email app password>",
    
    "OPENAI_API_KEY": "your-azure-ai-foundry-key",
    "OPENAI_BASE_URL": "https://<your-foundry-endpoint>.cognitive.microsoft.com/openai/v1",
    "OPENAI_MODEL_NAME": "gpt-4.1-mini"
  }
}
```

## Local Development Setup

1. **Clone the repository and initialize a virtual environment:**
   ```bash
   git clone https://github.com/CarClinch-Dealership-Assistant/email-processing-service.git
   cd email-processing-service
   python -m venv .venv
   source .venv/bin/activate  # On Windows environments: .venv/Scripts/activate
   ```

2. **Install all required dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Initialize the Azure Function locally:**
   ```bash
   func start
   ```

## Testing

Run:
```bash
pytest -v
```

## Deployment Pipeline

This application is configured for continuous integration and continuous deployment (CI/CD) utilizing **GitHub Actions** for latest Docker images and test verification. Commits pushed to the `main` branch will automatically initiate the `cicd.yml` workflow, which performs the following operations:
1. Provisions the requisite Python environment.
2. Executes the complete `pytest` suite to ensure code integrity.
3. Compiles the Docker container image.
```