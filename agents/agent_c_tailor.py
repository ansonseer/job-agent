"""
Agent C: Resume Tailor v2

Single-purpose: produce a tailored resume + cover letter from base_resume + JD + Agent B intel.
Does NOT evaluate (Agent D's job). Does NOT plan outreach (Agent E's job).
Customisation budget is 5-10%, applied via reorder + light rephrasing + cover-letter authoring.

Pipeline: Agent B (Intel) -> [Agent C: Tailor] -> Agent D (Validator)
                                              ^                  |
                                              |  retry_feedback  |
                                              +------------------+
"""
import json
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm import call_llm, print_usage
from config import LLM_CONFIG, PATHS
from prompts.agent_c_prompt import build_agent_c_system_prompt, AGENT_C_USER_TEMPLATE


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def _safe_filename(name: str) -> str:
    """Turn 'Culture Amp' / 'CallAidan Pty Ltd.' into 'culture_amp' / 'callaidan_pty_ltd'."""
    return (
        name.lower()
        .replace(" ", "_")
        .replace(".", "")
        .replace(",", "")
        .replace("/", "_")
        .strip("_")
    )


def _load_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_intel(intel_input):
    """Accept either a path-to-json or an already-parsed dict."""
    if isinstance(intel_input, dict):
        return intel_input
    if isinstance(intel_input, str) and os.path.isfile(intel_input):
        with open(intel_input, "r", encoding="utf-8") as f:
            return json.load(f)
    raise ValueError(
        "intel_json must be a dict (Agent B output) or a path to a saved intel JSON file."
    )


# ----------------------------------------------------------------
# Quality validation (v2 schema)
# ----------------------------------------------------------------
# Single source of truth for thresholds. Tweak here, not in multiple places.
COVERAGE_FLOOR_PCT      = 70   # keyword_coverage.coverage_rate must be >= this
CUSTOMISATION_MIN_PCT   = 5    # customization_layer.total_change_percentage low bound
CUSTOMISATION_MAX_PCT   = 10   # ...high bound
AGENT_B_REFS_MIN        = 2    # tailoring_notes.agent_b_references must contain at least this many quotes


def _evaluate_quality(result: dict) -> list:
    """
    Inspect Agent C's output against v2 quality standards.
    Returns a list of issue strings (empty when output is clean).

    Issues here drive the internal corrective retry. They are NOT the same as Agent D's
    HR/ATS evaluation — those happen downstream.
    """
    issues = []
    if not isinstance(result, dict):
        return ["result is not a dict"]

    # 1. Required top-level fields
    for k in ("tailored_resume", "cover_letter", "customization_layer", "keyword_coverage",
              "honesty_check", "tailoring_notes"):
        if k not in result:
            issues.append(f"missing top-level field: {k}")
    # If structurally broken, don't try to dig further.
    if issues:
        return issues

    # 2. Keyword coverage floor
    cov = result.get("keyword_coverage") or {}
    rate = cov.get("coverage_rate")
    if not isinstance(rate, (int, float)):
        issues.append("keyword_coverage.coverage_rate missing or non-numeric")
    elif rate < COVERAGE_FLOOR_PCT:
        issues.append(f"keyword_coverage {rate}% below floor {COVERAGE_FLOOR_PCT}%")

    # 3. Customisation band [5, 10]
    cl = result.get("customization_layer") or {}
    pct = cl.get("total_change_percentage")
    if not isinstance(pct, (int, float)):
        issues.append("customization_layer.total_change_percentage missing or non-numeric")
    elif pct < CUSTOMISATION_MIN_PCT:
        issues.append(f"customisation {pct}% below floor {CUSTOMISATION_MIN_PCT}% (lazy)")
    elif pct > CUSTOMISATION_MAX_PCT:
        issues.append(f"customisation {pct}% above ceiling {CUSTOMISATION_MAX_PCT}% (rewriting risk)")

    # 4. Honesty check — explicit branches (avoiding the v1 operator-precedence bug)
    hc = result.get("honesty_check") or {}
    if hc.get("any_facts_invented") is not False:
        issues.append("honesty_check.any_facts_invented must be explicit false")
    if hc.get("any_experiences_exaggerated") is not False:
        issues.append("honesty_check.any_experiences_exaggerated must be explicit false")

    # 5. Time-claims verification
    tcv = (hc.get("time_claims_verified") or {})
    if tcv.get("each_verified") is not True:
        unsupported = tcv.get("issues") or []
        issues.append(f"time_claims_verified.each_verified is not true (issues: {unsupported[:3]})")

    # 6. Banned-words scan must be empty
    bws = hc.get("banned_words_scan") or {}
    violations = bws.get("violations_found") or []
    if violations:
        # Each violation may be a string or a {term, where, snippet} dict.
        terms = []
        for v in violations:
            if isinstance(v, dict):
                terms.append(v.get("term", "?"))
            else:
                terms.append(str(v))
        issues.append(f"banned_words violations: {sorted(set(terms))}")

    # 7. Agent B references count
    refs = (result.get("tailoring_notes") or {}).get("agent_b_references") or []
    if len(refs) < AGENT_B_REFS_MIN:
        issues.append(f"agent_b_references has {len(refs)} items, need >= {AGENT_B_REFS_MIN}")

    return issues


