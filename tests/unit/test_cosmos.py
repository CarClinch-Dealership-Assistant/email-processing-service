# tests/unit/test_cosmos.py
import pytest
from unittest.mock import patch, MagicMock

@patch("app.database.cosmos.CosmosDBClient._init_client")
def test_init_raises_without_any_credentials(mock_init):
    mock_init.side_effect = ValueError("Either COSMOS_ENDPOINT or COSMOS_CONNECTION_STRING must be set")
    from app.database.cosmos import CosmosDBClient
    with pytest.raises(ValueError, match="COSMOS_ENDPOINT or COSMOS_CONNECTION_STRING"):
        CosmosDBClient()

@patch("app.database.cosmos.CosmosDBClient._init_client")
def test_query_returns_empty_list_on_cosmos_error(mock_init):
    from app.database.cosmos import CosmosDBClient
    from azure.cosmos import exceptions
    
    client = CosmosDBClient()
    mock_container = MagicMock()
    mock_container.query_items.side_effect = exceptions.CosmosHttpResponseError(message="bad query")
    client.get_default_container_client = MagicMock(return_value=mock_container)

    result = client.query_items_from_default_container("SELECT * FROM c", [])
    assert result == []

@patch("app.database.cosmos.CosmosDBClient._init_client")
def test_save_message_returns_doc(mock_init):
    from app.database.cosmos import CosmosDBClient

    client = CosmosDBClient()
    mock_container = MagicMock()
    mock_container.create_item.return_value = None
    client.get_default_container_client = MagicMock(return_value=mock_container)

    doc = {"id": "msg_001", "body": "hello"}
    result = client.save_message_to_default_container(doc)
    assert result == doc