output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "api_id" {
  description = "API Gateway ID"
  value       = aws_apigatewayv2_api.main.id
}

output "ingest_endpoint" {
  description = "Ingest endpoint: POST /tickets"
  value       = "${aws_apigatewayv2_api.main.api_endpoint}/tickets"
}

output "query_tickets_endpoint" {
  description = "Query all tickets: GET /tickets"
  value       = "${aws_apigatewayv2_api.main.api_endpoint}/tickets"
}

output "stats_endpoint" {
  description = "Statistics endpoint: GET /stats"
  value       = "${aws_apigatewayv2_api.main.api_endpoint}/stats"
}

output "search_endpoint" {
  description = "Search endpoint: GET /search?q=keyword"
  value       = "${aws_apigatewayv2_api.main.api_endpoint}/search"
}

output "ingest_function_name" {
  description = "Ingest Lambda function name"
  value       = aws_lambda_function.ingest.function_name
}

output "ingest_function_arn" {
  description = "Ingest Lambda function ARN"
  value       = aws_lambda_function.ingest.arn
}

output "query_function_name" {
  description = "Query Lambda function name"
  value       = aws_lambda_function.query.function_name
}

output "query_function_arn" {
  description = "Query Lambda function ARN"
  value       = aws_lambda_function.query.arn
}

output "dynamodb_table_name" {
  description = "DynamoDB table name for tickets"
  value       = aws_dynamodb_table.tickets.name
}

output "sns_topic_critical" {
  description = "SNS topic ARN for critical tickets"
  value       = aws_sns_topic.critical.arn
}

output "sns_topic_high" {
  description = "SNS topic ARN for high-urgency tickets"
  value       = aws_sns_topic.high.arn
}

output "sns_topic_medium" {
  description = "SNS topic ARN for medium-urgency tickets"
  value       = aws_sns_topic.medium.arn
}

output "sns_topic_low" {
  description = "SNS topic ARN for low-urgency tickets"
  value       = aws_sns_topic.low.arn
}

output "cloudwatch_log_group_ingest" {
  description = "Ingest Lambda CloudWatch log group"
  value       = aws_cloudwatch_log_group.ingest.name
}

output "cloudwatch_log_group_query" {
  description = "Query Lambda CloudWatch log group"
  value       = aws_cloudwatch_log_group.query.name
}
