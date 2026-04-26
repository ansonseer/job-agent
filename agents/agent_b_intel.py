"""
Agent B: Intel Agent v2
Uses RMC-v4.0-ISO prompt architecture with shared base + role-specific modules.
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm import call_llm, print_usage
from utils.web import fetch_company_data
from config import LLM_CONFIG
from prompts.agent_b_prompt import build_agent_b_system_prompt, AGENT_B_USER_TEMPLATE

def run_agent_b(company_name, jd_text, company_url=None):
    print(f"\n{'='*60}")
    print(f"Agent B: Intel Report for {company_name}")
    print(f"{'='*60}")
    raw_data = fetch_company_data(company_name, company_url)
    github_summary = "No GitHub presence found."
    if raw_data["github"]["found"]:
        gh = raw_data["github"]
        repos_text = "\n".join([f"  - {r['name']}: {r['description']} ({r['language']}, {r['stars']} stars)" for r in gh["top_repos"]])
        github_summary = f"Org: {gh['org_info'].get('description','N/A')}\nRepos: {gh['org_info'].get('public_repos',0)}\nLanguages: {json.dumps(gh['languages'])}\n{repos_text}"
    news_summary = "No recent news found."
    if raw_data["recent_news"]:
        news_summary = "\n".join([f"  - [{n['date']}] {n['title']}" for n in raw_data["recent_news"]])
    website_content = raw_data["website_content"] or "No website content available."
    system_prompt = build_agent_b_system_prompt()
    user_prompt = AGENT_B_USER_TEMPLATE.format(jd_text=jd_text[:4000], website_content=website_content[:3000], github_data=github_summary[:2000], news_data=news_summary[:1000])
    total_chars = len(system_prompt) + len(user_prompt)
    est_tokens = total_chars // 4
    print(f"  Input: ~{est_tokens} tokens")
    if est_tokens > 12000:
        print(f"  Truncating to fit token budget...")
        user_prompt = AGENT_B_USER_TEMPLATE.format(jd_text=jd_text[:3000], website_content=website_content[:1500], github_data=github_summary[:1500], news_data=news_summary[:500])
    print(f"  Calling {LLM_CONFIG['intel_model']}...")
    report = call_llm(prompt=user_prompt, system=system_prompt, model=LLM_CONFIG["intel_model"], expect_json=True)
    if report is None:
        return {"_failure": "LLM_RETURNED_NONE", "company": company_name}
    if isinstance(report, dict) and "_failure" in report:
        return report
    required = ["company_profile","tech_stack","pain_points","what_they_really_want","resume_strategy","match_assessment"]
    missing = [k for k in required if k not in report]
    if missing:
        print(f"  Missing fields: {missing}, retrying...")
        retry_prompt = user_prompt + f"\n\nRETRY: Previous output missing: {missing}. Include ALL required fields."
        report = call_llm(prompt=retry_prompt, system=system_prompt, model=LLM_CONFIG["intel_model"], expect_json=True)
    if report and isinstance(report, dict):
        report["_metadata"] = {"agent":"B","version":"2.0","company":company_name,"url":company_url,"sources":{"website":bool(raw_data["website_content"]),"github":raw_data["github"]["found"],"news":len(raw_data["recent_news"])},"tokens_est":est_tokens,"generated_at":datetime.datetime.now().isoformat()}
        match = report.get("match_assessment",{})
        print(f"\n  Score: {match.get('score','?')}/100 | Verdict: {match.get('verdict','?')}")
    return report

def save_report(report, filename=None):
    if not filename:
        name = report.get("company_profile",{}).get("name",report.get("_metadata",{}).get("company","unknown"))
        filename = f"data/intel/{name.lower().replace(' ','_').replace('.','')}.json"
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename,"w",encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  Saved to {filename}")

if __name__ == "__main__":
    test_jd = """AI Engineer - Applied AI at Culture Amp, Sydney NSW (Hybrid). Build LLM-powered features for employee experience platform used by 6500+ companies. Requirements: LLMs in production, Python, ML fundamentals, production deployment. Nice to have: RAG, HR analytics, AWS/GCP, LangChain."""
    report = run_agent_b("Culture Amp", test_jd, "https://www.cultureamp.com")
    if report and "_failure" not in report:
        save_report(report)
        print(json.dumps(report, indent=2)[:2000])
    print_usage()