# ----------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------
def run_agent_c(jd_text: str, intel_json, base_resume: str = None,
                retry_feedback: dict = None) -> dict:
    """
    Run Agent C (Resume Tailor) v2.

    Args:
        jd_text:        Full job description text.
        intel_json:     Agent B output. Either a dict or a path to a saved JSON file.
        base_resume:    Markdown content of the base resume. If None, loads from PATHS["base_resume"].
        retry_feedback: Optional dict from Agent D when triggering an external retry. Format:
                        {
                          "attempt":          <int>,        # current attempt number (>=2)
                          "previous_verdict": "A|B|C",
                          "reason":           "<str>",
                          "direction":        "<str>"
                        }
                        attempt >= 3 short-circuits with RETRY_LIMIT_REACHED.

    Returns:
        Structured Agent C v2 response — keys: tailored_resume, cover_letter,
        customization_layer, keyword_coverage, honesty_check, tailoring_notes,
        retry_needed (bool), retry_reasons (list[str]), _metadata.

        Or {"_failure": "..."} on hard failure.
    """
    # ---- 1. Load inputs ----
    intel = _load_intel(intel_json)
    if base_resume is None:
        base_resume = _load_text_file(PATHS["base_resume"])

    company_name = (
        intel.get("company_profile", {}).get("name")
        or intel.get("_metadata", {}).get("company")
        or "unknown"
    )

    print(f"\n{'='*60}")
    print(f"Agent C v2: Tailoring resume for {company_name}")
    print(f"{'='*60}")

    # ---- 2. External retry hard cap ----
    if retry_feedback:
        attempt = int(retry_feedback.get("attempt", 2))
        print(f"  External retry attempt #{attempt}: {retry_feedback.get('reason', '(no reason given)')}")
        if attempt >= 3:
            return {
                "_failure": "RETRY_LIMIT_REACHED",
                "company": company_name,
                "attempt": attempt,
                "retry_feedback": retry_feedback,
                "note": "Three honest tries is the cap. Send for human review.",
            }

    # ---- 3. Build prompts ----
    system_prompt = build_agent_c_system_prompt()

    def _build_user_prompt(jd_cap=4000, intel_cap=8000, base_cap=6000):
        up = AGENT_C_USER_TEMPLATE.format(
            company_name=company_name,
            jd_text=jd_text[:jd_cap],
            intel_json=json.dumps(intel, ensure_ascii=False, indent=2)[:intel_cap],
            base_resume=base_resume[:base_cap],
        )
        # Inject retry_feedback as the highest-priority block.
        # The prompt's RETRY HANDLING module governs how the model should react;
        # we only deliver the payload here. Reattaching after potential truncation
        # is critical — retry_feedback must NOT be dropped to fit token budget.
        if retry_feedback:
            up += (
                "\n\n## RETRY_FEEDBACK (highest priority — solve this BEFORE re-applying Phase 3):\n"
                + json.dumps(retry_feedback, ensure_ascii=False, indent=2)
            )
        return up

    user_prompt = _build_user_prompt()
    est_tokens = (len(system_prompt) + len(user_prompt)) // 4
    print(f"  Input: ~{est_tokens} tokens")

    if est_tokens > 14000:
        print("  Truncating to fit token budget...")
        user_prompt = _build_user_prompt(jd_cap=3000, intel_cap=5000, base_cap=5000)

    # ---- 4. Call LLM ----
    model = LLM_CONFIG.get("resume_model", LLM_CONFIG.get("intel_model"))
    max_tokens = LLM_CONFIG.get("max_tokens", 4096)
    print(f"  Calling {model} (max_tokens={max_tokens})...")

    result = call_llm(prompt=user_prompt, system=system_prompt,
                      model=model, max_tokens=max_tokens, expect_json=True)

    if result is None:
        return {"_failure": "LLM_RETURNED_NONE", "company": company_name}
    if isinstance(result, dict) and "_failure" in result:
        print(f"  Agent C self-reported failure: {result.get('_failure')}")
        return result

    # ---- 5. Internal corrective retry (max 1) ----
    issues = _evaluate_quality(result)
    if issues:
        print(f"  Quality issues on first pass: {len(issues)} — issuing 1 corrective retry.")
        for i in issues:
            print(f"    - {i}")

        corrective_prompt = (
            user_prompt
            + "\n\n## CORRECTIVE RETRY (Agent C internal, NOT an Agent D retry):\n"
            "Your previous output failed these v2 quality checks. Fix all of them. "
            "Do not regenerate from scratch — carry forward what worked.\n"
            + "\n".join(f"  - {i}" for i in issues)
        )
        result_retry = call_llm(prompt=corrective_prompt, system=system_prompt,
                                model=model, max_tokens=max_tokens, expect_json=True)

        if isinstance(result_retry, dict) and "_failure" not in result_retry:
            remaining = _evaluate_quality(result_retry)
            if not remaining:
                print("  Corrective retry passed all quality checks.")
                result = result_retry
            else:
                print(f"  Corrective retry still has {len(remaining)} issues — accepting best effort.")
                result = result_retry
                result["_quality_issues_remaining"] = remaining

    # ---- 6. Attach metadata for Agent D + main.py ----
    result["_metadata"] = {
        "agent": "C",
        "version": "2.0",
        "company": company_name,
        "intel_source": intel.get("_metadata", {}),
        "tokens_est": est_tokens,
        "external_retry_attempt": int(retry_feedback.get("attempt", 1)) if retry_feedback else 1,
        "model": model,
        "generated_at": datetime.datetime.now().isoformat(),
    }

    # ---- 7. Compute retry_needed signal for downstream consumers ----
    # After internal corrective retry, surface unresolved issues as retry_needed=True.
    # Agent D / main.py may also independently decide to trigger an external retry.
    final_issues = _evaluate_quality(result)
    result["retry_needed"]  = bool(final_issues)
    result["retry_reasons"] = final_issues

    # ---- 8. Console summary ----
    cov  = result.get("keyword_coverage") or {}
    cl   = result.get("customization_layer") or {}
    hc   = result.get("honesty_check") or {}
    tcv  = (hc.get("time_claims_verified") or {})
    bws  = (hc.get("banned_words_scan") or {})
    refs = (result.get("tailoring_notes") or {}).get("agent_b_references") or []

    print(
        f"\n  Customisation: {cl.get('total_change_percentage', '?')}% "
        f"| Coverage: {cov.get('coverage_rate', '?')}% "
        f"({len(cov.get('found_in_resume', []))}/{len(cov.get('required', []))})"
    )
    print(
        f"    honesty:           facts_invented={hc.get('any_facts_invented')}  "
        f"exaggerated={hc.get('any_experiences_exaggerated')}"
    )
    print(
        f"    time_claims:       each_verified={tcv.get('each_verified')}  "
        f"({len(tcv.get('claims_found', []))} claims)"
    )
    print(
        f"    banned_words:      violations={len(bws.get('violations_found', []))}  "
        f"replacements={len(bws.get('replacements_made', []))}"
    )
    print(f"    agent_b_refs:      {len(refs)} quotes")

    if result["retry_needed"]:
        print(f"  retry_needed=True -> {'; '.join(final_issues[:3])}")
    else:
        print("  retry_needed=False (all v2 quality checks passed)")

    return result


