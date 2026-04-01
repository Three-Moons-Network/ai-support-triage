###############################################################################
# AI Support Triage — Infrastructure
#
# Deploys:
#   - API Gateway HTTP API for webhook ingestion
#   - Lambda ingest function (classifies tickets)
#   - Lambda query function (ticket lookup/stats)
#   - DynamoDB table for tickets
#   - SNS topics per urgency (critical, high, medium, low)
#   - IAM roles with least-privilege policies
#   - CloudWatch log groups and alarms
###############################################################################

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "Three-Moons-Network"
    }
  }
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile name"
  type        = string
  default     = "default"
}

variable "project_name" {
  description = "Project identifier used in resource naming"
  type        = string
  default     = "ai-support-triage"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "uat", "prod"], var.environment)
    error_message = "Environment must be dev, uat, or prod."
  }
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude classification"
  type        = string
  sensitive   = true
}

variable "anthropic_model" {
  description = "Claude model to use for classification"
  type        = string
  default     = "claude-sonnet-4-20250514"
}

variable "max_tokens" {
  description = "Maximum output tokens per classification"
  type        = number
  default     = 512
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 256
}

variable "ingest_timeout" {
  description = "Ingest Lambda timeout in seconds"
  type        = number
  default     = 30
}

variable "query_timeout" {
  description = "Query Lambda timeout in seconds"
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 14
}

locals {
  prefix     = "${var.project_name}-${var.environment}"
  table_name = "${local.prefix}-tickets"
}

# ---------------------------------------------------------------------------
# DynamoDB — Support Tickets
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "tickets" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticket_id"

  attribute {
    name = "ticket_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  ttl {
    attribute_name = "expiration_time"
    enabled        = true
  }

  tags = {
    Name = local.table_name
  }
}

# ---------------------------------------------------------------------------
# SNS — Routing Topics by Urgency
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "critical" {
  name = "${local.prefix}-critical"
  tags = {
    Name    = "${local.prefix}-critical"
    Urgency = "critical"
  }
}

resource "aws_sns_topic" "high" {
  name = "${local.prefix}-high"
  tags = {
    Name    = "${local.prefix}-high"
    Urgency = "high"
  }
}

resource "aws_sns_topic" "medium" {
  name = "${local.prefix}-medium"
  tags = {
    Name    = "${local.prefix}-medium"
    Urgency = "medium"
  }
}

resource "aws_sns_topic" "low" {
  name = "${local.prefix}-low"
  tags = {
    Name    = "${local.prefix}-low"
    Urgency = "low"
  }
}

# ---------------------------------------------------------------------------
# IAM — Ingest Lambda
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest" {
  name               = "${local.prefix}-ingest-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "ingest_permissions" {
  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.ingest.arn}:*"]
  }

  # DynamoDB — write tickets
  statement {
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [aws_dynamodb_table.tickets.arn]
  }

  # SNS — publish to topics
  statement {
    actions = ["sns:Publish"]
    resources = [
      aws_sns_topic.critical.arn,
      aws_sns_topic.high.arn,
      aws_sns_topic.medium.arn,
      aws_sns_topic.low.arn,
    ]
  }

  # SSM Parameter Store — read API key
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.anthropic_api_key.arn]
  }
}

resource "aws_iam_role_policy" "ingest" {
  name   = "${local.prefix}-ingest-policy"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest_permissions.json
}

# ---------------------------------------------------------------------------
# IAM — Query Lambda
# ---------------------------------------------------------------------------

resource "aws_iam_role" "query" {
  name               = "${local.prefix}-query-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "query_permissions" {
  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.query.arn}:*"]
  }

  # DynamoDB — read only
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Scan",
      "dynamodb:Query",
    ]
    resources = [aws_dynamodb_table.tickets.arn]
  }
}

resource "aws_iam_role_policy" "query" {
  name   = "${local.prefix}-query-policy"
  role   = aws_iam_role.query.id
  policy = data.aws_iam_policy_document.query_permissions.json
}

# ---------------------------------------------------------------------------
# SSM Parameter Store — Anthropic API Key
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "anthropic_api_key" {
  name        = "/${var.project_name}/${var.environment}/anthropic-api-key"
  description = "Anthropic API key for ticket classification"
  type        = "SecureString"
  value       = var.anthropic_api_key

  tags = {
    Name = "${local.prefix}-anthropic-api-key"
  }
}

