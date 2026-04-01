"""
Tests for the AI Support Triage ingest handler.

Uses mocking to avoid real DynamoDB/SNS/Anthropic API calls during CI.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.ingest import (
    ClassificationResult,
    classify_ticket,
    lambda_handler,
    parse_ses_event,
    parse_webhook_event,
)


# ---------------------------------------------------------------------------
# parse_ses_event
# ---------------------------------------------------------------------------


class TestParseSesEvent:
    def test_valid_ses_event(self):
        event = {
            "sender": "customer@example.com",
            "subject": "Cannot login",
            "body": "I can't log into my account",
            "messageId": "msg-123",
        }
        sender, subject, body, msg_id = parse_ses_event(event)
        assert sender == "customer@example.com"
        assert subject == "Cannot login"
        assert body == "I can't log into my account"

    def test_missing_sender_raises(self):
        event = {"subject": "Test", "body": "Content"}
        with pytest.raises(ValueError, match="sender"):
            parse_ses_event(event)

    def test_missing_body_raises(self):
        event = {"sender": "test@example.com", "subject": "Test"}
        with pytest.raises(ValueError, match="body"):
            parse_ses_event(event)


# ---------------------------------------------------------------------------
# parse_webhook_event
# ---------------------------------------------------------------------------


class TestParseWebhookEvent:
    def test_valid_webhook_json(self):
        body = json.dumps(
            {
                "email": "user@example.com",
                "subject": "Billing question",
                "message": "Why was I charged?",
            }
        )
        sender, subject, message, msg_id = parse_webhook_event(body)
        assert sender == "user@example.com"
        assert subject == "Billing question"

    def test_webhook_with_sender_field(self):
        body = json.dumps(
            {
                "sender": "customer@example.com",
                "subject": "Bug report",
                "body": "Feature X is broken",
            }
        )
        sender, subject, message, msg_id = parse_webhook_event(body)
        assert sender == "customer@example.com"

    def test_webhook_missing_email_raises(self):
        body = json.dumps({"subject": "Test", "message": "Content"})
        with pytest.raises(ValueError, match="email"):
            parse_webhook_event(body)

    def test_webhook_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_webhook_event("not json {{{")


# ---------------------------------------------------------------------------
# classify_ticket
# ---------------------------------------------------------------------------


def _mock_anthropic_response(classification_json: str) -> MagicMock:
    """Build a mock anthropic.messages.create() response."""
    response = MagicMock()
    response.content = [MagicMock(text=classification_json)]
    response.model = "claude-sonnet-4-20250514"
    response.usage.input_tokens = 80
    response.usage.output_tokens = 40
    return response


class TestClassifyTicket:
    @patch("src.ingest.anthropic.Anthropic")
    def test_critical_urgency_classification(self, mock_client_cls):
        classification_json = json.dumps(
            {
                "urgency": "critical",
                "category": "technical",
                "reasoning": "System is down",
                "keywords": ["down", "critical", "broken"],
            }
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            classification_json
        )
        mock_client_cls.return_value = mock_client

        result = classify_ticket("System is down", "Our production database is offline")
        assert result.success
        assert result.urgency == "critical"
        assert result.category == "technical"
        assert "System is down" in result.reasoning

    @patch("src.ingest.anthropic.Anthropic")
    def test_billing_category_classification(self, mock_client_cls):
        classification_json = json.dumps(
            {
                "urgency": "high",
                "category": "billing",
                "reasoning": "Customer charged incorrectly",
                "keywords": ["invoice", "charge", "refund"],
            }
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            classification_json
        )
        mock_client_cls.return_value = mock_client

        result = classify_ticket("Wrong charge", "I was charged $500 instead of $50")
        assert result.success
        assert result.category == "billing"

    @patch("src.ingest.anthropic.Anthropic")
    def test_feedback_classification(self, mock_client_cls):
        classification_json = json.dumps(
            {
                "urgency": "low",
                "category": "feedback",
                "reasoning": "Feature suggestion",
                "keywords": ["feature", "request", "would like"],
            }
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            classification_json
        )
        mock_client_cls.return_value = mock_client

        result = classify_ticket("Feature idea", "Would be nice to have dark mode")
        assert result.success
        assert result.urgency == "low"
        assert result.category == "feedback"

    @patch("src.ingest.anthropic.Anthropic")
    def test_invalid_json_response(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            "not json {{{"
        )
        mock_client_cls.return_value = mock_client

        result = classify_ticket("Subject", "Body")
        assert not result.success
        assert "Invalid JSON" in result.error

    @patch("src.ingest.anthropic.Anthropic")
    def test_api_error(self, mock_client_cls):
        import anthropic as anthropic_mod

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic_mod.APIError(
            message="rate limited",
            request=MagicMock(),
            body=None,
        )
        mock_client_cls.return_value = mock_client

        result = classify_ticket("Subject", "Body")
        assert not result.success
        assert "API error" in result.error

    @patch("src.ingest.anthropic.Anthropic")
    def test_invalid_urgency_defaults(self, mock_client_cls):
        classification_json = json.dumps(
            {
                "urgency": "INVALID",
                "category": "technical",
                "reasoning": "Test",
                "keywords": [],
            }
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(
            classification_json
        )
        mock_client_cls.return_value = mock_client

        result = classify_ticket("Test", "Test")
        assert result.success
        assert result.urgency == "medium"  # Falls back to default


# ---------------------------------------------------------------------------
# lambda_handler
# ---------------------------------------------------------------------------


class TestLambdaHandler:
    @patch("src.ingest.route_to_sns")
    @patch("src.ingest.save_ticket_to_dynamodb")
    @patch("src.ingest.classify_ticket")
    def test_ingest_ses_event(self, mock_classify, mock_save_db, mock_route_sns):
        mock_classify.return_value = ClassificationResult(
            success=True,
            urgency="high",
            category="technical",
            reasoning="Feature broken",
            keywords=["broken"],
            error=None,
            latency_ms=500,
        )
        mock_save_db.return_value = True
        mock_route_sns.return_value = True

        event = {
            "sender": "customer@example.com",
            "subject": "Login broken",
            "body": "Cannot login to account",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["success"]
        assert body["urgency"] == "high"
        assert body["category"] == "technical"
        assert body["ingestion_method"] == "ses"
        assert body["routed_to_sns"]

    @patch("src.ingest.route_to_sns")
    @patch("src.ingest.save_ticket_to_dynamodb")
    @patch("src.ingest.classify_ticket")
    def test_ingest_webhook_event(self, mock_classify, mock_save_db, mock_route_sns):
        mock_classify.return_value = ClassificationResult(
            success=True,
            urgency="medium",
            category="general",
            reasoning="General question",
            keywords=["help"],
            error=None,
            latency_ms=300,
        )
        mock_save_db.return_value = True
        mock_route_sns.return_value = True

        event = {
            "body": json.dumps(
                {
                    "email": "user@example.com",
                    "subject": "How to use feature X?",
                    "message": "I don't understand how to...",
                }
            )
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["ingestion_method"] == "webhook"

    @patch("src.ingest.route_to_sns")
    @patch("src.ingest.save_ticket_to_dynamodb")
    @patch("src.ingest.classify_ticket")
    def test_classification_failure_still_saves(
        self, mock_classify, mock_save_db, mock_route_sns
    ):
        mock_classify.return_value = ClassificationResult(
            success=False,
            urgency=None,
            category=None,
            reasoning=None,
            keywords=None,
            error="API error",
            latency_ms=200,
        )
        mock_save_db.return_value = True
        mock_route_sns.return_value = False

        event = {
            "sender": "customer@example.com",
            "subject": "Help",
            "body": "Problem",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert not body["success"]
        assert "API error" in body["error"]
        assert body["dynamodb_saved"]
        assert not body["routed_to_sns"]

    def test_missing_required_fields(self):
        event = {"subject": "Test"}  # Missing sender and body/message
        result = lambda_handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing required fields" in result["body"]
