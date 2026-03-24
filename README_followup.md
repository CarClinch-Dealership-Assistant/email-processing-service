
## 1. System Architecture 

### Core Components
* **Intake Trigger (Service Bus):** Processes new lead forms and starts the primary orchestration.
* **Inbound Trigger (IMAP Poller):** A 1-minute timer trigger that scans for new emails and resets follow-up sequences upon a human reply.
* **Durable Orchestrator:** A long-running "manager" that handles the configurable 24/48/72-hour sleep cycles using virtual timers

---

## 2. The Follow-up Lifecycle
The system follows a "Wake and Check" pattern. Instead of a complex "kill" signal, the system uses a **Stateless Validation** check every time a timer expires.

### The Sequence Logic
1.  **Initiation:** When an email is sent (`contact` or `reply`), a sub-orchestrator is spawned with the `conversationId` and a `sequence_start_time`.
2.  **Durable Sleep:** The orchestrator calls `context.create_timer()`. This offloads the state to Azure Storage, consuming **zero compute resources** during the wait.
3.  **Hydration & Validation:** Upon waking, the system performs a "Point Read" in Cosmos DB:
    * **Status Check:** Is the conversation still active (status=1)?
    * **Inventory Check:** Is the vehicle still available (status=1)?
    * **Timestamp Check:** Has the user sent any message *after* the `sequence_start_time`?
4.  **Action:** If all checks pass, it generates a sequence-specific email (e.g., Sequence #2 includes alternative vehicles). If any check fails, the orchestrator self-terminates.

---

## 3. Data Flow & Persistence
The system uses `conversationId` as the primary anchor across all containers to ensure high performance and data integrity.
For example, we need to verify that the conversation is still active; otherwise, responseId in `messages` would be the ID I used.

---

## 4. Concurrency & Safety Guardrails
* **Infinite Loop Prevention:** The follow-up logic is a finite `for` loop. Once the final interval in the configuration (like reaching 72 hours) is reached, the orchestrator dies.
* **Collision Handling:** Because we use a relative `sequence_start_time`, if a user replies 12 hours into a 24-hour timer, the "old" timer will wake up, see the new reply in the DB, and abort itself, allowing the "new" timer to take over.
* **Escalation Awareness:** If the LLM detects a request for financing or trade-ins, it marks the conversation `status: 0`. The next time a timer wakes up, it sees this status and stops the automated sequence immediately.

---

## 5. Configuration (Env Vars)
The system is highly configurable via environment variables, allowing for easy testing without code changes:
### Local
* `FOLLOWUP_TIMER_VALUES`: Comma-separated intervals (e.g., `24,24,24`).
* `FOLLOWUP_TIME_STRUCTURE`: The unit of time (e.g., `hours`, `minutes`, or `seconds`). This is for testing, as you can shorten the interview to 24 seconds vs 24 hours using this.