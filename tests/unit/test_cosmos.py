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
    client.get_container_client = MagicMock(return_value=mock_container)

    result = client.query_items("messages", "SELECT * FROM c", [])
    assert result == []


@patch("app.database.cosmos.CosmosDBClient._init_client")
def test_save_message_returns_doc(mock_init):
    from app.database.cosmos import CosmosDBClient

    client = CosmosDBClient()
    mock_container = MagicMock()
    mock_container.create_item.return_value = None
    client.get_container_client = MagicMock(return_value=mock_container)

    doc = {"id": "msg_001", "body": "hello"}
    result = client.save_message(doc)
    assert result == doc


@patch("app.database.cosmos.CosmosDBClient._init_client")
def test_save_message_returns_none_on_error(mock_init):
    from app.database.cosmos import CosmosDBClient
    from azure.cosmos import exceptions

    client = CosmosDBClient()
    mock_container = MagicMock()
    mock_container.create_item.side_effect = exceptions.CosmosHttpResponseError(message="write failed")
    client.get_container_client = MagicMock(return_value=mock_container)

    result = client.save_message({"id": "msg_002", "body": "hello"})
    assert result is None


@patch("app.database.cosmos.CosmosDBClient._init_client")
def test_get_item_by_id_returns_first_result(mock_init):
    from app.database.cosmos import CosmosDBClient

    client = CosmosDBClient()
    expected = {"id": "conv_001", "status": 1}
    client.query_items = MagicMock(return_value=[expected])

    result = client.get_item_by_id("conv_001", "conversations")
    assert result == expected


@patch("app.database.cosmos.CosmosDBClient._init_client")
def test_get_item_by_id_returns_none_when_missing(mock_init):
    from app.database.cosmos import CosmosDBClient

    client = CosmosDBClient()
    client.query_items = MagicMock(return_value=[])

    result = client.get_item_by_id("missing_id", "conversations")
    assert result is None