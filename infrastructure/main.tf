# infrastructure/main.tf
# AWS Cost Optimizer - Lambda Infrastructure
#
# Deploy with:
#   cd infrastructure
#   terraform init
#   terraform plan
#   terraform apply

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = "aws-cost-optimizer"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "execution_mode" {
  description = "Execution mode: dry_run, safe, standard, full"
  type        = string
  default     = "dry_run"
  
  validation {
    condition     = contains(["dry_run", "safe", "standard", "full"], var.execution_mode)
    error_message = "execution_mode must be one of: dry_run, safe, standard, full"
  }
}

variable "schedule_expression" {
  description = "CloudWatch Events schedule expression"
  type        = string
  default     = "rate(1 day)"  # Daily
  # Other options:
  # "rate(7 days)"           - Weekly
  # "cron(0 8 * * ? *)"      - Daily at 8 AM UTC
  # "cron(0 8 ? * MON *)"    - Weekly on Monday at 8 AM UTC
}

variable "max_actions" {
  description = "Maximum actions to execute per run"
  type        = number
  default     = 50
}

variable "notify_threshold" {
  description = "Send notification if savings exceed this amount ($/month)"
  type        = number
  default     = 10.0
}

variable "notification_email" {
  description = "Email address for notifications (optional)"
  type        = string
  default     = ""
}

variable "slack_webhook_url" {
  description = "Slack webhook URL for notifications (optional)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "enable_schedule" {
  description = "Enable scheduled execution"
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# -----------------------------------------------------------------------------
# S3 Bucket for Reports
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "reports" {
  bucket = "cost-optimizer-reports-${data.aws_caller_identity.current.account_id}-${var.environment}"
}

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id
  
  rule {
    id     = "expire-old-reports"
    status = "Enabled"
    
    expiration {
      days = 90
    }
    
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket = aws_s3_bucket.reports.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# SNS Topic for Notifications
# -----------------------------------------------------------------------------

resource "aws_sns_topic" "notifications" {
  name = "cost-optimizer-notifications-${var.environment}"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

# -----------------------------------------------------------------------------
# IAM Role for Lambda
# -----------------------------------------------------------------------------

resource "aws_iam_role" "lambda" {
  name = "cost-optimizer-lambda-${var.environment}"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# CloudWatch Logs
resource "aws_iam_role_policy" "lambda_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# S3 Read Access (for scanning)
resource "aws_iam_role_policy" "lambda_s3_read" {
  name = "s3-read"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:ListAllMyBuckets",
          "s3:GetBucketLocation",
          "s3:GetBucketLifecycleConfiguration",
          "s3:ListBucket",
          "s3:GetObject",
          "s3:HeadObject",
          "s3:GetObjectTagging",
          "s3:GetObjectRetention",
          "s3:GetObjectLegalHold",
          "s3:ListBucketMultipartUploads",
          "s3:ListMultipartUploadParts",
          "s3:ListBucketVersions"
        ]
        Resource = "*"
      }
    ]
  })
}

# S3 Write Access (for executing optimizations)
resource "aws_iam_role_policy" "lambda_s3_write" {
  name = "s3-write"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:CopyObject",
          "s3:DeleteObject",
          "s3:PutObjectTagging",
          "s3:AbortMultipartUpload",
          "s3:PutLifecycleConfiguration",
          "s3:RestoreObject"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# S3 Write Access for Reports Bucket
resource "aws_iam_role_policy" "lambda_s3_reports" {
  name = "s3-reports"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject"
        ]
        Resource = "${aws_s3_bucket.reports.arn}/*"
      }
    ]
  })
}

# SNS Publish
resource "aws_iam_role_policy" "lambda_sns" {
  name = "sns-publish"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.notifications.arn
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Lambda Function
# -----------------------------------------------------------------------------

# Package the Lambda code
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/.."
  output_path = "${path.module}/lambda_package.zip"
  
  excludes = [
    "infrastructure",
    "reports",
    "scripts",
    ".git",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "venv",
    ".env"
  ]
}

resource "aws_lambda_function" "optimizer" {
  filename         = data.archive_file.lambda.output_path
  function_name    = "cost-optimizer-${var.environment}"
  role             = aws_iam_role.lambda.arn
  handler          = "lambda_function.handler.handler"
  source_code_hash = data.archive_file.lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 900  # 15 minutes
  memory_size      = 512
  
  environment {
    variables = {
      EXECUTION_MODE     = var.execution_mode
      SNS_TOPIC_ARN      = aws_sns_topic.notifications.arn
      S3_REPORT_BUCKET   = aws_s3_bucket.reports.id
      MAX_ACTIONS        = tostring(var.max_actions)
      NOTIFY_THRESHOLD   = tostring(var.notify_threshold)
      SLACK_WEBHOOK_URL  = var.slack_webhook_url
    }
  }
  
  layers = [
    "arn:aws:lambda:${data.aws_region.current.name}:770693421928:layer:Klayers-p311-boto3:12"
  ]
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.optimizer.function_name}"
  retention_in_days = 30
}

# -----------------------------------------------------------------------------
# EventBridge Schedule
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "schedule" {
  count = var.enable_schedule ? 1 : 0
  
  name                = "cost-optimizer-schedule-${var.environment}"
  description         = "Trigger cost optimizer on schedule"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "lambda" {
  count = var.enable_schedule ? 1 : 0
  
  rule      = aws_cloudwatch_event_rule.schedule[0].name
  target_id = "cost-optimizer"
  arn       = aws_lambda_function.optimizer.arn
}

resource "aws_lambda_permission" "eventbridge" {
  count = var.enable_schedule ? 1 : 0
  
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.optimizer.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule[0].arn
}

# -----------------------------------------------------------------------------
# CloudWatch Dashboard
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "CostOptimizer-${var.environment}"
  
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Lambda Invocations"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.optimizer.function_name],
            [".", "Errors", ".", "."],
          ]
          period = 86400
          stat   = "Sum"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Lambda Duration"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.optimizer.function_name, { stat = "Average" }],
            ["...", { stat = "Maximum" }],
          ]
          period = 86400
        }
      },
      {
        type   = "log"
        x      = 0
        y      = 6
        width  = 24
        height = 6
        properties = {
          title  = "Recent Logs"
          region = data.aws_region.current.name
          query  = "SOURCE '${aws_cloudwatch_log_group.lambda.name}' | fields @timestamp, @message | sort @timestamp desc | limit 50"
        }
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# CloudWatch Alarms
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "cost-optimizer-errors-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 86400  # 1 day
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Cost optimizer Lambda function errors"
  
  dimensions = {
    FunctionName = aws_lambda_function.optimizer.function_name
  }
  
  alarm_actions = [aws_sns_topic.notifications.arn]
  ok_actions    = [aws_sns_topic.notifications.arn]
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.optimizer.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.optimizer.arn
}

output "reports_bucket" {
  description = "S3 bucket for reports"
  value       = aws_s3_bucket.reports.id
}

output "sns_topic_arn" {
  description = "SNS topic ARN for notifications"
  value       = aws_sns_topic.notifications.arn
}

output "dashboard_url" {
  description = "CloudWatch dashboard URL"
  value       = "https://${data.aws_region.current.name}.console.aws.amazon.com/cloudwatch/home?region=${data.aws_region.current.name}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "invoke_command" {
  description = "AWS CLI command to manually invoke the function"
  value       = "aws lambda invoke --function-name ${aws_lambda_function.optimizer.function_name} --payload '{}' response.json"
}