# ---------------------------------------------------------------------------
# CloudWatch Log Groups
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.prefix}-ingest"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "query" {
  name              = "/aws/lambda/${local.prefix}-query"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/apigateway/${local.prefix}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# Lambda — Ingest
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "ingest" {
  function_name = "${local.prefix}-ingest"
  description   = "Classify and route support tickets"
  runtime       = "python3.11"
  handler       = "ingest.lambda_handler"
  memory_size   = var.lambda_memory
  timeout       = var.ingest_timeout
  role          = aws_iam_role.ingest.arn

  filename         = "${path.module}/../dist/ingest.zip"
  source_code_hash = filebase64sha256("${path.module}/../dist/ingest.zip")

  environment {
    variables = {
      ENVIRONMENT        = var.environment
      DYNAMODB_TABLE     = aws_dynamodb_table.tickets.name
      AWS_REGION         = var.aws_region
      ANTHROPIC_MODEL    = var.anthropic_model
      MAX_TOKENS         = tostring(var.max_tokens)
      ANTHROPIC_API_KEY  = var.anthropic_api_key
      SNS_TOPIC_CRITICAL = aws_sns_topic.critical.arn
      SNS_TOPIC_HIGH     = aws_sns_topic.high.arn
      SNS_TOPIC_MEDIUM   = aws_sns_topic.medium.arn
      SNS_TOPIC_LOW      = aws_sns_topic.low.arn
      LOG_LEVEL          = var.environment == "prod" ? "WARNING" : "INFO"
    }
  }

  depends_on = [
    aws_iam_role_policy.ingest,
    aws_cloudwatch_log_group.ingest,
  ]
}

# ---------------------------------------------------------------------------
# Lambda — Query
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "query" {
  function_name = "${local.prefix}-query"
  description   = "Query API for support tickets"
  runtime       = "python3.11"
  handler       = "query.lambda_handler"
  memory_size   = 128
  timeout       = var.query_timeout
  role          = aws_iam_role.query.arn

  filename         = "${path.module}/../dist/query.zip"
  source_code_hash = filebase64sha256("${path.module}/../dist/query.zip")

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.tickets.name
      AWS_REGION     = var.aws_region
      ENVIRONMENT    = var.environment
      LOG_LEVEL      = var.environment == "prod" ? "WARNING" : "INFO"
    }
  }

  depends_on = [
    aws_iam_role_policy.query,
    aws_cloudwatch_log_group.query,
  ]
}

# ---------------------------------------------------------------------------
# API Gateway — HTTP API
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "main" {
  name          = "${local.prefix}-api"
  protocol_type = "HTTP"
  description   = "Support ticket ingestion and query API"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["POST", "GET", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization"]
    max_age       = 3600
  }
}

# Integration for ingest
resource "aws_apigatewayv2_integration" "ingest" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ingest.invoke_arn
  payload_format_version = "2.0"
}

# Integration for query
resource "aws_apigatewayv2_integration" "query" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.query.invoke_arn
  payload_format_version = "2.0"
}

# Routes
resource "aws_apigatewayv2_route" "post_ingest" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /tickets"
  target    = "integrations/${aws_apigatewayv2_integration.ingest.id}"
}

resource "aws_apigatewayv2_route" "get_tickets" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /tickets"
  target    = "integrations/${aws_apigatewayv2_integration.query.id}"
}

resource "aws_apigatewayv2_route" "get_ticket_by_id" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /tickets/{ticket_id}"
  target    = "integrations/${aws_apigatewayv2_integration.query.id}"
}

resource "aws_apigatewayv2_route" "get_stats" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /stats"
  target    = "integrations/${aws_apigatewayv2_integration.query.id}"
}

resource "aws_apigatewayv2_route" "get_search" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /search"
  target    = "integrations/${aws_apigatewayv2_integration.query.id}"
}

# Stage
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = 10
    throttling_burst_limit = 20
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gw.arn
    format = jsonencode({
      requestId = "$context.requestId"
      ip        = "$context.identity.sourceIp"
      method    = "$context.httpMethod"
      path      = "$context.path"
      status    = "$context.status"
      latency   = "$context.responseLatency"
    })
  }
}

# Lambda permissions
resource "aws_lambda_permission" "api_gw_ingest" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "api_gw_query" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.query.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# CloudWatch Alarms
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ingest_errors" {
  alarm_name          = "${local.prefix}-ingest-errors"
  alarm_description   = "Ingest Lambda error rate exceeded"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.ingest.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "ingest_duration" {
  alarm_name          = "${local.prefix}-ingest-duration"
  alarm_description   = "Ingest Lambda p99 duration exceeded threshold"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  extended_statistic  = "p99"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.ingest_timeout * 1000 * 0.8 # 80% of timeout
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.ingest.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "dynamodb_throttles" {
  alarm_name          = "${local.prefix}-dynamodb-throttles"
  alarm_description   = "DynamoDB write throttling detected"
  namespace           = "AWS/DynamoDB"
  metric_name         = "WriteThrottleEvents"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = aws_dynamodb_table.tickets.name
  }
}
