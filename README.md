# Job Agent — AI-Powered Precision Job Application System

A 5-agent system that maximizes interview-to-application ratio. Instead of blasting 200 applications at 5% conversion, target 20 with 30%+.

## Architecture

```
Resume + Job Market
       ↓
┌──────────────┐
│   Agent A    │  Scout — searches Seek/LinkedIn, ranks top 30 matches
│  (Dynamic)   │  Uses: JSearch API + Playwright browser automation
└──────┬───────┘
       ↓
┌──────────────┐
│   Agent B    │  Intel — deep company analysis: pain points, culture,
│  (Pipeline)  │  hidden requirements, application channels
└──────┬───────┘  Confidence-tagged inferences with evidence citations
       ↓
┌──────────────┐
│   Agent C    │  Tailor — adjusts resume 5-10% per company
│  (Pipeline)  │  Outputs "customization layer" showing exactly what changed
└──────┬───────┘  Hard rule: no fabrication, no exaggeration
       ↓
┌──────────────┐
│   Agent D    │  Validator — Falsification-First HR simulation
│  (Pipeline)  │  Must find 3 rejection reasons before strengths
└──────┬───────┘  Interview probability + gap analysis + prep plan
       ↓
┌──────────────┐
│   Agent E    │  Executor — selects outreach channel, generates
│  (Dynamic)   │  personalised messages, tracks application status
└──────────────┘
```

### Pipeline vs Agent

B→C→D runs as a **fixed pipeline** — deterministic steps, same every time.
A and E are **true agents** — they make dynamic decisions based on context (which platforms to search, which channel to use for outreach).

This distinction matters. Most AI projects call everything an "agent" when it's really a pipeline. Understanding the difference is what makes the architecture reliable.

## Tech Stack

- **Language:** Python
- **LLM:** Claude API (Anthropic) — Sonnet for B/C, configurable for D
- **Web:** Playwright for browser automation, Requests for API calls
- **No frameworks:** No LangChain, no CrewAI, no AutoGen. Raw Python + JSON. Fixed workflows don't need orchestration frameworks.

## Key Design Decisions

1. **Falsification-First validation** — LLMs have sycophancy bias. Agent D's prompt forces rejection-first reasoning to prevent the validator becoming a rubber stamp.

2. **JSON + reasoning fields** — Agents pass not just "what" but "why". Agent B outputs `reasoning: "Python in JD paragraph 3, AWS inferred from cloud platforms"`. Downstream agents read these chains for better decisions.

3. **Separation of concerns** — Each agent has one job. Agent C tailors but doesn't evaluate (that's D). Agent D validates but doesn't modify (sends retry to C). A tailor shouldn't grade their own work.

4. **Tiered prompt complexity** — High-stakes agents (C, D) get structured methodology with self-verification. Low-stakes agents (A) get lightweight prompts. Not every agent needs the same engineering depth.

## Project Structure

```
job-agent/
├── config.example.py          # Configuration template (add your API keys)
├── main.py                    # Pipeline entry point
├── README.md
├── agents/
│   ├── agent_b_intel.py       # Agent B execution code
│   ├── agent_c_tailor.py      # Agent C execution code
│   └── agent_d_validator.py   # Agent D execution code
├── prompts/
│   ├── agent_b_prompt.py      # Agent B system prompt (shared base + role-specific)
│   ├── agent_c_prompt.py      # Agent C system prompt
│   └── agent_d_prompt.py      # Agent D system prompt
├── utils/
│   ├── llm.py                 # Claude API wrapper with retry + cost tracking
│   └── web.py                 # Web fetch + GitHub API + news search
└── data/
    └── base_resume.md         # Base resume (facts only, never modified by agents)
```

## Setup

```bash
pip install anthropic requests
cp config.example.py config.py
# Edit config.py with your API keys
python main.py --company "company_name" --jd "paste JD text"
```

## Cost

~$0.15-0.20 USD per company (full B→C→D pipeline). $5 covers ~30 applications.

## Status

- Agent A: Architecture complete, integration in progress
- Agent B: ✅ Complete — tested on 3 companies
- Agent C: ✅ Complete — with customization layer + honesty checks
- Agent D: ✅ Complete — Falsification-First + assessment reports
- Agent E: Architecture complete, integration in progress

## Prompt Architecture

Built on RMC (Recursive Meta-Cognition) v4.0 — a structured prompt framework designed for adversarial truth-seeking. Each agent prompt uses a shared base (identity, schema, boundaries, failure signals) + role-specific modules (methodology, domain knowledge, quality standards).

## Author

Ao Sun (Anson) — [github.com/ansonseer](https://github.com/ansonseer)
