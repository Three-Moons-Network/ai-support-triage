# AI Support Triage

Production-ready starter for intelligent customer support ticket triage using AWS and Claude. Automatically receives customer emails/webhooks, classifies urgency and category via Claude, routes to appropriate SNS topic, and provides a query API for ticket lookup and statistics.

Built as a reference implementation by [Three Moons Network](https://threemoonsnetwork.net) — an AI consulting practice helping small businesses automate with production-grade systems.

## Architecture

```
                  ┌──────────────────────────────────────────┐
                  │            AWS Cloud                     │
                  │                                          │
  Customer Email  │  API Gateway                            │
  or Webhook ───▶ │     │                                   │
                  │     ▼ (POST /tickets)                    │
                  │  Ingest Lambda                          │
                  │     │                                   │
                  │     ├──▶ Claude API (Classification)    │
                  │     │                                   │
                  │     ├──▶ DynamoDB (Store Ticket)        │
                  │     │                                   │
                  │     └──▶ SNS Topics (Route by Urgency)  │
                  │          ├─ Critical                    │
                  │          ├─ High                        │
                  │          ├─ Medium                      │
                  │          └─ Low                         │
                  │                                          │
                  │  Query API (GET /tickets, /stats, etc.) │
                  │     └──▶ DynamoDB (Query & Stats)       │
                  │                                          │
                  │  CloudWatch (Logs + Alarms)             │
                  │                                          │
                  └──────────────────────────────────────────┘
```

## What It Does

Submit a customer support request via webhook or email. The system automatically:

1. **Classifies** the ticket using Claude:
   - **Urgency:** critical, high, medium, low
   - **Category:** billing, technical, general, feedback

2. **Routes** to SNS topic based on urgency (critical/high/medium/low)

3. **Stores** ticket in DynamoDB with classification results

4. **Queries** via API for ticket lookup, search, and statistics

### Classification Example

**Input:**
```json
{
  "email": "customer@example.com",
  "subject": "Our database is down — site is offline",
  "message": "Production database went offline at 2pm. We've lost customer orders. This is critical!"
}
```

**Output (DynamoDB + SNS):**
```json
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "sender_email": "customer@example.com",
  "subject": "Our database is down — site is offline",
  "urgency": "critical",
  "category": "technical",
  "classification_reasoning": "System down, lost orders, explicit 'critical' language",
  "keywords": ["database", "offline", "critical", "production"],
  "created_at": "2024-01-15T14:30:00Z",
  "routing_status": "routed"
}
```

Routes to SNS critical topic for immediate on-call response.

## API Endpoints

### Ingest Endpoint

**POST /tickets** — Submit a support ticket

```bash
curl -X POST https://api-id.execute-api.us-east-1.amazonaws.com/tickets \
  -H "Content-Type: application/json" \
  -d '{
    "email": "customer@example.com",
    "subject": "Billing question",
    "message": "Why was I charged $500?"
  }'
```

**Response:**
```json
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "urgency": "high",
  "category": "billing",
  "routed_to_sns": true,
  "processing_time_ms": 1240
}
```

### Query Endpoints

**GET /tickets** — List all tickets (most recent first)

```bash
curl https://api-id.execute-api.us-east-1.amazonaws.com/tickets
```

**GET /tickets?urgency=critical** — Filter by urgency

```bash
curl 'https://api-id.execute-api.us-east-1.amazonaws.com/tickets?urgency=critical'
```

**GET /tickets/{ticket_id}** — Get single ticket

```bash
curl https://api-id.execute-api.us-east-1.amazonaws.com/tickets/550e8400-e29b-41d4-a716-446655440000
```

**GET /stats** — Ticket statistics

```bash
curl https://api-id.execute-api.us-east-1.amazonaws.com/stats
```

**Response:**
```json
{
  "total_tickets": 47,
  "by_urgency": {"critical": 2, "high": 8, "medium": 23, "low": 14},
  "by_category": {"technical": 18, "billing": 15, "general": 12, "feedback": 2},
  "by_routing_status": {"routed": 45, "failed": 2},
  "by_method": {"webhook": 35, "ses": 12}
}
```

**GET /search?q=keyword** — Search tickets by subject/message

```bash
curl 'https://api-id.execute-api.us-east-1.amazonaws.com/search?q=login'
```

## Quick Start

### Prerequisites

- AWS account with CLI configured
- Terraform >= 1.5
- Python 3.11+
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

### 1. Clone and configure

```bash
git clone git@github.com:Three-Moons-Network/ai-support-triage.git
cd ai-support-triage
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform.tfvars with your API key and region
```

### 2. Build Lambda packages

```bash
./scripts/deploy.sh
```

### 3. Deploy infrastructure

```bash
cd terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Terraform outputs the API endpoint URLs. Test the ingest endpoint:

```bash
API_URL=$(terraform output -raw ingest_endpoint)

curl -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "support@acme.com",
    "subject": "Cannot login",
    "message": "Multiple customers report login failures on mobile"
  }'
