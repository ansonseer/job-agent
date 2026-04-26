"""
Web Utility - Fetch company information from multiple sources.
Sources: Company website, GitHub, Google News
"""

import requests
import json
import re
import time


def fetch_webpage(url: str, timeout: int = 15) -> str:
    """
    Fetch a webpage and return clean text content.
    Strips HTML tags for LLM consumption.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        
        text = resp.text
        # Remove script and style blocks
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Clean whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Truncate to ~8000 chars to fit in LLM context
        if len(text) > 8000:
            text = text[:8000] + "... [truncated]"
        
        return text
    except requests.RequestException as e:
        return f"[Error fetching {url}: {str(e)}]"


def fetch_github_org(org_name: str) -> dict:
    """
    Fetch GitHub organization info and top repositories.
    Returns tech stack signals.
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    result = {
        "found": False,
        "org_info": {},
        "top_repos": [],
        "languages": {},
    }
    
    try:
        # Try org first
        resp = requests.get(
            f"https://api.github.com/orgs/{org_name}",
            headers=headers, timeout=10
        )
        
        if resp.status_code == 200:
            org = resp.json()
            result["found"] = True
            result["org_info"] = {
                "name": org.get("name", ""),
                "description": org.get("description", ""),
                "public_repos": org.get("public_repos", 0),
                "blog": org.get("blog", ""),
            }
            
            # Fetch top repos by stars
            repos_resp = requests.get(
                f"https://api.github.com/orgs/{org_name}/repos",
                params={"sort": "stars", "per_page": 5},
                headers=headers, timeout=10
            )
            
            if repos_resp.status_code == 200:
                for repo in repos_resp.json()[:5]:
                    result["top_repos"].append({
                        "name": repo["name"],
                        "description": repo.get("description", ""),
                        "language": repo.get("language", ""),
                        "stars": repo.get("stargazers_count", 0),
                        "topics": repo.get("topics", []),
                    })
                    if repo.get("language"):
                        lang = repo["language"]
                        result["languages"][lang] = result["languages"].get(lang, 0) + 1
        
        return result
        
    except requests.RequestException as e:
        result["error"] = str(e)
        return result


def search_google_news(query: str, num_results: int = 5) -> list:
    """
    Search for recent news about a company using Google's RSS feed.
    Free, no API key needed.
    """
    results = []
    try:
        # Use Google News RSS
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-AU&gl=AU&ceid=AU:en"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            # Simple XML parsing (avoid extra dependency)
            items = re.findall(r'<item>(.*?)</item>', resp.text, re.DOTALL)
            for item in items[:num_results]:
                title = re.search(r'<title>(.*?)</title>', item)
                pub_date = re.search(r'<pubDate>(.*?)</pubDate>', item)
                if title:
                    results.append({
                        "title": title.group(1).replace('<![CDATA[', '').replace(']]>', ''),
                        "date": pub_date.group(1) if pub_date else "",
                    })
    except requests.RequestException:
        pass
    
    return results


def fetch_company_data(company_name: str, company_url: str = None) -> dict:
    """
    Aggregate data from all sources for a company.
    This is the main function Agent B uses.
    """
    print(f"  🔍 Researching {company_name}...")
    data = {
        "company_name": company_name,
        "website_content": "",
        "github": {},
        "recent_news": [],
    }
    
    # 1. Fetch company website
    if company_url:
        print(f"    📄 Fetching website...")
        data["website_content"] = fetch_webpage(company_url)
        time.sleep(1)  # Be polite
    
    # 2. Try GitHub (guess org name from company name)
    github_name = company_name.lower().replace(" ", "").replace(".", "")
    print(f"    🐙 Checking GitHub ({github_name})...")
    data["github"] = fetch_github_org(github_name)
    
    # Also try with hyphens
    if not data["github"]["found"]:
        github_name_alt = company_name.lower().replace(" ", "-")
        data["github"] = fetch_github_org(github_name_alt)
    
    time.sleep(1)
    
    # 3. Search recent news
    print(f"    📰 Searching news...")
    data["recent_news"] = search_google_news(f"{company_name} AI technology")
    
    return data


# ============================================================
# JSearch API (RapidAPI) - for Agent A
# ============================================================
def search_jobs(query: str, location: str, api_key: str, 
                num_pages: int = 1, date_posted: str = "week") -> list:
    """
    Search for jobs using JSearch API on RapidAPI.
    Free tier: 500 requests/month.
    """
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    
    all_jobs = []
    for page in range(1, num_pages + 1):
        params = {
            "query": f"{query} in {location}",
            "page": str(page),
            "num_pages": "1",
            "date_posted": date_posted,
        }
        
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            
            if "data" in data:
                for job in data["data"]:
                    all_jobs.append({
                        "id": job.get("job_id", ""),
                        "title": job.get("job_title", ""),
                        "company": job.get("employer_name", ""),
                        "location": job.get("job_city", "") + ", " + job.get("job_country", ""),
                        "url": job.get("job_apply_link", ""),
                        "description": job.get("job_description", "")[:3000],
                        "posted_date": job.get("job_posted_at_datetime_utc", ""),
                        "employment_type": job.get("job_employment_type", ""),
                        "platform": job.get("job_publisher", ""),
                        "company_url": job.get("employer_website", ""),
                    })
            
            time.sleep(1)  # Rate limit respect
            
        except requests.RequestException as e:
            print(f"  ❌ JSearch Error: {e}")
    
    return all_jobs
