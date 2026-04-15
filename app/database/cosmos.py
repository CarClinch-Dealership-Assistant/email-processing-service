import logging
import os
from azure.cosmos import CosmosClient, exceptions
from azure.identity import DefaultAzureCredential

class DBClient:
    def __init__(self):
        self.endpoint = os.getenv("COSMOS_ENDPOINT")
        self.database = os.getenv("COSMOS_DB_NAME")
        self.verify_ssl = os.getenv("COSMOS_VERIFY_SSL", "true").lower() != "false"
        self._init_client()

    def _init_client(self):
        if self.endpoint:
            self.client = CosmosClient(
                url=self.endpoint,
                credential=DefaultAzureCredential()
            )
            return
        connection_string = os.getenv("COSMOS_CONNECTION_STRING")
        if not connection_string:
            raise ValueError("Either COSMOS_ENDPOINT or COSMOS_CONNECTION_STRING must be set")
        
        self.client = CosmosClient.from_connection_string(
            connection_string,
            connection_verify=self.verify_ssl
        )

    def _read_item_by_id_and_partition(self, container_name: str, item_id: str, partition_key: str) -> dict:
        try:
            container = self.get_container_client(self.database, container_name)
            # read_item is significantly cheaper and faster than query_items
            return container.read_item(item=item_id, partition_key=partition_key)
        except exceptions.CosmosResourceNotFoundError:
            return None
        
    def _get_database_client(self, db_name: str):
        return self.client.get_database_client(db_name)

    def get_container_client(self, db_name: str, container_name: str):
        return self._get_database_client(db_name).get_container_client(container_name)

    def save_message(self, msg: dict) -> dict:
        try:
            self.get_container_client(self.database, "messages").create_item(body=msg)
            return msg
        except exceptions.CosmosHttpResponseError as e:
            logging.error(f"save_message failed: {e.message}")
            return None

    def query_items(self, container_name: str, query: str, params: list, partition_key: str = None) -> list:
        try:
            container = self.get_container_client(self.database, container_name)
            
            # if partition key, pass it; otherwise, fan out
            if partition_key:
                items = container.query_items(query=query, parameters=params, partition_key=partition_key)
            else:
                items = container.query_items(query=query, parameters=params, enable_cross_partition_query=True)
                
            return list(items)
        except exceptions.CosmosHttpResponseError as e:
            logging.error(f"Query failed: {e.message}")
            return []
    
    def get_item_by_id(self, item_id: str, container_name: str) -> dict:
        results = self.query_items(
            container_name,
            "SELECT * FROM c WHERE c.id = @id",
            [{"name": "@id", "value": item_id}]
        )
        return results[0] if results else None

    def update_item_in_container(self, container_name: str, item: dict) -> dict:
        try:
            self.get_container_client(self.database, container_name).upsert_item(body=item)
            return item
        except exceptions.CosmosHttpResponseError as e:
            logging.error(f"update_item_in_container failed for {item.get('id')}: {e.message}")
            return None

class CosmosDBContainer(DBClient):
    def __init__(self, container_name: str):
        super().__init__()
        self.container_name = container_name

    def query_items_with_params(self, query: str, params: list[dict[str, str]], partition_key: str = None):
        return self.query_items(self.container_name, query, params, partition_key=partition_key)

    def update_item(self, item: dict) -> dict:
        return self.update_item_in_container(self.container_name, item)

    def get_item_with_id(self, id: str) -> dict:
        if id is None:
            return None
        return self.get_item_by_id(id, self.container_name)

class LeadsContainer(CosmosDBContainer):
    container_leads = "leads"
    def __init__(self):
        super().__init__(self.container_leads)

    def query_items_with_email(self, email: str):
        query = "SELECT * FROM c WHERE c.email = @email"
        params = [{"name": "@email", "value": email}]
        return self.query_items_with_params(query, params)

class ConversationContainer(CosmosDBContainer):
    container_conversations = "conversations"
    def __init__(self):
        super().__init__(self.container_conversations)

    def get_conversation_by_lead(self, conversation_id: str, lead_id: str) -> dict:
        return self._read_item_by_id_and_partition(self.container_name, conversation_id, lead_id)
    
    def query_items_with_lead(self, lead_id: str):
        query = "SELECT * FROM c WHERE c.leadId = @leadId AND c.status = 1 ORDER BY c.timestamp DESC OFFSET 0 LIMIT 1"
        params = [{"name": "@leadId", "value": lead_id}]
        return self.query_items_with_params(query, params)

class VehicleContainer(CosmosDBContainer):
    container_vehicles = "vehicles"
    def __init__(self):
        super().__init__(self.container_vehicles)

    def query_items_with_vehicle_and_dealership(self, vehicle_id: str, dealership_id: str):
        query = "SELECT * FROM c WHERE c.id=@id AND c.dealerId=@did"
        params = [{"name": "@id", "value": vehicle_id},{"name": "@did", "value": dealership_id}]
        return self.query_items_with_params(query, params)

class DealershipsContainer(CosmosDBContainer):
    container_dealerships = "dealerships"

    def __init__(self):
        super().__init__(self.container_dealerships)

class MessagesContainer(CosmosDBContainer):
    container_messages = "messages"
    def __init__(self):
        super().__init__(self.container_messages)

    def query_assistant_items_with_msg_id(self, msg_id: str, conversation_id: str):
        query = "SELECT * FROM c WHERE c.emailMessageId = @msgId AND c.role = 'assistant'"
        params = [{"name": "@msgId", "value": msg_id}]
        return self.query_items_with_params(query, params, partition_key=conversation_id)

    def query_user_items_with_conversation_and_time(self, conversation_id: str, startTime: str):
        query = "SELECT * FROM c WHERE c.conversationId = @convId AND c.role = 'user' AND c.timestamp > @startTime"
        params = [{"name": "@convId", "value": conversation_id}, {"name": "@startTime", "value": startTime}]
        return self.query_items_with_params(query, params, partition_key=conversation_id)

    def query_items_with_conversation(self, conversation_id: str):
        query = "SELECT * FROM c WHERE c.conversationId = @convId ORDER BY c.timestamp ASC"
        params = [{"name": "@convId", "value": conversation_id}]
        return self.query_items_with_params(query, params, partition_key=conversation_id)

class AppointmentsContainer(CosmosDBContainer):
    container_appointments = "appointments"
    def __init__(self):
        super().__init__(self.container_appointments)

    def query_appointments_with_dealer_and_date(self, dealer_id: str, date: str):
        query = "SELECT * FROM c WHERE c.dealerId = @did AND c.appointmentDate = @date"
        params = [
            {"name": "@did", "value": dealer_id},
            {"name": "@date", "value": date}
        ]
        return self.query_items_with_params(query, params)

class CosmosDBClient():
    def __init__(self):
        self.message_container = MessagesContainer()
        self.dealerships_container = DealershipsContainer()
        self.vehicle_container = VehicleContainer()
        self.conversation_container  = ConversationContainer()
        self.leads_container = LeadsContainer()
        self.appointments_container = AppointmentsContainer()

