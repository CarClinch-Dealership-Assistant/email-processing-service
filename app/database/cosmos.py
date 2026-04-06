import logging
import os
from azure.cosmos import CosmosClient, exceptions
from azure.identity import DefaultAzureCredential


class CosmosDBClient:
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

    def query_items(self, container_name: str, query: str, params: list) -> list:
        try:
            container = self.get_container_client(self.database, container_name)
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

