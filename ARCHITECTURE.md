# Job Agent — Architecture & Design Decisions

> A multi-agent system for AI-augmented job search.
> This doc captures the reasoning behind the current architecture,
> including the pivot from v1 (platform-coupled scraper) to v2
> (need-driven discovery layer).

---

## 1. Problem Statement

The original framing of "job search automation" almost always
collapses into "scrape job boards faster." This is the wrong
abstraction.

The real problem is not *finding more job postings* — it is
*identifying which postings actually match a candidate's evolving
need-state, and what to do next when a match is found*.

This distinction drove the architecture pivot below.

---

## 2. v1 Architecture (deprecated)

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Agent A    │───>│   Agent B    │───>│   Agent C    │
│  (Scraper)   │    │  (Intel)     │    │  (Resume     │
│              │    │              │    │   Tailor)    │
│  Seek +      │    │  Analyze JD  │    │  Customize   │
│  LinkedIn    │    │  + Score     │    │  per role    │
└──────────────┘    └──────────────┘    └──────────────┘
```

**v1 Agent A bound the entire pipeline to specific platforms
(Seek, LinkedIn). This was wrong for three reasons:**

1. **Platform fragility** — Anti-scraping measures, layout changes,
   and rate limits made Agent A the bottleneck. Every change broke
   the downstream pipeline.

2. **Wrong abstraction** — The user does not want "scraped postings."
   They want "opportunities matching a current need-state." Job
   boards are *one source* of opportunities, not the only source.

3. **Closed ecosystem** — A scraper-only Agent A cannot ingest
   referrals, recruiter messages, or alumni-network leads —
   which empirically have 5–10x higher conversion rates than
   cold applications.

---

## 3. v2 Architecture (current)

```
┌────────────────────────────────────┐
│           Agent A                  │
│   Need-Driven Discovery Layer      │
│                                    │
│   Source-agnostic intake:          │
│   • Job boards (Seek, LinkedIn)    │
│   • Direct company career pages    │
│   • Recruiter inbound              │
│   • Referrals + alumni             │
│   • RSS / API feeds                │
│                                    │
│   Output: normalized               │
│   "Opportunity" objects            │
└──────────────────┬─────────────────┘
                   │
                   ▼
┌────────────────────────────────────┐
│        Decision Council            │
│      (Agent B / C / D)             │
│                                    │
│  ┌──────────────────────────┐      │
│  │ Agent B — Intel Officer  │      │
│  │ Score JD vs candidate    │      │
│  │ Identify pain points     │      │
│  └──────────────────────────┘      │
│                                    │
│  ┌──────────────────────────┐      │
│  │ Agent C — Tailor         │      │
│  │ Customize resume + CL    │      │
│  │ for high-match opps      │      │
│  └──────────────────────────┘      │
│                                    │
│  ┌──────────────────────────┐      │
│  │ Agent D — Strategist     │      │
│  │ Map gaps → skill plan    │      │
│  │ Suggest interview angle  │      │
│  └──────────────────────────┘      │
└──────────────────┬─────────────────┘
                   │
                   ▼
        Action recommendations to user
