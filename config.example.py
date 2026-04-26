"""
Job Agent Configuration — TEMPLATE
Copy this file to config.py and fill in your real API keys.
config.py is gitignored, so your keys never enter version control.

Usage:
    cp config.example.py config.py
    # edit config.py with your real keys
"""

# ============================================================
# API Keys — replace with your real keys in config.py
# ============================================================
ANTHROPIC_API_KEY = "your-anthropic-api-key-here"  # From console.anthropic.com
JSEARCH_API_KEY   = "your-jsearch-api-key-here"    # From rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch

# ============================================================
# Job Seeker Profile — replace with your own profile
# ============================================================
SEEKER_PROFILE = {
    "name":     "Your Name",
    "email":    "you@example.com",
    "phone":    "+61 4XX XXX XXX",
    "location": "Sydney, NSW",
    "visa":     "Your visa status (e.g. 'PR' or '485 Post-Study Work Visa')",
    "linkedin": "https://www.linkedin.com/in/your-handle",
    "github":   "https://github.com/your-handle",

    "target_roles": [
        "AI Engineer",
        "Machine Learning Engineer",
        "Full Stack Developer (AI focus)",
        # ...add more
    ],

    "target_locations": [
        "Sydney, Australia",
        "Melbourne, Australia",
        "Remote - Australia",
        "Remote - Global",
    ],

    "salary_range": {
        "min":      65000,
        "max":      140000,
        "currency": "AUD",
    },

    "deal_breakers": [
        "Requires 5+ years experience",
        "Requires PhD",
        "Requires citizenship / security clearance",
        # ...add your own
    ],

    "preferences": [
        "Startup > Large enterprise",
        "Hands-on building > Management",
        # ...add your own
    ],

    # Be HONEST here. The system uses this to flag "cannot_claim" items as fabrication
    # if a tailored resume tries to mention them.
    "skills_honest": {
        "strong":        ["List skills you can demonstrate at interview"],
        "moderate":      ["List skills you've used but aren't expert at"],
        "learning":      ["List skills you're studying"],
        "cannot_claim":  ["List skills NOT to put on a resume — even if a JD asks for them"],
    },
}

# ============================================================
# Search Parameters (Agent A)
# ============================================================
SEARCH_CONFIG = {
    "queries":               ["AI Engineer", "Machine Learning Engineer junior", "LLM Engineer"],
    "locations":             ["Sydney, Australia", "Melbourne, Australia", "Australia"],
    "date_posted":           "week",       # today | 3days | week | month
    "employment_type":       "FULLTIME",   # FULLTIME | PARTTIME | CONTRACTOR | INTERN
    "max_results_per_query": 10,
    "min_match_score":       50,           # 0-100, below this = auto-skip
}

# ============================================================
# LLM Configuration
# ============================================================
LLM_CONFIG = {
    "screening_model": "claude-sonnet-4-20250514",  # Agent A scoring
    "intel_model":     "claude-sonnet-4-20250514",  # Agent B intel
    "resume_model":    "claude-sonnet-4-20250514",  # Agent C generation
    "validator_model": "claude-sonnet-4-20250514",  # Agent D — consider Opus if Sonnet sycophancy persists
    "max_tokens":      6000,
    "temperature":     0.3,
}

# ============================================================
# File Paths
# ============================================================
PATHS = {
    "base_resume": "data/base_resume.md",
    "output_dir":  "output/",
    "job_data":    "data/jobs.json",
    "intel_data":  "data/intel/",
    "tracking":    "data/tracking.json",
}
