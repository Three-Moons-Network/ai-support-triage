"""Shared test configuration for ai-support-triage tests."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add repo root to Python path so imports work correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def aws_credentials(monkeypatch):
    """Set fake AWS credentials for testing."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(autouse=True)
def mock_aws_clients(aws_credentials):
    """Mock AWS clients to prevent real API calls."""
    with (
        patch("src.ingest.get_dynamodb_client") as mock_dynamodb_cls,
        patch("src.ingest.get_sns_client") as mock_sns_cls,
    ):
        mock_dynamodb = MagicMock()
        mock_dynamodb.put_item.return_value = {}
        mock_dynamodb.update_item.return_value = {}
        mock_dynamodb_cls.return_value = mock_dynamodb

        mock_sns = MagicMock()
        mock_sns.publish.return_value = {"MessageId": "test-message-id"}
        mock_sns_cls.return_value = mock_sns

        yield {
            "dynamodb": mock_dynamodb,
            "sns": mock_sns,
        }
