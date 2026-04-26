"""
Job Agent - Main Entry Point
Run the full pipeline or individual agents.
"""

import sys
import json
import os

from config import SEEKER_PROFILE, SEARCH_CONFIG, PATHS
from agents.agent_b_intel import run_agent_b, save_report
from utils.llm import print_usage


def run_single_company(company_name: str, jd_text: str, company_url: str = None):
    """Run Agent B on a single company."""
    report = run_agent_b(company_name, jd_text, company_url)
    if report:
        save_report(report)
    print_usage()
    return report


def run_batch(jobs: list):
    """Run Agent B on multiple jobs."""
    reports = []
    for i, job in enumerate(jobs):
        print(f"\n\n{'#'*60}")
        print(f"# Job {i+1}/{len(jobs)}: {job.get('title', '?')} at {job.get('company', '?')}")
        print(f"{'#'*60}")
        
        report = run_agent_b(
            company_name=job["company"],
            jd_text=job.get("description", ""),
            company_url=job.get("company_url"),
        )
        
        if report:
            save_report(report)
            reports.append(report)
    
    # Summary
    print(f"\n\n{'='*60}")
    print(f"📊 BATCH SUMMARY: {len(reports)}/{len(jobs)} reports generated")
    print(f"{'='*60}")
    
    for r in reports:
        match = r.get("match_assessment", {})
        name = r.get("company_profile", {}).get("name", "?")
        score = match.get("overall_match_score", "?")
        verdict = match.get("verdict", "?")
        print(f"  {name}: {score}/100 - {verdict}")
    
    print_usage()
    return reports


if __name__ == "__main__":
    print("="*60)
    print("🤖 JOB AGENT v1.0")
    print(f"👤 Seeker: {SEEKER_PROFILE['name']}")
    print(f"🎯 Target: {', '.join(SEEKER_PROFILE['target_roles'][:3])}...")
    print("="*60)
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "test":
            # Quick test with Culture Amp
            print("\n🧪 Running test with Culture Amp...")
            run_single_company(
                "Culture Amp",
                """AI Engineer - Applied AI. Culture Amp, Sydney NSW (Hybrid).
                Looking for an AI Engineer to build AI-powered features for employee engagement.
                Requirements: LLMs, Python, production AI, ML fundamentals.
                Nice to have: RAG, HR analytics, AWS/GCP.""",
                "https://www.cultureamp.com"
            )
        
        elif cmd == "intel":
            # Interactive mode: enter company details
            print("\n🕵️ Agent B - Intel Mode")
            company = input("Company name: ").strip()
            url = input("Company URL (optional, press Enter to skip): ").strip() or None
            print("Paste JD (type END on a new line when done):")
            jd_lines = []
            while True:
                line = input()
                if line.strip() == "END":
                    break
                jd_lines.append(line)
            jd = "\n".join(jd_lines)
            
            run_single_company(company, jd, url)
    
    else:
        print("\nUsage:")
        print("  python main.py test      # Quick test with sample data")
        print("  python main.py intel     # Interactive: analyze one company")
        print("\nNext steps:")
        print("  1. Add your API key in config.py")
        print("  2. Run: python main.py test")
        print("  3. Check output in data/intel/")
