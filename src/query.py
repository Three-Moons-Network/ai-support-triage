"""
AI Support Triage — Query Handler

API endpoint for querying support tickets.
Provides ticket lookup, search, and statistics.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import parse_qs

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "support-tickets")
DYNAMODB_REGION = os.environ.get("AWS_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# AWS Clients
# ---------------------------------------------------------------------------

def get_dynamodb_client() -> boto3.client:
    """Get DynamoDB client."""
    return boto3.client("dynamodb", region_name=DYNAMODB_REGION)


# ---------------------------------------------------------------------------
# Query operations
# ---------------------------------------------------------------------------

def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    """Fetch a single ticket by ID."""
    dynamodb = get_dynamodb_client()

    try:
        response = dynamodb.get_item(
            TableName=DYNAMODB_TABLE,
            Key={"ticket_id": {"S": ticket_id}},
        )

        if "Item" not in response:
            return None

        item = response["Item"]
        return {
            "ticket_id": item["ticket_id"]["S"],
            "sender_email": item["sender_email"]["S"],
            "subject": item["subject"]["S"],
            "message": item["message"]["S"],
            "urgency": item["urgency"]["S"],
            "category": item["category"]["S"],
            "classification_reasoning": item.get("classification_reasoning", {}).get("S", ""),
            "keywords": item.get("keywords", {}).get("SS", []),
            "created_at": item["created_at"]["S"],
            "ingestion_method": item.get("ingestion_method", {}).get("S", "unknown"),
            "routing_status": item.get("routing_status", {}).get("S", "unknown"),
            "error_message": item.get("error_message", {}).get("S"),
        }

    except ClientError as e:
        logger.error(f"DynamoDB get error: {e}")
        return None


def list_tickets(limit: int = 50, urgency_filter: str | None = None) -> list[dict[str, Any]]:
    """
    List all tickets with optional urgency filter.

    Returns most recent first (scan order varies, but we sort by created_at).
    """
    dynamodb = get_dynamodb_client()

    try:
        response = dynamodb.scan(
            TableName=DYNAMODB_TABLE,
            Limit=limit,
        )

        tickets = []
        for item in response.get("Items", []):
            ticket = {
                "ticket_id": item["ticket_id"]["S"],
                "sender_email": item["sender_email"]["S"],
                "subject": item["subject"]["S"],
                "urgency": item["urgency"]["S"],
                "category": item["category"]["S"],
                "created_at": item["created_at"]["S"],
                "routing_status": item.get("routing_status", {}).get("S", "unknown"),
            }

            # Filter by urgency if specified
            if urgency_filter and ticket["urgency"] != urgency_filter:
                continue

            tickets.append(ticket)

        # Sort by created_at descending (most recent first)
        tickets.sort(key=lambda t: t["created_at"], reverse=True)

        return tickets[:limit]

    except ClientError as e:
        logger.error(f"DynamoDB scan error: {e}")
        return []


def get_statistics() -> dict[str, Any]:
    """Get ticket statistics: count by urgency and category."""
    dynamodb = get_dynamodb_client()

    try:
        response = dynamodb.scan(TableName=DYNAMODB_TABLE)

        items = response.get("Items", [])

        stats = {
            "total_tickets": len(items),
            "by_urgency": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "by_category": {"billing": 0, "technical": 0, "general": 0, "feedback": 0},
            "by_routing_status": {"routed": 0, "failed": 0},
            "by_method": {"ses": 0, "webhook": 0},
        }

        for item in items:
            urgency = item.get("urgency", {}).get("S", "unknown")
            if urgency in stats["by_urgency"]:
                stats["by_urgency"][urgency] += 1

            category = item.get("category", {}).get("S", "unknown")
            if category in stats["by_category"]:
                stats["by_category"][category] += 1

            routing = item.get("routing_status", {}).get("S", "unknown")
            if routing in stats["by_routing_status"]:
                stats["by_routing_status"][routing] += 1

            method = item.get("ingestion_method", {}).get("S", "unknown")
            if method in stats["by_method"]:
                stats["by_method"][method] += 1

        return stats

    except ClientError as e:
        logger.error(f"DynamoDB scan error: {e}")
        return {"error": str(e)}


def search_tickets(keyword: str, limit: int = 50) -> list[dict[str, Any]]:
    """
    Search tickets by keyword in subject or message (simple text search).

    This does a full scan - in production, use DynamoDB GSI or Elasticsearch.
    """
    dynamodb = get_dynamodb_client()

    try:
        response = dynamodb.scan(TableName=DYNAMODB_TABLE, Limit=limit * 3)

        tickets = []
        keyword_lower = keyword.lower()

        for item in response.get("Items", []):
            subject = item.get("subject", {}).get("S", "").lower()
            message = item.get("message", {}).get("S", "").lower()

            if keyword_lower in subject or keyword_lower in message:
                ticket = {
                    "ticket_id": item["ticket_id"]["S"],
                    "sender_email": item["sender_email"]["S"],
                    "subject": item["subject"]["S"],
                    "urgency": item["urgency"]["S"],
                    "category": item["category"]["S"],
                    "created_at": item["created_at"]["S"],
                }
                tickets.append(ticket)

        # Sort by created_at descending
        tickets.sort(key=lambda t: t["created_at"], reverse=True)
        return tickets[:limit]

    except ClientError as e:
        logger.error(f"DynamoDB scan error: {e}")
        return []


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context: Any) -> dict:
    """
    Lambda handler for query API endpoints.

    Routes:
      GET /tickets              - List all tickets
      GET /tickets?urgency=high - Filter by urgency
      GET /tickets/{ticket_id}  - Get single ticket
      GET /stats                - Ticket statistics
      GET /search?q=keyword     - Search tickets
    """
    logger.info("Query API request", extra={"path": event.get("rawPath"), "method": event.get("requestContext", {}).get("http", {}).get("method")})

    try:
        path = event.get("rawPath", "")
        method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
        query_string = event.get("rawQueryString", "")

        # Parse query parameters
        query_params = {}
        if query_string:
            params = parse_qs(query_string)
            query_params = {k: v[0] if v else None for k, v in params.items()}

        # Route handlers
        if path == "/tickets" and method == "GET":
            limit = int(query_params.get("limit", 50))
            urgency = query_params.get("urgency")

            tickets = list_tickets(limit=limit, urgency_filter=urgency)
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "count": len(tickets),
                    "tickets": tickets,
                }),
            }

        elif path == "/stats" and method == "GET":
            stats = get_statistics()
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(stats),
            }

        elif path.startswith("/tickets/") and method == "GET":
            ticket_id = path.split("/")[-1]
            ticket = get_ticket(ticket_id)

            if not ticket:
                return {
                    "statusCode": 404,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"error": "Ticket not found"}),
                }

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(ticket),
            }

        elif path == "/search" and method == "GET":
            keyword = query_params.get("q") or query_params.get("query")
            if not keyword:
                return {
                    "statusCode": 400,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"error": "Missing search query parameter 'q'"}),
                }

            limit = int(query_params.get("limit", 50))
            tickets = search_tickets(keyword, limit=limit)
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "query": keyword,
                    "count": len(tickets),
                    "tickets": tickets,
                }),
            }

        else:
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "error": "Not found",
                    "available_routes": [
                        "GET /tickets",
                        "GET /tickets?urgency=high",
                        "GET /tickets/{ticket_id}",
                        "GET /stats",
                        "GET /search?q=keyword",
                    ],
                }),
            }

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }

    except Exception as e:
        logger.exception("Unexpected error in query handler")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "Internal server error",
                "details": str(e),
            }),
        }
