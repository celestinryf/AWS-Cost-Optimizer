# lambda/handler.py
"""
AWS Lambda handler for scheduled cost optimization runs.

Triggered by EventBridge on a schedule (daily/weekly).
Scans S3 buckets, scores recommendations, and optionally executes safe optimizations.

Environment Variables:
    EXECUTION_MODE: safe|standard|dry_run (default: dry_run)
    SNS_TOPIC_ARN: ARN for notifications (optional)
    S3_REPORT_BUCKET: Bucket to store reports (optional)
    MAX_ACTIONS: Maximum actions per run (default: 50)
    SLACK_WEBHOOK_URL: Slack webhook for notifications (optional)
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import boto3

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ScannerConfig
from scanner import S3CostScanner
from scoring import RiskScorer, SavingsCalculator
from executor import Executor, ExecutionConfig, ExecutionMode
from models import Recommendation, RecommendationType, RiskLevel


def get_config_from_env() -> dict:
    """Load configuration from environment variables."""
    return {
        "execution_mode": os.environ.get("EXECUTION_MODE", "dry_run"),
        "sns_topic_arn": os.environ.get("SNS_TOPIC_ARN"),
        "s3_report_bucket": os.environ.get("S3_REPORT_BUCKET"),
        "max_actions": int(os.environ.get("MAX_ACTIONS", "50")),
        "slack_webhook_url": os.environ.get("SLACK_WEBHOOK_URL"),
        "notify_on_savings_threshold": float(os.environ.get("NOTIFY_THRESHOLD", "10.0")),
    }


def handler(event: dict, context) -> dict:
    """
    Main Lambda handler.
    
    Args:
        event: EventBridge event or manual trigger payload
        context: Lambda context
        
    Returns:
        Execution summary
    """
    print(f"Starting cost optimization run at {datetime.now(timezone.utc).isoformat()}")
    
    config = get_config_from_env()
    print(f"Configuration: mode={config['execution_mode']}, max_actions={config['max_actions']}")
    
    try:
        # Phase 1: Scan
        print("Phase 1: Scanning S3 buckets...")
        scan_result = run_scan()
        
        if not scan_result["recommendations"]:
            print("No recommendations found. Exiting.")
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "No optimization opportunities found",
                    "buckets_scanned": scan_result["stats"]["buckets_scanned"],
                    "objects_scanned": scan_result["stats"]["objects_scanned"],
                })
            }
        
        print(f"Found {len(scan_result['recommendations'])} recommendations")
        
        # Phase 2: Score
        print("Phase 2: Scoring recommendations...")
        score_result = run_scoring(scan_result["recommendations"])
        
        print(f"Scoring complete: {score_result['summary']['safe_to_automate']} safe to automate")
        
        # Phase 3: Execute (if not dry_run)
        execution_result = None
        if config["execution_mode"] != "dry_run":
            print(f"Phase 3: Executing in {config['execution_mode']} mode...")
            execution_result = run_execution(
                scan_result["recommendations"],
                score_result["scores"],
                config
            )
            print(f"Execution complete: {execution_result['successful']} successful, {execution_result['failed']} failed")
        else:
            print("Phase 3: Dry-run mode - skipping execution")
        
        # Generate summary
        summary = generate_summary(scan_result, score_result, execution_result, config)
        
        # Store report
        if config["s3_report_bucket"]:
            store_report(summary, config["s3_report_bucket"])
        
        # Send notifications
        if should_notify(summary, config):
            send_notifications(summary, config)
        
        print(f"Run complete. Total savings potential: ${summary['total_monthly_savings']:.2f}/month")
        
        return {
            "statusCode": 200,
            "body": json.dumps(summary, default=str)
        }
        
    except Exception as e:
        error_msg = f"Cost optimization run failed: {str(e)}"
        print(f"ERROR: {error_msg}")
        
        # Send error notification
        if config.get("sns_topic_arn"):
            send_error_notification(error_msg, config)
        
        return {
            "statusCode": 500,
            "body": json.dumps({"error": error_msg})
        }


def run_scan() -> dict:
    """Run the S3 scanner."""
    scanner_config = ScannerConfig()
    scanner = S3CostScanner(scanner_config)
    
    recommendations = scanner.scan_all_buckets()
    report = scanner.generate_report()
    
    return report


def run_scoring(recommendations_data: list) -> dict:
    """Score recommendations by risk."""
    # Reconstruct Recommendation objects
    recommendations = []
    for r in recommendations_data:
        rec = Recommendation(
            id=r["id"],
            bucket=r["bucket"],
            key=r.get("key"),
            recommendation_type=RecommendationType(r["recommendation_type"]),
            risk_level=RiskLevel(r["risk_level"]),
            current_state=r["current_state"],
            recommended_action=r["recommended_action"],
            estimated_monthly_savings=r["estimated_monthly_savings"],
            size_bytes=r["size_bytes"],
            storage_class=r.get("storage_class"),
            reason=r.get("reason", ""),
        )
        if r.get("last_modified"):
            from datetime import datetime
            rec.last_modified = datetime.fromisoformat(r["last_modified"].replace("Z", "+00:00"))
        recommendations.append(rec)
    
    # Score
    scorer = RiskScorer()
    savings_calc = SavingsCalculator()
    
    scores = []
    savings = []
    
    for rec in recommendations:
        score = scorer.score_recommendation(rec)
        scores.append(score)
        savings.append(savings_calc.calculate_savings(rec))
    
    return {
        "summary": scorer.get_summary(),
        "scores": {s.recommendation_id: s for s in scores},
        "savings": savings_calc.calculate_total_savings(savings),
        "recommendations": recommendations,
    }


def run_execution(recommendations_data: list, risk_scores: dict, config: dict) -> dict:
    """Execute optimizations."""
    # Reconstruct recommendations
    recommendations = []
    for r in recommendations_data:
        rec = Recommendation(
            id=r["id"],
            bucket=r["bucket"],
            key=r.get("key"),
            recommendation_type=RecommendationType(r["recommendation_type"]),
            risk_level=RiskLevel(r["risk_level"]),
            current_state=r["current_state"],
            recommended_action=r["recommended_action"],
            estimated_monthly_savings=r["estimated_monthly_savings"],
            size_bytes=r["size_bytes"],
            storage_class=r.get("storage_class"),
            reason=r.get("reason", ""),
        )
        recommendations.append(rec)
    
    # Determine mode
    mode_map = {
        "safe": ExecutionMode.SAFE,
        "standard": ExecutionMode.STANDARD,
        "full": ExecutionMode.FULL,
        "dry_run": ExecutionMode.DRY_RUN,
    }
    mode = mode_map.get(config["execution_mode"], ExecutionMode.DRY_RUN)
    
    # Configure executor
    exec_config = ExecutionConfig(
        mode=mode,
        max_actions=config["max_actions"],
        max_failures=5,
        require_confirmation=False,  # No prompts in Lambda
    )
    
    # Lambda doesn't support interactive confirmation
    executor = Executor(
        config=exec_config,
        confirm_callback=lambda msg: False  # Decline all confirmations
    )
    
    # Execute
    summary = executor.execute(recommendations, risk_scores)
    
    return summary.to_dict()


def generate_summary(scan_result: dict, score_result: dict, execution_result: Optional[dict], config: dict) -> dict:
    """Generate comprehensive summary."""
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": config["execution_mode"],
        
        # Scan stats
        "buckets_scanned": scan_result["stats"]["buckets_scanned"],
        "objects_scanned": scan_result["stats"]["objects_scanned"],
        "total_size_gb": scan_result["stats"]["total_size_gb"],
        
        # Recommendations
        "total_recommendations": len(scan_result["recommendations"]),
        "safe_to_automate": score_result["summary"]["safe_to_automate"],
        "requires_approval": score_result["summary"]["requires_approval"],
        
        # Risk breakdown
        "by_risk_level": score_result["summary"]["by_risk_level"],
        
        # Savings
        "total_monthly_savings": score_result["savings"]["total_monthly_savings"],
        "total_annual_savings": score_result["savings"]["total_annual_savings"],
        
        # Execution (if performed)
        "execution": None,
    }
    
    if execution_result:
        summary["execution"] = {
            "batch_id": execution_result.get("batch_id"),
            "executed": execution_result.get("executed", 0),
            "successful": execution_result.get("successful", 0),
            "failed": execution_result.get("failed", 0),
            "skipped": execution_result.get("skipped", 0),
            "errors": execution_result.get("errors", [])[:5],  # First 5 errors
        }
    
    return summary


def should_notify(summary: dict, config: dict) -> bool:
    """Determine if we should send notifications."""
    # Always notify if there were execution errors
    if summary.get("execution") and summary["execution"].get("failed", 0) > 0:
        return True
    
    # Notify if savings exceed threshold
    if summary["total_monthly_savings"] >= config["notify_on_savings_threshold"]:
        return True
    
    return False


def send_notifications(summary: dict, config: dict):
    """Send notifications via configured channels."""
    # SNS
    if config.get("sns_topic_arn"):
        send_sns_notification(summary, config["sns_topic_arn"])
    
    # Slack
    if config.get("slack_webhook_url"):
        send_slack_notification(summary, config["slack_webhook_url"])


def send_sns_notification(summary: dict, topic_arn: str):
    """Send notification via SNS."""
    sns = boto3.client("sns")
    
    subject = f"AWS Cost Optimizer: ${summary['total_monthly_savings']:.2f}/mo savings identified"
    
    message = f"""
