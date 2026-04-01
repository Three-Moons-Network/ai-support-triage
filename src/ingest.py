"""
AI Support Triage — Ingest Handler

Receives customer emails via SES (inbound) or webhook (API Gateway).
Classifies urgency and category using Claude.
Routes to appropriate SNS topic.
Logs ticket to DynamoDB.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

import anthropic
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "512"))
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "support-tickets")
DYNAMODB_REGION = os.environ.get("AWS_REGION", "us-east-1")
SNS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Topic ARNs from environment
SNS_TOPICS = {
    "critical": os.environ.get("SNS_TOPIC_CRITICAL", ""),
    "high": os.environ.get("SNS_TOPIC_HIGH", ""),
    "medium": os.environ.get("SNS_TOPIC_MEDIUM", ""),
    "low": os.environ.get("SNS_TOPIC_LOW", ""),
}

CATEGORIES = {"billing", "technical", "general", "feedback"}
URGENCIES = {"critical", "high", "medium", "low"}

CLASSIFICATION_SCHEMA = """{
  "urgency": "critical|high|medium|low",
  "category": "billing|technical|general|feedback",
  "reasoning": "Brief explanation of classification",
  "keywords": ["comma", "separated", "keywords"]
}"""

SYSTEM_PROMPT = f"""You are an expert customer support triage agent. Classify incoming support tickets based on:

1. Urgency (critical/high/medium/low):
   - critical: System down, data loss, security breach, payment failed
   - high: Feature broken, significant impact, angry customer
   - medium: Minor bug, feature request, performance issue
   - low: General question, feedback, documentation request

2. Category (billing/technical/general/feedback):
   - billing: Invoices, pricing, subscriptions, payments
   - technical: Bugs, errors, integration issues
   - general: Account, onboarding, usage questions
   - feedback: Feature requests, suggestions, testimonials

Return ONLY valid JSON matching this schema:
{CLASSIFICATION_SCHEMA}

Analyze the email content carefully. Look for keywords indicating urgency (urgent, critical, down, broken) and category context."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SupportTicket:
    """Support ticket record for DynamoDB."""
    ticket_id: str
    sender_email: str
    subject: str
    message: str
    urgency: str
    category: str
    classification_reasoning: str
    keywords: list[str]
    created_at: str  # ISO 8601
    ingestion_method: str  # "ses" or "webhook"
    routing_status: str  # "routed" or "failed"
    error_message: str | None


@dataclass
class ClassificationResult:
    """Result of ticket classification."""
    success: bool
    urgency: str | None
    category: str | None
    reasoning: str | None
    keywords: list[str] | None
    error: str | None
    latency_ms: int


# ---------------------------------------------------------------------------
# AWS Clients
# ---------------------------------------------------------------------------

def get_dynamodb_client() -> boto3.client:
    """Get DynamoDB client."""
    return boto3.client("dynamodb", region_name=DYNAMODB_REGION)


def get_sns_client() -> boto3.client:
    """Get SNS client."""
    return boto3.client("sns", region_name=SNS_REGION)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def parse_ses_event(event: dict[str, Any]) -> tuple[str, str, str, str]:
    """
    Parse SES inbound event into (sender, subject, body, message_id).

    SES events require mail processing via SNS wrapper. For this template,
    we accept a simplified format with extracted fields.
    """
    # Expected format: event passed from SNS containing SES message
    sender = event.get("sender", "unknown@example.com")
    subject = event.get("subject", "(No subject)")
    body = event.get("body", "")
    message_id = event.get("messageId", str(uuid4()))

    if not body or not sender:
        raise ValueError("Missing required SES fields: sender, body")

    return sender, subject, body, message_id


