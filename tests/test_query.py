"""
Tests for the AI Support Triage query handler.

Uses mocking to avoid real DynamoDB calls during CI.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


from src.query import (
    get_statistics,
    get_ticket,
    lambda_handler,
    list_tickets,
    search_tickets,
)


# ---------------------------------------------------------------------------
# get_ticket
# ---------------------------------------------------------------------------


class TestGetTicket:
    @patch("src.query.get_dynamodb_client")
    def test_ticket_found(self, mock_get_client):
        mock_dynamodb = MagicMock()
        mock_get_client.return_value = mock_dynamodb

        mock_dynamodb.get_item.return_value = {
            "Item": {
                "ticket_id": {"S": "ticket-123"},
                "sender_email": {"S": "user@example.com"},
                "subject": {"S": "Cannot login"},
                "message": {"S": "I can't log in"},
                "urgency": {"S": "high"},
                "category": {"S": "technical"},
                "created_at": {"S": "2024-01-15T10:30:00Z"},
            }
        }

        ticket = get_ticket("ticket-123")
        assert ticket is not None
        assert ticket["ticket_id"] == "ticket-123"
        assert ticket["urgency"] == "high"

    @patch("src.query.get_dynamodb_client")
    def test_ticket_not_found(self, mock_get_client):
        mock_dynamodb = MagicMock()
        mock_get_client.return_value = mock_dynamodb
        mock_dynamodb.get_item.return_value = {}

        ticket = get_ticket("nonexistent")
        assert ticket is None


# ---------------------------------------------------------------------------
# list_tickets
# ---------------------------------------------------------------------------


class TestListTickets:
    @patch("src.query.get_dynamodb_client")
    def test_list_all_tickets(self, mock_get_client):
        mock_dynamodb = MagicMock()
        mock_get_client.return_value = mock_dynamodb

        mock_dynamodb.scan.return_value = {
            "Items": [
                {
                    "ticket_id": {"S": "ticket-1"},
                    "sender_email": {"S": "user1@example.com"},
                    "subject": {"S": "Issue 1"},
                    "urgency": {"S": "high"},
                    "category": {"S": "technical"},
                    "created_at": {"S": "2024-01-15T10:00:00Z"},
                    "routing_status": {"S": "routed"},
                },
                {
                    "ticket_id": {"S": "ticket-2"},
                    "sender_email": {"S": "user2@example.com"},
                    "subject": {"S": "Issue 2"},
                    "urgency": {"S": "low"},
                    "category": {"S": "general"},
                    "created_at": {"S": "2024-01-15T11:00:00Z"},
                    "routing_status": {"S": "routed"},
                },
            ]
        }

        tickets = list_tickets(limit=50)
        assert len(tickets) == 2
        # Should be sorted by created_at descending
        assert tickets[0]["created_at"] > tickets[1]["created_at"]

    @patch("src.query.get_dynamodb_client")
    def test_filter_by_urgency(self, mock_get_client):
        mock_dynamodb = MagicMock()
        mock_get_client.return_value = mock_dynamodb

        mock_dynamodb.scan.return_value = {
            "Items": [
                {
                    "ticket_id": {"S": "ticket-1"},
                    "sender_email": {"S": "user1@example.com"},
                    "subject": {"S": "Critical issue"},
                    "urgency": {"S": "critical"},
                    "category": {"S": "technical"},
                    "created_at": {"S": "2024-01-15T10:00:00Z"},
                    "routing_status": {"S": "routed"},
                },
                {
                    "ticket_id": {"S": "ticket-2"},
                    "sender_email": {"S": "user2@example.com"},
                    "subject": {"S": "Low issue"},
                    "urgency": {"S": "low"},
                    "category": {"S": "feedback"},
                    "created_at": {"S": "2024-01-15T11:00:00Z"},
                    "routing_status": {"S": "routed"},
                },
            ]
        }

        tickets = list_tickets(limit=50, urgency_filter="critical")
        assert len(tickets) == 1
        assert tickets[0]["urgency"] == "critical"


# ---------------------------------------------------------------------------
# get_statistics
# ---------------------------------------------------------------------------


class TestGetStatistics:
    @patch("src.query.get_dynamodb_client")
    def test_statistics_aggregation(self, mock_get_client):
        mock_dynamodb = MagicMock()
        mock_get_client.return_value = mock_dynamodb

        mock_dynamodb.scan.return_value = {
            "Items": [
                {
                    "ticket_id": {"S": "t1"},
                    "urgency": {"S": "critical"},
                    "category": {"S": "technical"},
                    "routing_status": {"S": "routed"},
                    "ingestion_method": {"S": "ses"},
                },
                {
                    "ticket_id": {"S": "t2"},
                    "urgency": {"S": "high"},
                    "category": {"S": "billing"},
                    "routing_status": {"S": "routed"},
                    "ingestion_method": {"S": "webhook"},
                },
                {
                    "ticket_id": {"S": "t3"},
                    "urgency": {"S": "low"},
                    "category": {"S": "feedback"},
                    "routing_status": {"S": "failed"},
                    "ingestion_method": {"S": "webhook"},
                },
            ]
        }

        stats = get_statistics()
        assert stats["total_tickets"] == 3
        assert stats["by_urgency"]["critical"] == 1
        assert stats["by_urgency"]["high"] == 1
        assert stats["by_urgency"]["low"] == 1
        assert stats["by_category"]["technical"] == 1
        assert stats["by_category"]["billing"] == 1
        assert stats["by_category"]["feedback"] == 1
        assert stats["by_routing_status"]["routed"] == 2
        assert stats["by_routing_status"]["failed"] == 1
        assert stats["by_method"]["ses"] == 1
        assert stats["by_method"]["webhook"] == 2


# ---------------------------------------------------------------------------
# search_tickets
# ---------------------------------------------------------------------------


class TestSearchTickets:
    @patch("src.query.get_dynamodb_client")
    def test_search_by_keyword(self, mock_get_client):
        mock_dynamodb = MagicMock()
        mock_get_client.return_value = mock_dynamodb

        mock_dynamodb.scan.return_value = {
            "Items": [
                {
                    "ticket_id": {"S": "t1"},
                    "sender_email": {"S": "user1@example.com"},
                    "subject": {"S": "Login problem"},
                    "message": {"S": "Cannot login"},
                    "urgency": {"S": "high"},
                    "category": {"S": "technical"},
                    "created_at": {"S": "2024-01-15T10:00:00Z"},
                },
                {
                    "ticket_id": {"S": "t2"},
                    "sender_email": {"S": "user2@example.com"},
                    "subject": {"S": "Billing issue"},
                    "message": {"S": "Wrong charge"},
                    "urgency": {"S": "medium"},
                    "category": {"S": "billing"},
                    "created_at": {"S": "2024-01-15T11:00:00Z"},
                },
            ]
        }

        tickets = search_tickets("login", limit=50)
        assert len(tickets) == 1
        assert "login" in tickets[0]["subject"].lower()


# ---------------------------------------------------------------------------
# lambda_handler
# ---------------------------------------------------------------------------


class TestLambdaHandler:
    @patch("src.query.list_tickets")
    def test_list_tickets_endpoint(self, mock_list):
        mock_list.return_value = [
            {
                "ticket_id": "t1",
                "sender_email": "user1@example.com",
                "subject": "Issue 1",
                "urgency": "high",
                "category": "technical",
                "created_at": "2024-01-15T10:00:00Z",
                "routing_status": "routed",
            }
        ]

        event = {
            "rawPath": "/tickets",
            "requestContext": {"http": {"method": "GET"}},
            "rawQueryString": "",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["count"] == 1

    @patch("src.query.list_tickets")
    def test_list_tickets_with_urgency_filter(self, mock_list):
        mock_list.return_value = [
            {
                "ticket_id": "t1",
                "sender_email": "user1@example.com",
                "subject": "Critical issue",
                "urgency": "critical",
                "category": "technical",
                "created_at": "2024-01-15T10:00:00Z",
                "routing_status": "routed",
            }
        ]

        event = {
            "rawPath": "/tickets",
            "requestContext": {"http": {"method": "GET"}},
            "rawQueryString": "urgency=critical",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["count"] == 1
        mock_list.assert_called_once_with(limit=50, urgency_filter="critical")

    @patch("src.query.get_ticket")
    def test_get_single_ticket(self, mock_get):
        mock_get.return_value = {
            "ticket_id": "t1",
            "sender_email": "user1@example.com",
            "subject": "Issue",
            "message": "Details",
            "urgency": "high",
            "category": "technical",
            "created_at": "2024-01-15T10:00:00Z",
        }

        event = {
            "rawPath": "/tickets/t1",
            "requestContext": {"http": {"method": "GET"}},
            "rawQueryString": "",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["ticket_id"] == "t1"

    @patch("src.query.get_ticket")
    def test_get_ticket_not_found(self, mock_get):
        mock_get.return_value = None

        event = {
            "rawPath": "/tickets/nonexistent",
            "requestContext": {"http": {"method": "GET"}},
            "rawQueryString": "",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 404

    @patch("src.query.get_statistics")
    def test_stats_endpoint(self, mock_stats):
        mock_stats.return_value = {
            "total_tickets": 10,
            "by_urgency": {"critical": 2, "high": 3, "medium": 4, "low": 1},
            "by_category": {"technical": 5, "billing": 3, "general": 2, "feedback": 0},
        }

        event = {
            "rawPath": "/stats",
            "requestContext": {"http": {"method": "GET"}},
            "rawQueryString": "",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["total_tickets"] == 10

    @patch("src.query.search_tickets")
    def test_search_endpoint(self, mock_search):
        mock_search.return_value = [
            {
                "ticket_id": "t1",
                "sender_email": "user@example.com",
                "subject": "Login issue",
                "urgency": "high",
                "category": "technical",
                "created_at": "2024-01-15T10:00:00Z",
            }
        ]

        event = {
            "rawPath": "/search",
            "requestContext": {"http": {"method": "GET"}},
            "rawQueryString": "q=login",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["query"] == "login"

    def test_search_missing_query(self):
        event = {
            "rawPath": "/search",
            "requestContext": {"http": {"method": "GET"}},
            "rawQueryString": "",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 400
        assert "Missing search query" in result["body"]

    def test_not_found_endpoint(self):
        event = {
            "rawPath": "/invalid",
            "requestContext": {"http": {"method": "GET"}},
            "rawQueryString": "",
        }

        result = lambda_handler(event, None)
        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert "available_routes" in body
