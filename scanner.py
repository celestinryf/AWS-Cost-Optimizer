#!/usr/bin/env python3
"""
AWS S3 Cost Optimization Scanner

Scans S3 buckets and identifies cost optimization opportunities.
Outputs recommendations as JSON for later processing.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import ScannerConfig
from models import Recommendation, RiskLevel
from analyzers import (
    StorageClassAnalyzer,
    AccessPatternAnalyzer,
    LifecycleAnalyzer,
    MultipartUploadAnalyzer,
)


console = Console()


class S3CostScanner:
    """Main scanner class that orchestrates all analyzers."""
    
    def __init__(self, config: Optional[ScannerConfig] = None):
        self.config = config or ScannerConfig()
        self.s3 = boto3.client("s3", region_name=self.config.aws_region)
        
        # Initialize analyzers
        self.storage_analyzer = StorageClassAnalyzer(self.config)
        self.access_analyzer = AccessPatternAnalyzer(self.config)
        self.lifecycle_analyzer = LifecycleAnalyzer(self.config)
        self.multipart_analyzer = MultipartUploadAnalyzer(self.config)
        
        self.recommendations: list[Recommendation] = []
        self.stats = {
            "buckets_scanned": 0,
            "objects_scanned": 0,
            "total_size_scanned": 0,
            "errors": [],
        }
    
    def scan_all_buckets(self) -> list[Recommendation]:
        """Scan all accessible S3 buckets."""
        console.print("\n[bold blue]AWS S3 Cost Optimization Scanner[/bold blue]\n")
        
        try:
            response = self.s3.list_buckets()
            buckets = response.get("Buckets", [])
        except ClientError as e:
            console.print(f"[red]Error listing buckets: {e}[/red]")
            return []
        
        console.print(f"Found [green]{len(buckets)}[/green] buckets\n")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for bucket in buckets:
                bucket_name = bucket["Name"]
                
                # Skip system buckets
                if any(bucket_name.startswith(p) for p in self.config.skip_bucket_prefixes):
                    continue
                
                task = progress.add_task(f"Scanning {bucket_name}...", total=None)
                self._scan_bucket(bucket_name)
                progress.remove_task(task)
        
        return self.recommendations
    
    def _scan_bucket(self, bucket_name: str) -> None:
        """Scan a single bucket for optimization opportunities."""
        try:
            # Get bucket region
            try:
                location = self.s3.get_bucket_location(Bucket=bucket_name)
                region = location.get("LocationConstraint") or "us-east-1"
            except ClientError:
                region = "unknown"
            
            # Get lifecycle configuration
            lifecycle_rules = None
            try:
                lifecycle = self.s3.get_bucket_lifecycle_configuration(Bucket=bucket_name)
                lifecycle_rules = lifecycle.get("Rules", [])
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchLifecycleConfiguration":
                    self.stats["errors"].append(f"{bucket_name}: {e}")
            
            # Scan objects
            objects = []
            total_size = 0
            paginator = self.s3.get_paginator("list_objects_v2")
            
            try:
                for page in paginator.paginate(Bucket=bucket_name):
                    for obj in page.get("Contents", []):
                        objects.append(obj)
                        total_size += obj.get("Size", 0)
                        self.stats["objects_scanned"] += 1
                        
                        # Analyze each object
                        self._analyze_object(bucket_name, obj)
                        
                        # Respect scan limit
                        if (
                            self.config.max_objects_per_bucket 
                            and len(objects) >= self.config.max_objects_per_bucket
                        ):
                            break
                    
                    if (
                        self.config.max_objects_per_bucket 
                        and len(objects) >= self.config.max_objects_per_bucket
                    ):
                        break
            except ClientError as e:
                self.stats["errors"].append(f"{bucket_name}: {e}")
                return
            
            self.stats["total_size_scanned"] += total_size
            self.stats["buckets_scanned"] += 1
            
            # Analyze bucket-level things
            for rec in self.lifecycle_analyzer.analyze(
                bucket_name, lifecycle_rules, total_size, len(objects)
            ):
                self.recommendations.append(rec)
            
            # Analyze access patterns by prefix
            for rec in self.access_analyzer.analyze_prefix_patterns(bucket_name, objects):
                self.recommendations.append(rec)
            
            # Check for incomplete multipart uploads
            self._scan_multipart_uploads(bucket_name)
            
        except ClientError as e:
            self.stats["errors"].append(f"{bucket_name}: {e}")
    
    def _analyze_object(self, bucket: str, obj: dict) -> None:
        """Run all object-level analyzers."""
        now = datetime.now(timezone.utc)
        last_modified = obj.get("LastModified")
        
        if last_modified:
            days_since_modified = (now - last_modified).days
        else:
            days_since_modified = 0
        
        # Storage class analysis
        for rec in self.storage_analyzer.analyze(bucket, obj, days_since_modified):
            self.recommendations.append(rec)
        
        # Access pattern analysis
        for rec in self.access_analyzer.analyze(bucket, obj, days_since_modified):
            self.recommendations.append(rec)
    
    def _scan_multipart_uploads(self, bucket_name: str) -> None:
        """Scan for incomplete multipart uploads."""
        try:
            response = self.s3.list_multipart_uploads(Bucket=bucket_name)
            uploads = response.get("Uploads", [])
            
            for rec in self.multipart_analyzer.analyze(bucket_name, uploads):
                self.recommendations.append(rec)
                
        except ClientError as e:
            if e.response["Error"]["Code"] != "AccessDenied":
                self.stats["errors"].append(f"{bucket_name} multipart: {e}")
    
    def generate_report(self) -> dict:
        """Generate a summary report."""
        total_savings = sum(r.estimated_monthly_savings for r in self.recommendations)
        
        by_risk = {
            RiskLevel.LOW: [],
            RiskLevel.MEDIUM: [],
            RiskLevel.HIGH: [],
        }
        for rec in self.recommendations:
            by_risk[rec.risk_level].append(rec)
        
        return {
            "scan_timestamp": datetime.now(timezone.utc).isoformat(),
            "stats": {
                "buckets_scanned": self.stats["buckets_scanned"],
                "objects_scanned": self.stats["objects_scanned"],
                "total_size_gb": round(self.stats["total_size_scanned"] / (1024**3), 2),
                "total_recommendations": len(self.recommendations),
                "estimated_monthly_savings": round(total_savings, 2),
            },
            "summary": {
                "low_risk": len(by_risk[RiskLevel.LOW]),
                "medium_risk": len(by_risk[RiskLevel.MEDIUM]),
                "high_risk": len(by_risk[RiskLevel.HIGH]),
            },
            "recommendations": [r.to_dict() for r in self.recommendations],
            "errors": self.stats["errors"],
        }
    
    def print_summary(self) -> None:
        """Print a summary table to console."""
        total_savings = sum(r.estimated_monthly_savings for r in self.recommendations)
        
        console.print("\n[bold]Scan Complete[/bold]\n")
        
        # Stats table
        stats_table = Table(title="Scan Statistics")
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="green")
        
        stats_table.add_row("Buckets scanned", str(self.stats["buckets_scanned"]))
        stats_table.add_row("Objects scanned", f"{self.stats['objects_scanned']:,}")
        stats_table.add_row(
            "Total size scanned", 
            f"{self.stats['total_size_scanned'] / (1024**3):.2f} GB"
        )
        stats_table.add_row("Recommendations", str(len(self.recommendations)))
        stats_table.add_row(
            "Est. monthly savings", 
            f"[bold green]${total_savings:.2f}[/bold green]"
        )
        
        console.print(stats_table)
        
        # Top recommendations
        if self.recommendations:
            console.print("\n[bold]Top Recommendations[/bold]\n")
            
            rec_table = Table()
            rec_table.add_column("Risk", style="cyan", width=8)
            rec_table.add_column("Bucket", style="blue")
            rec_table.add_column("Action", style="white")
            rec_table.add_column("Savings/mo", style="green", justify="right")
            
            # Sort by savings, show top 10
            sorted_recs = sorted(
                self.recommendations, 
                key=lambda r: r.estimated_monthly_savings, 
                reverse=True
            )[:10]
            
            for rec in sorted_recs:
                risk_color = {
                    RiskLevel.LOW: "green",
                    RiskLevel.MEDIUM: "yellow", 
                    RiskLevel.HIGH: "red",
                }[rec.risk_level]
                
                rec_table.add_row(
                    f"[{risk_color}]{rec.risk_level.value.upper()}[/{risk_color}]",
                    rec.bucket[:20],
                    rec.recommended_action[:50],
                    f"${rec.estimated_monthly_savings:.2f}"
                )
            
            console.print(rec_table)
        
        if self.stats["errors"]:
            console.print(f"\n[yellow]Warnings: {len(self.stats['errors'])} errors during scan[/yellow]")


def main():
    """Main entry point."""
    config = ScannerConfig()
    scanner = S3CostScanner(config)
    
    # Run scan
    scanner.scan_all_buckets()
    
    # Print summary
    scanner.print_summary()
    
    # Save report
    report = scanner.generate_report()
    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    
    output_file = output_dir / "scan_results.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    console.print(f"\n[dim]Full report saved to: {output_file}[/dim]\n")
    
    return 0 if not scanner.stats["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())