```

Check statistics:

```bash
STATS_URL=$(terraform output -raw stats_endpoint)
curl "$STATS_URL"
```

### 4. Tear down

```bash
terraform destroy
```

## Project Structure

```
├── src/
│   ├── ingest.py            # Ingest handler — classify, route, store
│   └── query.py             # Query handler — ticket lookup, search, stats
├── tests/
│   ├── test_ingest.py       # Ingest tests with mocked Anthropic/DynamoDB
│   └── test_query.py        # Query tests with mocked DynamoDB
├── terraform/
│   ├── main.tf              # All infra: API GW, Lambda, DynamoDB, SNS, IAM, CW
│   ├── outputs.tf           # API endpoints, function ARNs, topic ARNs
│   ├── backend.tf           # Remote state config (commented for local)
│   └── terraform.tfvars.example
├── scripts/
│   └── deploy.sh            # Build ingest.zip and query.zip
├── .github/workflows/
│   └── ci.yml               # Test, lint, TF validate, package
├── requirements.txt         # Runtime: anthropic, boto3
└── requirements-dev.txt     # Dev: pytest, ruff, moto
```

## Infrastructure Details

| Resource | Purpose |
|----------|---------|
| API Gateway HTTP API | Webhook endpoint for ingest + query routes |
| Lambda Ingest | Receives ticket, classifies with Claude, routes |
| Lambda Query | Provides REST API for ticket lookup/search/stats |
| DynamoDB Table | Stores tickets with urgency, category, keywords |
| SNS Topics (4) | One per urgency level for routing (critical/high/medium/low) |
| CloudWatch Logs | Ingest + query function logs + API access logs |
| CloudWatch Alarms | Errors > 5/5min, p99 latency > 80% timeout, DynamoDB throttles |
| IAM Roles | Least-privilege for Lambda (CloudWatch, DynamoDB, SNS, SSM) |

All resources tagged with Project, Environment, ManagedBy, and Owner for cost tracking and governance.

## CI/CD

GitHub Actions runs on every push/PR to `main`:

- **Test** — `pytest` with mocked Anthropic/DynamoDB/SNS
- **Lint** — `ruff format --check` + `ruff check`
- **Terraform Validate** — `fmt -check`, `init -backend=false`, `validate`
- **Package** — Builds `ingest.zip` and `query.zip` on main merges

## Customization

**Change urgency levels:**

Edit `URGENCIES` in `src/ingest.py` and add corresponding SNS topics in `terraform/main.tf`.

**Change classification categories:**

Update `CATEGORIES` in `src/ingest.py` and adjust the system prompt for Claude.

**Customize routing logic:**

Modify `route_to_sns()` in `src/ingest.py` to fan out to multiple topics, HTTP webhooks, or other services.

**Connect to team messaging:**

Subscribe SNS topics to Slack, Teams, or Datadog for instant notifications.

**Add SES for email routing:**

Integrate AWS SES to send tickets directly to support queues (modify `route_to_sns()`).

## Cost Estimate

For low-volume support (< 500 tickets/month):

| Component | Estimated Monthly Cost |
|-----------|----------------------|
| Lambda Ingest | ~$0 (free tier: 1M requests, 400K GB-seconds) |
| Lambda Query | ~$0 (free tier) |
| API Gateway | ~$0 (free tier: 1M HTTP calls) |
| DynamoDB | ~$0 (free tier: 25 write/read units/sec, 25GB storage) |
| SNS | ~$0 (free tier: first 1,000 notifications) |
| CloudWatch | ~$0.50 (log storage) |
| Anthropic API | Usage-based (~$3/M input tokens, ~$15/M output tokens for Sonnet) |

**Total infrastructure: effectively free.** Main cost is Anthropic API usage based on ticket volume.

## Local Development

```bash
# Set up
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/
ruff format src/ tests/

# Test classification locally (requires API key)
export ANTHROPIC_API_KEY="sk-ant-..."
python -c "
from src.ingest import classify_ticket
result = classify_ticket('Cannot login', 'I lost access to my account')
print(result)
"
```

## Troubleshooting

**Tickets not routing to SNS:**
- Check SNS topic ARNs in Lambda environment variables
- Verify Lambda execution role has `sns:Publish` permission
- Check CloudWatch logs for routing errors

**Claude classification not working:**
- Verify Anthropic API key in SSM Parameter Store
- Check CloudWatch logs for API errors
- Increase `max_tokens` if response is truncated

**API returns 404:**
- Verify API Gateway routes are deployed (check outputs)
- Check HTTP method (POST for /tickets, GET for queries)
- Verify request path matches (e.g., `/tickets` not `/ticket`)

**Lambda timeouts:**
- Increase `ingest_timeout` (Claude inference can be slow)
- Check CloudWatch for slow requests
- Consider increasing Lambda memory for better CPU

## License

MIT

## Author

Charles Harvey ([linuxlsr](https://github.com/linuxlsr)) — [Three Moons Network LLC](https://threemoonsnetwork.net)
