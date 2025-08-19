#!/usr/bin/env python3
"""
Data Consistency Monitor

This script can be run periodically (e.g., via cron) to monitor data consistency
between PostgreSQL and Neo4j and alert when inconsistencies are detected.
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

# Reuse the consistency checker
from data_consistency_check import DataConsistencyChecker

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataConsistencyMonitor:
    def __init__(self, log_dir: str = "/tmp"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.report_file = self.log_dir / "data_consistency_report.json"
        self.checker = DataConsistencyChecker()

    def run_check_with_monitoring(self) -> Dict[str, Any]:
        """Run consistency check and add monitoring metadata"""
        try:
            results = self.checker.run_consistency_check()
            
            # Add monitoring metadata
            results["monitoring"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "error": None
            }
            
            return results
            
        except Exception as e:
            logger.error(f"Consistency check failed: {e}")
            return {
                "summary": {
                    "postgres_notes_count": 0,
                    "neo4j_notes_count": 0,
                    "postgres_documents_count": 0,
                    "neo4j_documents_count": 0,
                    "notes_missing_in_neo4j": 0,
                    "notes_orphaned_in_neo4j": 0,
                    "docs_missing_in_neo4j": 0,
                    "docs_orphaned_in_neo4j": 0
                },
                "inconsistencies": {
                    "notes_missing_in_neo4j": {"ids": [], "details": []},
                    "notes_orphaned_in_neo4j": {"ids": [], "details": []},
                    "documents_missing_in_neo4j": {"ids": [], "details": []},
                    "documents_orphaned_in_neo4j": {"ids": [], "details": []}
                },
                "monitoring": {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "error",
                    "error": str(e)
                }
            }

    def save_report(self, results: Dict[str, Any]):
        """Save the consistency report to a JSON file"""
        try:
            with open(self.report_file, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Report saved to {self.report_file}")
        except Exception as e:
            logger.error(f"Failed to save report: {e}")

    def load_previous_report(self) -> Dict[str, Any]:
        """Load the previous consistency report if it exists"""
        try:
            if self.report_file.exists():
                with open(self.report_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load previous report: {e}")
        return None

    def detect_changes(self, current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
        """Detect changes between current and previous reports"""
        if not previous:
            return {"status": "first_run", "changes": []}
        
        changes = []
        current_summary = current.get("summary", {})
        previous_summary = previous.get("summary", {})
        
        # Check for changes in inconsistency counts
        metrics = [
            "notes_missing_in_neo4j",
            "notes_orphaned_in_neo4j", 
            "docs_missing_in_neo4j",
            "docs_orphaned_in_neo4j"
        ]
        
        for metric in metrics:
            current_count = current_summary.get(metric, 0)
            previous_count = previous_summary.get(metric, 0)
            
            if current_count != previous_count:
                change_type = "increased" if current_count > previous_count else "decreased"
                changes.append({
                    "metric": metric,
                    "change_type": change_type,
                    "previous_count": previous_count,
                    "current_count": current_count,
                    "difference": abs(current_count - previous_count)
                })
        
        # Check for database count changes
        db_metrics = [
            "postgres_notes_count",
            "neo4j_notes_count",
            "postgres_documents_count", 
            "neo4j_documents_count"
        ]
        
        for metric in db_metrics:
            current_count = current_summary.get(metric, 0)
            previous_count = previous_summary.get(metric, 0)
            
            if current_count != previous_count:
                change_type = "increased" if current_count > previous_count else "decreased"
                changes.append({
                    "metric": metric,
                    "change_type": change_type,
                    "previous_count": previous_count,
                    "current_count": current_count,
                    "difference": abs(current_count - previous_count)
                })
        
        return {
            "status": "changes_detected" if changes else "no_changes",
            "changes": changes
        }

    def format_alert_message(self, results: Dict[str, Any], change_info: Dict[str, Any]) -> str:
        """Format an alert message for inconsistencies"""
        summary = results.get("summary", {})
        timestamp = results.get("monitoring", {}).get("timestamp", "unknown")
        
        total_inconsistencies = (
            summary.get("notes_missing_in_neo4j", 0) +
            summary.get("notes_orphaned_in_neo4j", 0) +
            summary.get("docs_missing_in_neo4j", 0) +
            summary.get("docs_orphaned_in_neo4j", 0)
        )
        
        message = f"""
🚨 DATA CONSISTENCY ALERT
Timestamp: {timestamp}

Database Status:
- PostgreSQL Notes: {summary.get('postgres_notes_count', 0)}
- Neo4j Notes: {summary.get('neo4j_notes_count', 0)}
- PostgreSQL Documents: {summary.get('postgres_documents_count', 0)}
- Neo4j Documents: {summary.get('neo4j_documents_count', 0)}

