#!/usr/bin/env python3
"""
AWS S3 Cost Optimization Tool

Usage:
    python main.py scan              # Scan and identify optimizations
    python main.py score             # Score recommendations by risk
    python main.py dry-run           # Validate what would happen
    python main.py report            # Generate full report
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import ScannerConfig
from scanner import S3CostScanner
from scoring import RiskScorer, SavingsCalculator
from executor import DryRunExecutor, PreExecutionValidator
from models import RiskLevel


console = Console()


def cmd_scan(args):
    """Run the scanner to identify optimization opportunities."""
    console.print("\n[bold blue]═══ AWS S3 Cost Optimizer - Scan Mode ═══[/bold blue]\n")
    
    config = ScannerConfig()
    scanner = S3CostScanner(config)
    
    # Run scan
    recommendations = scanner.scan_all_buckets()
    
    # Print summary
    scanner.print_summary()
    
    # Save results
    report = scanner.generate_report()
    output_file = Path("reports/scan_results.json")
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    console.print(f"\n[dim]Results saved to: {output_file}[/dim]")
    
    if recommendations:
        console.print("\n[yellow]Next step:[/yellow] Run 'python main.py score' to analyze risk levels\n")
    
    return 0


def cmd_score(args):
    """Score recommendations by risk and calculate savings."""
    console.print("\n[bold blue]═══ AWS S3 Cost Optimizer - Score Mode ═══[/bold blue]\n")
    
    # Load scan results
    scan_file = Path("reports/scan_results.json")
    if not scan_file.exists():
        console.print("[red]No scan results found. Run 'python main.py scan' first.[/red]")
        return 1
    
    with open(scan_file) as f:
        scan_data = json.load(f)
    
    recommendations_data = scan_data.get("recommendations", [])
    if not recommendations_data:
        console.print("[yellow]No recommendations to score.[/yellow]")
        return 0
    
    console.print(f"Scoring [green]{len(recommendations_data)}[/green] recommendations...\n")
    
    # Convert back to Recommendation objects
    from models import Recommendation, RecommendationType, RiskLevel
    from datetime import datetime
    
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
            rec.last_modified = datetime.fromisoformat(r["last_modified"].replace("Z", "+00:00"))
        recommendations.append(rec)
    
    # Score each recommendation
    scorer = RiskScorer()
    savings_calc = SavingsCalculator()
    
    scores = []
    savings = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing...", total=len(recommendations))
        
        for rec in recommendations:
            score = scorer.score_recommendation(rec)
            scores.append(score)
            
            savings_estimate = savings_calc.calculate_savings(rec)
            savings.append(savings_estimate)
            
            progress.advance(task)
    
    # Print risk summary
    summary = scorer.get_summary()
    
    risk_table = Table(title="Risk Analysis Summary")
    risk_table.add_column("Category", style="cyan")
    risk_table.add_column("Count", style="green", justify="right")
    
    risk_table.add_row("Total Recommendations", str(summary["total_scored"]))
    risk_table.add_row("Low Risk (automatable)", str(summary["by_risk_level"]["low"]))
    risk_table.add_row("Medium Risk (review)", str(summary["by_risk_level"]["medium"]))
    risk_table.add_row("High Risk (approval needed)", str(summary["by_risk_level"]["high"]))
    risk_table.add_row("", "")
    risk_table.add_row("Safe to Automate", f"[green]{summary['safe_to_automate']}[/green]")
    risk_table.add_row("Requires Approval", f"[yellow]{summary['requires_approval']}[/yellow]")
    
    console.print(risk_table)
    
    # Print savings summary
    savings_summary = savings_calc.calculate_total_savings(savings)
    
    console.print()
    savings_panel = Panel(
        f"[bold green]${savings_summary['total_monthly_savings']:.2f}[/bold green] / month\n"
        f"[green]${savings_summary['total_annual_savings']:.2f}[/green] / year\n\n"
        f"One-time transition costs: [yellow]${savings_summary['total_transition_costs']:.2f}[/yellow]\n"
        f"High confidence estimates: {savings_summary['high_confidence_count']}/{savings_summary['count']}",
        title="Estimated Savings",
        border_style="green",
    )
    console.print(savings_panel)
    
    # Print detailed breakdown
    console.print("\n[bold]Recommendations by Risk Level[/bold]\n")
    
    # Group by risk level
    low_risk = [s for s in scores if s.risk_level == RiskLevel.LOW]
    med_risk = [s for s in scores if s.risk_level == RiskLevel.MEDIUM]
    high_risk = [s for s in scores if s.risk_level == RiskLevel.HIGH]
    
    if low_risk:
        console.print(f"[green]✓ LOW RISK ({len(low_risk)} items)[/green] - Safe to automate")
        for score in low_risk[:5]:  # Show first 5
            rec = next(r for r in recommendations if r.id == score.recommendation_id)
            console.print(f"  • {rec.bucket}/{rec.key or ''}: {rec.recommended_action[:60]}")
        if len(low_risk) > 5:
            console.print(f"  ... and {len(low_risk) - 5} more")
    
    if med_risk:
        console.print(f"\n[yellow]⚠ MEDIUM RISK ({len(med_risk)} items)[/yellow] - Review recommended")
        for score in med_risk[:5]:
            rec = next(r for r in recommendations if r.id == score.recommendation_id)
            console.print(f"  • {rec.bucket}/{rec.key or ''}: {rec.recommended_action[:60]}")
        if len(med_risk) > 5:
            console.print(f"  ... and {len(med_risk) - 5} more")
    
    if high_risk:
        console.print(f"\n[red]✗ HIGH RISK ({len(high_risk)} items)[/red] - Manual approval required")
        for score in high_risk[:5]:
            rec = next(r for r in recommendations if r.id == score.recommendation_id)
            console.print(f"  • {rec.bucket}/{rec.key or ''}: {rec.recommended_action[:60]}")
        if len(high_risk) > 5:
            console.print(f"  ... and {len(high_risk) - 5} more")
    
    # Save scored results
    scored_output = {
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "savings": savings_summary,
        "scores": [s.to_dict() for s in scores],
        "savings_details": [s.to_dict() for s in savings],
    }
    
    output_file = Path("reports/scored_results.json")
    with open(output_file, "w") as f:
        json.dump(scored_output, f, indent=2)
    
    console.print(f"\n[dim]Scores saved to: {output_file}[/dim]")
    console.print("\n[yellow]Next step:[/yellow] Run 'python main.py dry-run' to validate changes\n")
    
    return 0


def cmd_dry_run(args):
    """Run dry-run validation on recommendations."""
    console.print("\n[bold blue]═══ AWS S3 Cost Optimizer - Dry Run Mode ═══[/bold blue]\n")
    
    # Load scan and score results
    scan_file = Path("reports/scan_results.json")
    score_file = Path("reports/scored_results.json")
    
    if not scan_file.exists():
        console.print("[red]No scan results found. Run 'python main.py scan' first.[/red]")
        return 1
    
    if not score_file.exists():
        console.print("[red]No scores found. Run 'python main.py score' first.[/red]")
        return 1
    
    with open(scan_file) as f:
        scan_data = json.load(f)
    
    with open(score_file) as f:
        score_data = json.load(f)
    
    # Reconstruct recommendations
    from models import Recommendation, RecommendationType, RiskLevel
    from scoring import RiskScore, ConfidenceLevel
    
    recommendations = []
    for r in scan_data.get("recommendations", []):
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
    
    # Reconstruct risk scores
    risk_scores = {}
    for s in score_data.get("scores", []):
        risk_scores[s["recommendation_id"]] = RiskScore(
            recommendation_id=s["recommendation_id"],
            risk_score=s["risk_score"],
            confidence_score=s["confidence_score"],
            impact_score=s["impact_score"],
            risk_level=RiskLevel(s["risk_level"]),
            confidence_level=ConfidenceLevel(s["confidence_level"]),
            safe_to_automate=s["safe_to_automate"],
            requires_approval=s["requires_approval"],
            factors=s["factors"],
            execution_recommendation=s["execution_recommendation"],
        )
    
    console.print(f"Validating [green]{len(recommendations)}[/green] recommendations...\n")
    console.print("[dim]This checks if changes can be made without actually making them.[/dim]\n")
    
    # Run dry-run
    executor = DryRunExecutor()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Validating...", total=None)
        results = executor.run(
            recommendations, 
            risk_scores, 
            skip_high_risk=not args.include_high_risk
        )
        progress.remove_task(task)
    
    # Print results
    report = executor.generate_report()
    summary = report["summary"]
    
    result_table = Table(title="Dry Run Results")
    result_table.add_column("Status", style="cyan")
    result_table.add_column("Count", justify="right")
    
    result_table.add_row(
        "[green]Would Succeed[/green]", 
        str(summary["would_succeed"])
    )
    result_table.add_row(
        "[red]Would Fail[/red]", 
        str(summary["would_fail"])
    )
    result_table.add_row(
        "[yellow]Skipped[/yellow]", 
        str(summary["skipped"])
    )
    result_table.add_row(
        "[red]Errors[/red]", 
        str(summary["errors"])
    )
    
    console.print(result_table)
    
    # Show details for failures
    if report["needs_attention"]:
        console.print("\n[red]Items that would fail:[/red]")
        for item in report["needs_attention"]:
            console.print(f"  ✗ {item['would_affect'].get('bucket')}/{item['would_affect'].get('key', '')}")
            console.print(f"    Reason: {item['failure_reason']}")
    
    # Show what's ready
    if report["ready_to_execute"]:
        console.print(f"\n[green]Ready to execute: {len(report['ready_to_execute'])} actions[/green]")
        if not args.quiet:
            for item in report["ready_to_execute"][:10]:
                console.print(f"  ✓ {item['action_description'][:70]}")
            if len(report["ready_to_execute"]) > 10:
                console.print(f"  ... and {len(report['ready_to_execute']) - 10} more")
    
    # Save report
    report_path = executor.save_report()
    console.print(f"\n[dim]Full report saved to: {report_path}[/dim]")
    
    if summary["would_succeed"] > 0:
        console.print("\n[yellow]Next step:[/yellow] Run 'python main.py execute' to apply changes (Phase 3)\n")
    
    return 0


def cmd_report(args):
    """Generate a comprehensive report."""
    console.print("\n[bold blue]═══ AWS S3 Cost Optimizer - Full Report ═══[/bold blue]\n")
    
    # Load all data
    scan_file = Path("reports/scan_results.json")
    score_file = Path("reports/scored_results.json")
    
    if not scan_file.exists():
        console.print("[red]No scan results found. Run 'python main.py scan' first.[/red]")
        return 1
    
    with open(scan_file) as f:
        scan_data = json.load(f)
    
    score_data = None
    if score_file.exists():
        with open(score_file) as f:
            score_data = json.load(f)
    
    # Generate summary
    console.print(Panel(
        f"[bold]Scan Summary[/bold]\n\n"
        f"Buckets Scanned: {scan_data['stats']['buckets_scanned']}\n"
        f"Objects Scanned: {scan_data['stats']['objects_scanned']:,}\n"
        f"Total Size: {scan_data['stats']['total_size_gb']:.2f} GB\n"
        f"Recommendations: {scan_data['stats']['total_recommendations']}\n"
        f"Estimated Savings: [green]${scan_data['stats']['estimated_monthly_savings']:.2f}/month[/green]",
        title="Overview",
        border_style="blue",
    ))
    
    if score_data:
        console.print(Panel(
            f"[bold]Risk Analysis[/bold]\n\n"
            f"Low Risk: {score_data['summary']['by_risk_level']['low']}\n"
            f"Medium Risk: {score_data['summary']['by_risk_level']['medium']}\n"
            f"High Risk: {score_data['summary']['by_risk_level']['high']}\n\n"
            f"Safe to Automate: [green]{score_data['summary']['safe_to_automate']}[/green]\n"
            f"Requires Approval: [yellow]{score_data['summary']['requires_approval']}[/yellow]",
            title="Risk Assessment",
            border_style="yellow",
        ))
        
        console.print(Panel(
            f"[bold]Savings Estimate[/bold]\n\n"
            f"Monthly Savings: [green]${score_data['savings']['total_monthly_savings']:.2f}[/green]\n"
            f"Annual Savings: [green]${score_data['savings']['total_annual_savings']:.2f}[/green]\n"
            f"Transition Costs: ${score_data['savings']['total_transition_costs']:.2f}\n"
            f"High Confidence: {score_data['savings']['high_confidence_count']}/{score_data['savings']['count']}",
            title="Cost Impact",
            border_style="green",
        ))
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="AWS S3 Cost Optimization Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  scan      Scan S3 buckets for optimization opportunities
  score     Analyze risk levels and calculate savings
  dry-run   Validate changes without executing
  report    Generate comprehensive summary report

Examples:
  python main.py scan
  python main.py score
  python main.py dry-run --include-high-risk
  python main.py report
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Scan for optimizations")
    
    # Score command
    score_parser = subparsers.add_parser("score", help="Score by risk")
    
    # Dry-run command
    dry_run_parser = subparsers.add_parser("dry-run", help="Validate changes")
    dry_run_parser.add_argument(
        "--include-high-risk",
        action="store_true",
        help="Include high-risk items in validation"
    )
    dry_run_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Minimal output"
    )
    
    # Report command
    report_parser = subparsers.add_parser("report", help="Generate report")
    
    args = parser.parse_args()
    
    if args.command == "scan":
        return cmd_scan(args)
    elif args.command == "score":
        return cmd_score(args)
    elif args.command == "dry-run":
        return cmd_dry_run(args)
    elif args.command == "report":
        return cmd_report(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())