```

### Key reframe

|                   | v1                          | v2                                |
|-------------------|-----------------------------|-----------------------------------|
| Agent A's job     | Scrape job boards           | Detect opportunity windows        |
| Coupling          | Tight to platform APIs      | Source-agnostic intake            |
| Output            | Job posting objects         | Normalized opportunity objects    |
| BCD's role        | Process scraped data        | Strategic decision council        |
| Failure mode      | Platform breaks → all dead  | One source breaks → others continue |

---

## 4. Why a Pipeline, not an Agent Framework

This is a Python pipeline with sequential stages and JSON-passing
between agents. It is **not** built on LangChain, CrewAI, AutoGen,
or any framework.

This is intentional, not a deficiency.

Reasons:

1. **The task flow is fixed.** Scraping → intel → tailoring →
   strategy is a deterministic sequence, not an emergent
   conversation. Pipelines are more debuggable and reproducible
   than agent frameworks for fixed flows.

2. **Framework lock-in costs.** LangChain/CrewAI churn rapidly.
   A 2024 codebase using them is often broken by 2026. Pure
   Python + the model provider's SDK is more durable.

3. **Reasoning transparency.** Each agent passes a `reasoning`
   field alongside its output JSON. The full reasoning chain is
   auditable, not buried inside framework abstractions.

4. **Cost control.** Direct API calls are easier to monitor and
   bound than framework-mediated calls.

---

## 5. Inter-Agent Contract

Every agent input and output is a JSON object with this shape:

```python
{
  "agent_id": "B",
  "input_summary": "...",      # what this agent received
  "reasoning": "...",          # how it processed
  "output": { ... },           # structured result
  "confidence": 0.0–1.0,       # self-reported certainty
  "weak_points": [ ... ],      # where this agent is least sure
  "next_agent_hints": [ ... ]  # what downstream should attend to
}
```

The `reasoning` and `weak_points` fields exist because of an
insight from working with multiple LLM agents:

> A single LLM with high stated confidence can be confidently wrong
> (sycophancy bias). Forcing each agent to surface its weak points
> lets downstream agents — and the human reviewer — apply
> appropriate skepticism.

This is a small piece of "verification thinking" embedded in the
contract itself, rather than added as a separate verification
layer.

---

## 6. Prompt Architecture: RMC-v4.0-ISO

Each agent's system prompt follows the RMC-v4.0-ISO template:

- **Shared base** (sections a–e): identity, mission, input schema,
  output schema, boundaries — common to all agents.
- **Role-specific** (sections f–i): methodology, quality criteria,
  failure signals, retry feedback handling — distinct per agent.

This separation makes prompts maintainable. Updating a shared
constraint (e.g., "always include `weak_points`") changes one
file, not five.

For details on the RMC framework see the `prompts/` directory.

---

## 7. Current Implementation Status

| Component             | Status              | Notes                                                  |
|-----------------------|---------------------|--------------------------------------------------------|
| Agent A (Discovery)   | Design phase        | v2 reframe complete; implementation pending            |
| Agent B (Intel)       | Implemented         | Tested manually on 3 companies via Claude Code         |
| Agent C (Tailor)      | Implemented (MVP)   | Generated resume + cover letter for one role           |
| Agent D (Strategist)  | Not started         | Planned next                                           |
| Agent E (Outreach)    | Not started         | Planned next                                           |
| Inter-agent contract  | Defined             | JSON schema in `schemas/`                              |
| RMC prompts           | v4.0-ISO            | Shared base + role-specific layers                     |

This is a project under active development. The architecture
above represents the intended design; implementation is in
progress.

---

## 8. Decisions That Were Considered and Rejected

**LangChain / CrewAI / AutoGen** — see Section 4.

**MCP (Model Context Protocol)** — Useful when agents need to
share tools. Current pipeline is sequential with JSON passing,
so MCP overhead is not justified yet. Will revisit when adding
Agent E (outreach) which needs email/LinkedIn tools.

**RAG / Vector DB** — Not needed at current scale. Each
opportunity fits in context. Will reconsider if accumulated
opportunity history exceeds context window.

**Fine-tuning** — Generic LLM capability is sufficient for the
reasoning tasks here. Fine-tuning adds operational cost without
meaningful capability gain at this scale.

**Multi-model routing** (Claude vs GPT vs DeepSeek per agent) —
Considered. Current implementation uses Claude for all agents
to keep iteration fast. Multi-model routing is a future
optimization once each agent's prompt is stable.

---

## 9. Open Questions

These are problems I am actively working through:

1. **Sycophancy bias across agents.** Agent B may over-score a
   role because Agent A passed it through. The current `weak_points`
   mechanism is a partial mitigation; a stronger fix would be
   physical context isolation between agents (RMC-v4.0-ISO mode).

2. **Verification layer.** No automated check that Agent C's
   tailored resume actually matches Agent B's identified pain
   points. Currently relies on manual review. A Promptfoo eval
   suite is the next planned addition.

3. **Failure mode handling.** When an agent returns malformed
   JSON or fails entirely, the pipeline halts. Need retry-with-
   feedback logic at the orchestrator level.

4. **Agent A's source ranking.** Given multiple opportunity sources,
   how should Agent A weight a referral vs a job board posting vs
   a recruiter inbound? Currently uniform; should be conversion-
   weighted.

5. **Schema reliability.** Agent JSON output is currently driven
   by prompt instruction ("respond in this format..."), with
   ~85% format compliance. Schema-aligned parsing tools (BAML
   and similar) compile typed schemas into both prompt and
   recovery parser, raising compliance toward ~99%. Migrating
   the inter-agent contract to a schema-first approach is a
   planned reliability improvement.

6. **Match scoring with human feedback.** Currently Agent B
   produces a match score that the user accepts or ignores —
   no feedback loop. A future direction is letting the user
   score Agent B's verdicts (worth-applying / borderline / skip),
   so subsequent runs adjust their scoring criteria based on
   accumulated user judgment. This makes Agent B a learning
   layer rather than a fixed evaluator.

---

## 10. Why This Repo Matters

This is not a polished commercial product. It is a working notebook
of one engineer thinking through a real problem (job search
automation) with multi-agent LLM systems.

The value is in the reasoning trail, not the feature completeness.
Architecture decisions, rejected alternatives, and open questions
are documented so the trade-offs are visible — not just the result.

— Anson Sun
Last updated: May 4, 2026