Total Inconsistencies: {total_inconsistencies}
- Notes missing in Neo4j: {summary.get('notes_missing_in_neo4j', 0)}
- Notes orphaned in Neo4j: {summary.get('notes_orphaned_in_neo4j', 0)}
- Documents missing in Neo4j: {summary.get('docs_missing_in_neo4j', 0)}
- Documents orphaned in Neo4j: {summary.get('docs_orphaned_in_neo4j', 0)}
"""
        
        if change_info["status"] == "changes_detected":
            message += "\nChanges detected:\n"
            for change in change_info["changes"]:
                message += f"- {change['metric']}: {change['change_type']} from {change['previous_count']} to {change['current_count']}\n"
        
        return message.strip()

    def print_status_summary(self, results: Dict[str, Any], change_info: Dict[str, Any]):
        """Print a concise status summary"""
        summary = results.get("summary", {})
        timestamp = results.get("monitoring", {}).get("timestamp", "unknown")
        status = results.get("monitoring", {}).get("status", "unknown")
        
        total_inconsistencies = (
            summary.get("notes_missing_in_neo4j", 0) +
            summary.get("notes_orphaned_in_neo4j", 0) +
            summary.get("docs_missing_in_neo4j", 0) +
            summary.get("docs_orphaned_in_neo4j", 0)
        )
        
        print(f"Data Consistency Monitor - {timestamp}")
        print(f"Status: {status.upper()}")
        
        if status == "success":
            if total_inconsistencies == 0:
                print("✅ Database consistency: HEALTHY")
            else:
                print(f"⚠️  Database consistency: {total_inconsistencies} inconsistencies detected")
                print(f"   - Notes orphaned in Neo4j: {summary.get('notes_orphaned_in_neo4j', 0)}")
                print(f"   - Documents orphaned in Neo4j: {summary.get('docs_orphaned_in_neo4j', 0)}")
                print(f"   - Notes missing in Neo4j: {summary.get('notes_missing_in_neo4j', 0)}")
                print(f"   - Documents missing in Neo4j: {summary.get('docs_missing_in_neo4j', 0)}")
        else:
            print("❌ Database consistency: ERROR")
            print(f"   Error: {results.get('monitoring', {}).get('error', 'Unknown error')}")
        
        if change_info["status"] == "changes_detected":
            print(f"📊 Changes since last check: {len(change_info['changes'])} metrics changed")

    def close_connections(self):
        """Close database connections"""
        self.checker.close_connections()

def main():
    parser = argparse.ArgumentParser(description="Monitor data consistency between PostgreSQL and Neo4j")
    parser.add_argument(
        "--alert-on-inconsistencies",
        action="store_true",
        help="Exit with non-zero code if inconsistencies are found (useful for monitoring systems)"
    )
    parser.add_argument(
        "--alert-on-changes",
        action="store_true", 
        help="Exit with non-zero code if changes are detected since last run"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only output if inconsistencies or changes are found"
    )
    parser.add_argument(
        "--log-dir",
        default="/tmp",
        help="Directory to store consistency reports (default: /tmp)"
    )
    
    args = parser.parse_args()
    
    monitor = DataConsistencyMonitor(log_dir=args.log_dir)
    
    try:
        # Run consistency check
        current_results = monitor.run_check_with_monitoring()
        
        # Load previous report for comparison
        previous_results = monitor.load_previous_report()
        
        # Detect changes
        change_info = monitor.detect_changes(current_results, previous_results)
        
        # Save current report
        monitor.save_report(current_results)
        
        # Determine if we should output anything
        summary = current_results.get("summary", {})
        total_inconsistencies = (
            summary.get("notes_missing_in_neo4j", 0) +
            summary.get("notes_orphaned_in_neo4j", 0) +
            summary.get("docs_missing_in_neo4j", 0) +
            summary.get("docs_orphaned_in_neo4j", 0)
        )
        
        has_inconsistencies = total_inconsistencies > 0
        has_changes = change_info["status"] == "changes_detected"
        should_output = not args.quiet or has_inconsistencies or has_changes
        
        if should_output:
            monitor.print_status_summary(current_results, change_info)
            
            # If there are inconsistencies, show the alert message
            if has_inconsistencies:
                print("\n" + monitor.format_alert_message(current_results, change_info))
        
        # Exit with appropriate code for monitoring systems
        exit_code = 0
        if args.alert_on_inconsistencies and has_inconsistencies:
            exit_code = 1
        elif args.alert_on_changes and has_changes:
            exit_code = 1
        
        sys.exit(exit_code)
        
    except Exception as e:
        logger.error(f"Monitoring failed: {e}")
        sys.exit(2)  # Error code for script failure
    finally:
        monitor.close_connections()

if __name__ == "__main__":
    main()