AWS Cost Optimizer Report
========================
Time: {summary['timestamp']}
Mode: {summary['mode']}

Scan Results:
- Buckets scanned: {summary['buckets_scanned']}
- Objects scanned: {summary['objects_scanned']:,}
- Total size: {summary['total_size_gb']:.2f} GB

Recommendations:
- Total: {summary['total_recommendations']}
- Safe to automate: {summary['safe_to_automate']}
- Requires approval: {summary['requires_approval']}

Risk Breakdown:
- Low: {summary['by_risk_level']['low']}
- Medium: {summary['by_risk_level']['medium']}
- High: {summary['by_risk_level']['high']}

Potential Savings:
- Monthly: ${summary['total_monthly_savings']:.2f}
- Annual: ${summary['total_annual_savings']:.2f}
"""
    
    if summary.get("execution"):
        exec_info = summary["execution"]
        message += f"""
Execution Results:
- Batch ID: {exec_info['batch_id'][:8]}...
- Successful: {exec_info['successful']}
- Failed: {exec_info['failed']}
- Skipped: {exec_info['skipped']}
"""
        if exec_info.get("errors"):
            message += f"\nErrors:\n"
            for err in exec_info["errors"]:
                message += f"  - {err}\n"
    
    sns.publish(
        TopicArn=topic_arn,
        Subject=subject,
        Message=message
    )
    
    print(f"SNS notification sent to {topic_arn}")


def send_slack_notification(summary: dict, webhook_url: str):
    """Send notification to Slack."""
    import urllib.request
    
    # Build Slack message
    color = "#36a64f" if summary.get("execution", {}).get("failed", 0) == 0 else "#ff0000"
    
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"💰 AWS Cost Optimizer Report"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Mode:* {summary['mode']}"},
                {"type": "mrkdwn", "text": f"*Buckets:* {summary['buckets_scanned']}"},
                {"type": "mrkdwn", "text": f"*Monthly Savings:* ${summary['total_monthly_savings']:.2f}"},
                {"type": "mrkdwn", "text": f"*Recommendations:* {summary['total_recommendations']}"},
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Low Risk:* {summary['by_risk_level']['low']}"},
                {"type": "mrkdwn", "text": f"*Medium Risk:* {summary['by_risk_level']['medium']}"},
                {"type": "mrkdwn", "text": f"*High Risk:* {summary['by_risk_level']['high']}"},
                {"type": "mrkdwn", "text": f"*Safe to Auto:* {summary['safe_to_automate']}"},
            ]
        },
    ]
    
    if summary.get("execution"):
        exec_info = summary["execution"]
        status = "✅" if exec_info["failed"] == 0 else "⚠️"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{status} *Execution:* {exec_info['successful']} successful, {exec_info['failed']} failed, {exec_info['skipped']} skipped"
            }
        })
    
    payload = {
        "attachments": [{
            "color": color,
            "blocks": blocks
        }]
    }
    
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    
    try:
        urllib.request.urlopen(req)
        print("Slack notification sent")
    except Exception as e:
        print(f"Failed to send Slack notification: {e}")


def send_error_notification(error_msg: str, config: dict):
    """Send error notification."""
    if config.get("sns_topic_arn"):
        sns = boto3.client("sns")
        sns.publish(
            TopicArn=config["sns_topic_arn"],
            Subject="AWS Cost Optimizer: Run Failed",
            Message=f"The cost optimization run failed with error:\n\n{error_msg}"
        )


def store_report(summary: dict, bucket: str):
    """Store report in S3."""
    s3 = boto3.client("s3")
    
    timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
    key = f"cost-optimizer-reports/{timestamp}/summary.json"
    
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(summary, indent=2, default=str),
        ContentType="application/json"
    )
    
    print(f"Report stored to s3://{bucket}/{key}")


# For local testing
if __name__ == "__main__":
    # Simulate Lambda invocation
    test_event = {"source": "local-test"}
    
    class MockContext:
        function_name = "cost-optimizer-test"
        memory_limit_in_mb = 512
        
    result = handler(test_event, MockContext())
    print(json.dumps(result, indent=2))