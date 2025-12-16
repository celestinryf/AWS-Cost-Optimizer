#!/usr/bin/env python3
# scripts/test_lambda_local.py
"""
Test the Lambda handler locally before deploying.

Usage:
    python scripts/test_lambda_local.py [--mode MODE]
    
Options:
    --mode MODE    Execution mode: dry_run, safe, standard, full (default: dry_run)

Examples:
    python scripts/test_lambda_local.py
    python scripts/test_lambda_local.py --mode safe
"""

import argparse
import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Test Lambda handler locally")
    parser.add_argument(
        "--mode",
        choices=["dry_run", "safe", "standard", "full"],
        default="dry_run",
        help="Execution mode (default: dry_run)"
    )
    parser.add_argument(
        "--max-actions",
        type=int,
        default=10,
        help="Maximum actions to execute (default: 10)"
    )
    args = parser.parse_args()
    
    # Set environment variables
    os.environ["EXECUTION_MODE"] = args.mode
    os.environ["MAX_ACTIONS"] = str(args.max_actions)
    os.environ["NOTIFY_THRESHOLD"] = "1000"  # High threshold to avoid notifications
    
    print("=" * 60)
    print("Local Lambda Test")
    print("=" * 60)
    print(f"Mode: {args.mode}")
    print(f"Max Actions: {args.max_actions}")
    print()
    
    # Import handler
    from lambda_function.handler import handler
    
    # Create mock event and context
    event = {
        "source": "local-test",
        "detail-type": "Scheduled Event",
    }
    
    class MockContext:
        function_name = "cost-optimizer-local"
        memory_limit_in_mb = 512
        invoked_function_arn = "arn:aws:lambda:us-east-1:123456789:function:test"
        aws_request_id = "test-request-id"
        
        def get_remaining_time_in_millis(self):
            return 900000  # 15 minutes
    
    # Run handler
    try:
        result = handler(event, MockContext())
        
        print()
        print("=" * 60)
        print("Result")
        print("=" * 60)
        print(json.dumps(result, indent=2, default=str))
        
        # Parse and display summary
        if result.get("statusCode") == 200:
            body = json.loads(result.get("body", "{}"))
            
            print()
            print("=" * 60)
            print("Summary")
            print("=" * 60)
            print(f"Buckets Scanned: {body.get('buckets_scanned', 'N/A')}")
            print(f"Objects Scanned: {body.get('objects_scanned', 'N/A'):,}")
            print(f"Recommendations: {body.get('total_recommendations', 'N/A')}")
            print(f"Monthly Savings: ${body.get('total_monthly_savings', 0):.2f}")
            
            if body.get("execution"):
                exec_info = body["execution"]
                print()
                print("Execution:")
                print(f"  Successful: {exec_info.get('successful', 0)}")
                print(f"  Failed: {exec_info.get('failed', 0)}")
                print(f"  Skipped: {exec_info.get('skipped', 0)}")
        
        return 0
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())