# ----------------------------------------------------------------
# Persistence (v2 schema — adds {slug}_customization_layer.json)
# ----------------------------------------------------------------
def save_outputs(result: dict, output_dir: str = None) -> dict:
    """
    Save Agent C v2 outputs to disk.

    Files produced:
      output/{slug}_resume.md
      output/{slug}_cover_letter.md
      output/{slug}_customization_layer.json   (new in v2)
      output/{slug}_tailoring_notes.json

    Returns:
      {"resume_path": ..., "cover_letter_path": ..., "customization_layer_path": ...,
       "notes_path": ..., "retry_needed": ..., "retry_reasons": [...]}
    """
    if "_failure" in result:
        print(f"  Skipping save — agent failed: {result.get('_failure')}")
        return {}

    output_dir = output_dir or PATHS.get("output_dir", "output/")
    os.makedirs(output_dir, exist_ok=True)

    company = result.get("_metadata", {}).get("company", "unknown")
    slug = _safe_filename(company)

    resume_path  = os.path.join(output_dir, f"{slug}_resume.md")
    letter_path  = os.path.join(output_dir, f"{slug}_cover_letter.md")
    layer_path   = os.path.join(output_dir, f"{slug}_customization_layer.json")
    notes_path   = os.path.join(output_dir, f"{slug}_tailoring_notes.json")

    # Resume + cover letter
    with open(resume_path, "w", encoding="utf-8") as f:
        f.write(result.get("tailored_resume", ""))
    with open(letter_path, "w", encoding="utf-8") as f:
        f.write(result.get("cover_letter", ""))

    # Customization layer (new in v2) — surfaced as its own file so users can see
    # exactly what was changed without parsing the larger notes blob.
    customization_layer = result.get("customization_layer", {}) or {}
    with open(layer_path, "w", encoding="utf-8") as f:
        json.dump({
            "customization_layer": customization_layer,
            "_metadata":           result.get("_metadata", {}),
        }, f, indent=2, ensure_ascii=False)

    # Tailoring notes — bundles keyword_coverage, honesty_check, agent_b_refs, retry signal.
    keyword_coverage = result.get("keyword_coverage", {}) or {}
    honesty_check    = result.get("honesty_check",    {}) or {}
    tailoring_notes  = result.get("tailoring_notes",  {}) or {}

    notes_payload = {
        "tailoring_notes":  tailoring_notes,
        "keyword_coverage": keyword_coverage,    # surfaced top-level for Agent D
        "honesty_check":    honesty_check,       # surfaced top-level for Agent D + reviewer
        "retry_needed":     result.get("retry_needed", False),
        "retry_reasons":    result.get("retry_reasons", []),
        "_metadata":        result.get("_metadata", {}),
    }
    with open(notes_path, "w", encoding="utf-8") as f:
        json.dump(notes_payload, f, indent=2, ensure_ascii=False)

    # Console summary
    print(f"  Saved resume:                {resume_path}")
    print(f"  Saved cover letter:          {letter_path}")
    print(f"  Saved customization_layer:   {layer_path}")
    print(f"  Saved tailoring notes:       {notes_path}")

    return {
        "resume_path":              resume_path,
        "cover_letter_path":        letter_path,
        "customization_layer_path": layer_path,
        "notes_path":               notes_path,
        "retry_needed":             result.get("retry_needed", False),
        "retry_reasons":            result.get("retry_reasons", []),
    }


# ----------------------------------------------------------------
# CLI test entry — uses brix v2 intel
# ----------------------------------------------------------------
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    intel_dir   = PATHS.get("intel_data", "data/intel/")
    intel_path  = os.path.join(intel_dir, "brix_v2.json")
    jd_path     = os.path.join("data/jds", "brix.txt")

    if not os.path.isfile(intel_path) or not os.path.isfile(jd_path):
        print("Cannot run Agent C v2 test — missing input files:")
        for p in (intel_path, jd_path):
            print(f"  - {'OK ' if os.path.isfile(p) else 'MISSING '}{p}")
        sys.exit(1)

    jd_text = _load_text_file(jd_path)

    print("Agent C v2 — Resume Tailor (test run on brix_v2 intel)")
    result = run_agent_c(jd_text=jd_text, intel_json=intel_path)

    if result and "_failure" not in result:
        save_outputs(result)
        print("\n--- customization_layer summary ---")
        print(json.dumps(result.get("customization_layer", {}), indent=2, ensure_ascii=False)[:1500])
    else:
        print("\nAgent C failed:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    print_usage()
