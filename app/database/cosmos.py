import logging
import os
from azure.cosmos import CosmosClient, exceptions

class CosmosDBClient:
    def __init__(self):
        self.connection_string = os.getenv("COSMOS_CONNECTION_STRING")
        self.database = os.getenv("COSMOS_DB_NAME")
        self.container = os.getenv("COSMOS_DB_CONTAINER")
        self._init_client()

    def _init_client(self):
        self.client = CosmosClient.from_connection_string(
            self.connection_string,
            connection_verify=True
        )

    def _get_database_client(self, db_name: str):
        return self.client.get_database_client(db_name)

    def get_container_client(self, db_name: str, container_name: str):
        return self._get_database_client(db_name).get_container_client(container_name)

    def get_default_container_client(self):
        return self.get_container_client(self.database, self.container)

    def save_message_to_default_container(self, msg: dict[str, str]):
        self.get_default_container_client().create_item(body=msg)
        return msg

    def query_items_from_default_container(self, query: str, params: list[dict[str, str]]):
        try:
            items = self.get_default_container_client().query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            )
            return [item for item in items]
        except exceptions.CosmosHttpResponseError as e:
            logging.error(f"Query failed: {e.message}")
            return []