def parse_webhook_event(body_str: str) -> tuple[str, str, str, str]:
    """Parse webhook POST body into (sender, subject, body, message_id)."""
    try:
        body = json.loads(body_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON body: {e}")

    sender = body.get("email") or body.get("sender")
    subject = body.get("subject", "(No subject)")
    message = body.get("message") or body.get("body")
    message_id = body.get("message_id") or str(uuid4())

    if not sender or not message:
        raise ValueError("Missing required fields: email/sender, message/body")

    return sender, subject, message, message_id


def classify_ticket(subject: str, body: str) -> ClassificationResult:
    """
    Classify a support ticket using Claude.

    Returns urgency, category, reasoning, and keywords.
    """
    client = anthropic.Anthropic()

    user_message = f"""Classify this support ticket:

Subject: {subject}

Message:
{body}
"""

    start = time.monotonic()

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        result_text = response.content[0].text

        # Parse JSON response
        try:
            data = json.loads(result_text)
        except json.JSONDecodeError as e:
            return ClassificationResult(
                success=False,
                urgency=None,
                category=None,
                reasoning=None,
                keywords=None,
                error=f"Invalid JSON from Claude: {str(e)}",
                latency_ms=latency_ms,
            )

        # Validate classifications
        urgency = data.get("urgency", "medium").lower()
        category = data.get("category", "general").lower()

        if urgency not in URGENCIES:
            urgency = "medium"
        if category not in CATEGORIES:
            category = "general"

        return ClassificationResult(
            success=True,
            urgency=urgency,
            category=category,
            reasoning=data.get("reasoning", ""),
            keywords=data.get("keywords", []),
            error=None,
            latency_ms=latency_ms,
        )

    except anthropic.APIError as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.error(f"Anthropic API error: {e}")
        return ClassificationResult(
            success=False,
            urgency=None,
            category=None,
            reasoning=None,
            keywords=None,
            error=f"Claude API error: {getattr(e, 'status_code', 'unknown')}",
            latency_ms=latency_ms,
        )


def save_ticket_to_dynamodb(ticket: SupportTicket) -> bool:
    """Save support ticket to DynamoDB."""
    dynamodb = get_dynamodb_client()

    item = {
        "ticket_id": {"S": ticket.ticket_id},
        "sender_email": {"S": ticket.sender_email},
        "subject": {"S": ticket.subject},
        "message": {"S": ticket.message},
        "urgency": {"S": ticket.urgency},
        "category": {"S": ticket.category},
        "classification_reasoning": {"S": ticket.classification_reasoning},
        "keywords": {"SS": ticket.keywords or ["none"]},
        "created_at": {"S": ticket.created_at},
        "ingestion_method": {"S": ticket.ingestion_method},
        "routing_status": {"S": ticket.routing_status},
    }

    if ticket.error_message:
        item["error_message"] = {"S": ticket.error_message}

    try:
        dynamodb.put_item(TableName=DYNAMODB_TABLE, Item=item)
        logger.info(f"Saved ticket {ticket.ticket_id} to DynamoDB")
        return True
    except ClientError as e:
        logger.error(f"DynamoDB save error: {e}")
        return False


def route_to_sns(ticket: SupportTicket) -> bool:
    """Publish ticket to appropriate SNS topic based on urgency."""
    if not SNS_TOPICS.get(ticket.urgency):
        logger.warning(f"No SNS topic configured for urgency: {ticket.urgency}")
        return False

    sns = get_sns_client()
    topic_arn = SNS_TOPICS[ticket.urgency]

    message = {
        "ticket_id": ticket.ticket_id,
        "sender_email": ticket.sender_email,
        "subject": ticket.subject,
        "message": ticket.message,
        "urgency": ticket.urgency,
        "category": ticket.category,
        "classification_reasoning": ticket.classification_reasoning,
        "keywords": ticket.keywords,
        "created_at": ticket.created_at,
    }

    try:
        sns.publish(
            TopicArn=topic_arn,
            Subject=f"[{ticket.urgency.upper()}] {ticket.subject}",
            Message=json.dumps(message, indent=2),
        )
        logger.info(f"Routed ticket {ticket.ticket_id} to {ticket.urgency} topic")
        return True
    except ClientError as e:
        logger.error(f"SNS publish error: {e}")
        return False


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context: Any) -> dict:
    """
    Lambda handler for support ticket ingestion.

    Accepts either:
    1. SES inbound event (from SNS)
    2. API Gateway webhook event

    Classifies ticket, saves to DynamoDB, routes to SNS topic by urgency.
    """
    logger.info("Processing support ticket")

    try:
        # Determine ingestion method and parse input
        ingestion_method = "unknown"
        sender = None
        subject = None
        message_body = None
        message_id = None

        # Check if this is an SES event (has email-like structure)
        if "sender" in event or "email" in event:
            ingestion_method = "ses"
            sender, subject, message_body, message_id = parse_ses_event(event)
        # Check if this is API Gateway webhook
        elif "body" in event and isinstance(event["body"], str):
            ingestion_method = "webhook"
            sender, subject, message_body, message_id = parse_webhook_event(event["body"])
        elif "body" in event and isinstance(event["body"], dict):
            ingestion_method = "webhook"
            body_dict = event["body"]
            sender = body_dict.get("email") or body_dict.get("sender")
            subject = body_dict.get("subject", "(No subject)")
            message_body = body_dict.get("message") or body_dict.get("body")
            message_id = body_dict.get("message_id") or str(uuid4())
        else:
            raise ValueError("Unrecognized event format")

        if not all([sender, message_body]):
            raise ValueError("Missing required fields: sender, message")

        logger.info(f"Ticket from {sender}", extra={"method": ingestion_method})

        # Classify ticket
        start = time.monotonic()
        classification = classify_ticket(subject, message_body)
        total_ms = int((time.monotonic() - start) * 1000)

        # Create ticket record
        ticket_id = str(uuid4())
        ticket = SupportTicket(
            ticket_id=ticket_id,
            sender_email=sender,
            subject=subject,
            message=message_body,
            urgency=classification.urgency or "medium",
            category=classification.category or "general",
            classification_reasoning=classification.reasoning or "",
            keywords=classification.keywords or [],
            created_at=datetime.utcnow().isoformat() + "Z",
            ingestion_method=ingestion_method,
            routing_status="failed",  # Will update if routing succeeds
            error_message=None if classification.success else classification.error,
        )

        # Save to DynamoDB
        db_saved = save_ticket_to_dynamodb(ticket)

        # Route to SNS
        routed = False
        if classification.success:
            routed = route_to_sns(ticket)
            if routed:
                ticket.routing_status = "routed"
                # Update routing status in DynamoDB
                dynamodb = get_dynamodb_client()
                try:
                    dynamodb.update_item(
                        TableName=DYNAMODB_TABLE,
                        Key={"ticket_id": {"S": ticket.ticket_id}},
                        UpdateExpression="SET routing_status = :status",
                        ExpressionAttributeValues={":status": {"S": "routed"}},
                    )
                except ClientError as e:
                    logger.error(f"Failed to update routing status: {e}")

        return {
            "statusCode": 200 if classification.success else 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "ticket_id": ticket_id,
                "sender_email": sender,
                "subject": subject,
                "success": classification.success,
                "urgency": ticket.urgency,
                "category": ticket.category,
                "classification_reasoning": classification.reasoning,
                "error": classification.error,
                "processing_time_ms": total_ms,
                "dynamodb_saved": db_saved,
                "routed_to_sns": routed,
                "ingestion_method": ingestion_method,
            }),
        }

    except (ValueError, KeyError) as e:
        logger.warning(f"Validation error: {e}")
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }

    except Exception as e:
        logger.exception("Unexpected error in ticket ingestion")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "Internal server error",
                "details": str(e),
            }),
        }
