"""
Agent D: Application Validator + Interview Probability Analyst v2

Two core jobs:
  1. VALIDATE — strict HR-side review of resume + cover letter (was v1's only job).
  2. ASSESS  — interview probability estimation + gap analysis + preparation plan
              (moved here from Agent C as part of the v2 architecture correction).

Pipeline: Agent C (Tailor) -> [Agent D: Validator] -> Agent E (CRM)
                                                 |
                                                 +-> retry -> Agent C
"""
import json
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm import call_llm, print_usage
from config import LLM_CONFIG, PATHS
from prompts.agent_d_prompt import build_agent_d_system_prompt, AGENT_D_USER_TEMPLATE


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def _safe_filename(name: str) -> str:
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
    if isinstance(intel_input, dict):
        return intel_input
    if isinstance(intel_input, str) and os.path.isfile(intel_input):
        with open(intel_input, "r", encoding="utf-8") as f:
            return json.load(f)
    raise ValueError("intel_json must be a dict or a path to a saved intel JSON file.")


def _load_customization_layer(payload):
    """Accept dict (already-loaded), str path, or None. Returns dict or None."""
    if payload is None:
        return None
    if isinstance(payload, dict):
        # Saved layers wrap the actual data under 'customization_layer'; unwrap if present.
        return payload.get("customization_layer", payload)
    if isinstance(payload, str) and os.path.isfile(payload):
        with open(payload, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("customization_layer", data)
    return None


# ----------------------------------------------------------------
# Output quality validation (v2 — expanded for assessment_report)
# ----------------------------------------------------------------
INTERVIEW_Q_MIN, INTERVIEW_Q_MAX = 8, 12


def _validate_output_quality(result: dict) -> list:
    """Static structural checks on Agent D's output. Returns issues list (empty = clean)."""
    issues = []
    if not isinstance(result, dict):
        return ["result is not a dict"]

    # ---- ats_analysis ----
    ats = result.get("ats_analysis", {}) or {}
    if "score" in ats:
        # v1 bug-fix: score must NOT exist. coverage_rate is the single ATS metric.
        # We will pop it in the orchestrator; flag it here so the model learns.
        issues.append("ats_analysis.score must not exist in v2 — only coverage_rate is allowed.")
    cov = ats.get("coverage_rate")
    ats_verdict = ats.get("verdict")
    if not isinstance(cov, (int, float)):
        issues.append("ats_analysis.coverage_rate missing or non-numeric.")
    elif ats_verdict in ("PASS", "MARGINAL", "FAIL"):
        expected = "PASS" if cov >= 70 else ("MARGINAL" if cov >= 50 else "FAIL")
        if ats_verdict != expected:
            issues.append(
                f"ats_analysis.verdict ({ats_verdict}) disagrees with coverage_rate ({cov}%); "
                f"expected {expected} per verdict_logic."
            )

    # ---- hr_simulation ----
    hr = result.get("hr_simulation", {}) or {}
    rejection_reasons = hr.get("rejection_reasons") or []
    if len(rejection_reasons) < 3:
        issues.append(f"hr_simulation.rejection_reasons has {len(rejection_reasons)} items (>=3 required).")

    # ---- pipeline_control ----
    pc = result.get("pipeline_control", {}) or {}
    retry_needed = bool(pc.get("retry_needed"))
    rd = pc.get("retry_direction", {}) or {}
    priority_fixes = rd.get("priority_fixes") or []
    if retry_needed and len(priority_fixes) < 2:
        issues.append(f"retry_needed=true but priority_fixes has {len(priority_fixes)} items (>=2 required).")

    # ---- interview_questions ----
    questions = result.get("interview_questions") or []
    if not (INTERVIEW_Q_MIN <= len(questions) <= INTERVIEW_Q_MAX):
        issues.append(f"interview_questions count is {len(questions)} (must be {INTERVIEW_Q_MIN}-{INTERVIEW_Q_MAX}).")
    types = [q.get("type", "") for q in questions]
    n_tech, n_beh, n_co = (sum(1 for t in types if t == k)
                           for k in ("technical", "behavioral", "company_specific"))
    if n_tech < 3:
        issues.append(f"only {n_tech} technical interview questions (>=3 required).")
    if n_beh < 2:
        issues.append(f"only {n_beh} behavioral interview questions (>=2 required).")
    if n_co < 1:
        issues.append(f"only {n_co} company_specific interview questions (>=1 required).")

    # ---- verdict consistency check ----
    hr_verdict = hr.get("verdict")
    if isinstance(cov, (int, float)) and hr_verdict in ("A", "B", "C"):
        if cov >= 80 and hr_verdict == "C" and not result.get("verdict_consistency_check"):
            issues.append("ATS coverage>=80 but HR verdict=C: verdict_consistency_check must be populated.")
        if cov < 50 and hr_verdict == "A" and not result.get("verdict_consistency_check"):
            issues.append("ATS coverage<50 but HR verdict=A: verdict_consistency_check must be populated.")

    # ---- assessment_report ----
    ar = result.get("assessment_report", {}) or {}
    ip = ar.get("interview_probability", {}) or {}
    ds = ip.get("dimension_scores", {}) or {}
    expected_dims = ("technical_match", "culture_match", "ats_probability",
                     "experience_match", "competitiveness")
    for d in expected_dims:
        if d not in ds:
            issues.append(f"interview_probability.dimension_scores.{d} missing.")
        else:
            inner = ds[d] or {}
            if not isinstance(inner.get("score"), (int, float)):
                issues.append(f"dimension_scores.{d}.score missing or non-numeric.")
    # Validate weighted_total math when all dims present
    if all(d in ds and isinstance(ds[d].get("score"), (int, float)) for d in expected_dims):
        weights = {"technical_match": 0.30, "culture_match": 0.20, "ats_probability": 0.20,
                   "experience_match": 0.15, "competitiveness": 0.15}
        expected_wt = round(sum(ds[d]["score"] * weights[d] for d in expected_dims))
        actual_wt = ip.get("weighted_total")
        if isinstance(actual_wt, (int, float)) and abs(actual_wt - expected_wt) > 2:
            issues.append(
                f"weighted_total ({actual_wt}) disagrees with dimension scores "
                f"(expected approx {expected_wt})."
            )
        # Band consistency
        overall = ip.get("overall")
        if isinstance(actual_wt, (int, float)) and overall in ("HIGH", "MEDIUM", "LOW"):
            expected_band = "HIGH" if actual_wt >= 75 else ("MEDIUM" if actual_wt >= 55 else "LOW")
            if overall != expected_band:
                issues.append(
                    f"interview_probability.overall ({overall}) disagrees with "
                    f"weighted_total {actual_wt} (expected {expected_band})."
                )

    if not ip.get("disclaimer"):
        issues.append("interview_probability.disclaimer missing — required to flag uncertainty.")

    gaps = ar.get("gap_analysis") or []
    if len(gaps) < 3:
        issues.append(f"assessment_report.gap_analysis has {len(gaps)} rows (>=3 required).")

    pp = ar.get("preparation_plan", {}) or {}
    for sub, label in (("before_application", "before_application"),
                       ("before_interview",   "before_interview"),
                       ("technical_prep",     "technical_prep"),
                       ("behavioral_prep",    "behavioral_prep"),
                       ("company_research",   "company_research")):
        items = pp.get(sub) or []
        if len(items) < 2:
            issues.append(f"preparation_plan.{label} has {len(items)} items (>=2 required).")

    # ---- customization_audit ----
    ca = result.get("customization_audit", {}) or {}
    if ca.get("fabrication_detected") is True and not retry_needed:
        issues.append("fabrication_detected=true but retry_needed=false (must be coupled).")
    if ca.get("banned_words_found") and not retry_needed:
        issues.append("banned_words_found is non-empty but retry_needed=false (must be coupled).")

    # ---- prediction_record ----
    pr = result.get("prediction_record", {}) or {}
    if not pr.get("company"):
        issues.append("prediction_record.company missing.")
    if "actual_result" not in pr:
        issues.append("prediction_record.actual_result missing (must exist as null).")
    elif pr.get("actual_result") is not None:
        issues.append("prediction_record.actual_result must be null at evaluation time.")

    return issues


# ----------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------
def run_agent_d(tailored_resume: str,
                cover_letter: str,
                jd_text: str,
                intel_json,
                customization_layer=None) -> dict:
    """
    Run Agent D v2.

    Args:
        tailored_resume:     Agent C's tailored resume markdown.
        cover_letter:        Agent C's cover letter markdown.
        jd_text:             Original job description.
        intel_json:          Agent B output (dict or path to a saved JSON).
        customization_layer: Optional Agent C v2 customization_layer (dict or path to layer JSON).
                             Enables Module 3 (customization audit). When None, Module 3 still
                             runs but only via independent diff.

    Returns:
        On success:
          {
            "hr_verdict":         "A|B|C",
            "ats_coverage":       int,
            "retry_needed":       bool,
            "retry_direction":    {...},
            "interview_questions": [...],
            "assessment_report":  {...},
            "prediction_record":  {...},
            "customization_audit": {...},
            "full_validation":    <full Agent D response>,
            "_metadata":          {...}
          }
        On hard failure:
          {"error": "FORMAT_ERROR" | "INSUFFICIENT_INFO" | ..., "message": "..."}
    """
    # ---- 1. Code-layer input validation (BEFORE any API call) ----
    if not tailored_resume or len(tailored_resume.strip()) < 100:
        return {"error": "FORMAT_ERROR", "field": "tailored_resume",
                "message": "Resume is empty or shorter than 100 chars."}
    if not cover_letter or len(cover_letter.strip()) < 50:
        return {"error": "FORMAT_ERROR", "field": "cover_letter",
                "message": "Cover letter is empty or shorter than 50 chars."}
    if not jd_text or len(jd_text.split()) < 100:
        return {"error": "INSUFFICIENT_INFO", "field": "jd_text",
                "message": "JD has fewer than 100 words; not enough signal to evaluate."}

    intel = _load_intel(intel_json)
    cl    = _load_customization_layer(customization_layer)

    company_name = (
        intel.get("company_profile", {}).get("name")
        or intel.get("_metadata", {}).get("company")
        or "unknown"
    )

    print(f"\n{'='*60}")
    print(f"Agent D v2: Validating + assessing application for {company_name}")
    print(f"{'='*60}")
    if cl:
        print(f"  customization_layer: provided "
              f"(claimed total_change_percentage={cl.get('total_change_percentage', '?')}%)")
    else:
        print("  customization_layer: not provided — Module 3 runs in independent-diff mode")

    # ---- 2. Defence-in-depth: strip forbidden intel fields before sending to LLM ----
    intel_for_prompt = {k: v for k, v in intel.items() if k != "match_assessment"}
    # cover_letter_hook was Agent C's input, not Agent D's
    if "resume_strategy" in intel_for_prompt and isinstance(intel_for_prompt["resume_strategy"], dict):
        rs = dict(intel_for_prompt["resume_strategy"])
        rs.pop("cover_letter_hook", None)
        intel_for_prompt["resume_strategy"] = rs

    # ---- 3. Build prompt ----
    system_prompt = build_agent_d_system_prompt()
    cl_repr = json.dumps(cl, ensure_ascii=False, indent=2) if cl else "(not provided)"

    def _build_user_prompt(jd_cap=4000, intel_cap=7000, resume_cap=5000, letter_cap=3000, cl_cap=3000):
        return AGENT_D_USER_TEMPLATE.format(
            company_name=company_name,
            jd_text=jd_text[:jd_cap],
            intel_json=json.dumps(intel_for_prompt, ensure_ascii=False, indent=2)[:intel_cap],
            tailored_resume=tailored_resume[:resume_cap],
            cover_letter=cover_letter[:letter_cap],
            customization_layer=cl_repr[:cl_cap],
        )

    user_prompt = _build_user_prompt()
    est_tokens = (len(system_prompt) + len(user_prompt)) // 4
    print(f"  Input: ~{est_tokens} tokens")
    if est_tokens > 14000:
        print("  Truncating to fit token budget...")
        user_prompt = _build_user_prompt(jd_cap=3000, intel_cap=5000, resume_cap=4000,
                                         letter_cap=2500, cl_cap=2000)

    # ---- 4. Call LLM ----
    model = LLM_CONFIG.get("validator_model", LLM_CONFIG.get("intel_model"))
    max_tokens = LLM_CONFIG.get("max_tokens", 4096)
    print(f"  Calling {model} (max_tokens={max_tokens})...")

    result = call_llm(prompt=user_prompt, system=system_prompt,
                      model=model, max_tokens=max_tokens, expect_json=True)

    if result is None:
        return {"error": "LLM_RETURNED_NONE", "company": company_name}
    if isinstance(result, dict) and "_failure" in result:
        return {"error": result["_failure"], "company": company_name, "raw": result}

    # ---- 5. Defence: strip any leaked 'score' field from ats_analysis ----
    if isinstance(result.get("ats_analysis"), dict) and "score" in result["ats_analysis"]:
        leaked = result["ats_analysis"].pop("score")
        print(f"  Defence: stripped leaked ats_analysis.score={leaked} (v1 bug shouldn't return)")

    # ---- 6. Defence: couple fabrication/banned_words to retry_needed ----
    ca = result.get("customization_audit", {}) or {}
    pc = result.setdefault("pipeline_control", {})
    if ca.get("fabrication_detected") is True or (ca.get("banned_words_found") or []):
        if pc.get("retry_needed") is not True:
            print("  Defence: forcing retry_needed=true because fabrication or banned words found.")
            pc["retry_needed"] = True
            rd = pc.setdefault("retry_direction", {})
            existing_fixes = list(rd.get("priority_fixes") or [])
            if ca.get("fabrication_detected"):
                existing_fixes.append(
                    f"[FABRICATION] {ca.get('fabrication_details', 'fabricated content detected')} "
                    "-> remove the unsupported claim and rely on transferable evidence instead"
                )
            for bw in (ca.get("banned_words_found") or []):
                term = bw if isinstance(bw, str) else bw.get("term", str(bw))
                existing_fixes.append(
                    f"[BANNED_WORD] '{term}' present in resume/cover_letter "
                    "-> replace with a plain alternative (use 'use' for 'leverage', etc.)"
                )
            rd["priority_fixes"] = existing_fixes[:6]
            rd.setdefault("specific_instructions",
                          "Remove fabricated/banned content; keep all other parts of the package.")
            rd.setdefault("sections_to_change", [])

    # ---- 7. Quality check + one corrective retry ----
    issues = _validate_output_quality(result)
    if issues:
        print(f"  Quality issues: {len(issues)} — issuing one corrective retry.")
        for i in issues:
            print(f"    - {i}")
        retry_prompt = (
            user_prompt
            + "\n\n## CORRECTIVE RETRY:\nYour previous output failed these structural checks. "
            "Fix all of them. Do not regenerate from scratch — carry forward what worked.\n"
            + "\n".join(f"  - {i}" for i in issues)
        )
        result_retry = call_llm(prompt=retry_prompt, system=system_prompt,
                                model=model, max_tokens=max_tokens, expect_json=True)
        if isinstance(result_retry, dict) and "_failure" not in result_retry:
            # Re-apply defence steps to the retry
            if isinstance(result_retry.get("ats_analysis"), dict) and "score" in result_retry["ats_analysis"]:
                result_retry["ats_analysis"].pop("score")
            remaining = _validate_output_quality(result_retry)
            if not remaining:
                print("  Corrective retry passed all quality checks.")
                result = result_retry
            else:
                print(f"  Corrective retry still has {len(remaining)} issues — accepting best version.")
                result = result_retry
                result["_quality_issues_remaining"] = remaining

    # ---- 8. Attach metadata ----
    result["_metadata"] = {
        "agent": "D",
        "version": "2.0",
        "company": company_name,
        "intel_source": intel.get("_metadata", {}),
        "tokens_est": est_tokens,
        "model": model,
        "customization_layer_provided": cl is not None,
        "generated_at": datetime.datetime.now().isoformat(),
    }

    # ---- 9. Console summary ----
    hr  = result.get("hr_simulation", {}) or {}
    ats = result.get("ats_analysis", {}) or {}
    pc  = result.get("pipeline_control", {}) or {}
    ar  = result.get("assessment_report", {}) or {}
    ip  = ar.get("interview_probability", {}) or {}
    print(
        f"\n  HR verdict:   {hr.get('verdict', '?')} | "
        f"ATS coverage: {ats.get('coverage_rate', '?')}% ({ats.get('verdict', '?')}) | "
        f"retry_needed: {pc.get('retry_needed', '?')}"
    )
    print(
        f"  Probability:  {ip.get('overall', '?')} ({ip.get('estimated_range', '?')}) | "
        f"weighted_total={ip.get('weighted_total', '?')}"
    )
    cau = result.get("customization_audit", {}) or {}
    print(
        f"  Audit:        fabrication={cau.get('fabrication_detected', '?')} | "
        f"banned_words={len(cau.get('banned_words_found', []))} | "
        f"over={cau.get('over_customized', '?')} under={cau.get('under_customized', '?')}"
    )

    # ---- 10. Return shape designed for main.py / Agent E consumption ----
    return {
        "hr_verdict":          hr.get("verdict"),
        "ats_coverage":        ats.get("coverage_rate"),
        "retry_needed":        bool(pc.get("retry_needed")),
        "retry_direction":     pc.get("retry_direction", {}),
        "interview_questions": result.get("interview_questions", []),
        "assessment_report":   ar,
        "prediction_record":   result.get("prediction_record", {}),
        "customization_audit": cau,
        "full_validation":     result,
        "_metadata":           result["_metadata"],
    }


# ----------------------------------------------------------------
# Persistence (v2 — three files: validation, assessment_report, prediction_record)
# ----------------------------------------------------------------
def save_validation(result: dict, output_dir: str = None) -> dict:
    """Save the full validation report + standalone assessment + prediction record."""
    if "error" in result and "full_validation" not in result:
        print(f"  Skipping save — agent failed: {result.get('error')}")
        return {}

    output_dir = output_dir or PATHS.get("output_dir", "output/")
    os.makedirs(output_dir, exist_ok=True)

    company = (result.get("_metadata", {}) or {}).get("company") \
              or (result.get("full_validation", {}) or {}).get("_metadata", {}).get("company") \
              or "unknown"
    slug = _safe_filename(company)

    full_path       = os.path.join(output_dir, f"{slug}_validation.json")
    assessment_path = os.path.join(output_dir, f"{slug}_assessment_report.json")
    prediction_path = os.path.join(output_dir, f"{slug}_prediction_record.json")

    payload = result.get("full_validation", result)
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # Standalone assessment report — easy for the human to skim post-validation
    assessment = payload.get("assessment_report", {}) or {}
    with open(assessment_path, "w", encoding="utf-8") as f:
        json.dump({
            "assessment_report": assessment,
            "_metadata": payload.get("_metadata", {}),
        }, f, indent=2, ensure_ascii=False)

    # Standalone prediction record — append-able log for future calibration analysis
    prediction = payload.get("prediction_record", {}) or {}
    with open(prediction_path, "w", encoding="utf-8") as f:
        json.dump(prediction, f, indent=2, ensure_ascii=False)

    print(f"  Saved validation:        {full_path}")
    print(f"  Saved assessment_report: {assessment_path}")
    print(f"  Saved prediction_record: {prediction_path}")

    return {
        "validation_path":        full_path,
        "assessment_report_path": assessment_path,
        "prediction_record_path": prediction_path,
    }


# ----------------------------------------------------------------
# CLI test entry — uses brix v3 outputs by default
# ----------------------------------------------------------------
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    output_dir = PATHS.get("output_dir", "output/")
    intel_dir  = PATHS.get("intel_data", "data/intel/")
    jd_dir     = "data/jds"

    # Prefer v3 brix outputs (Agent C v2 product); fall back to v1 if missing.
    candidate_files = [
        ("brix_v3", os.path.join(output_dir, "brix_v3_resume.md"),
                    os.path.join(output_dir, "brix_v3_cover_letter.md"),
                    os.path.join(output_dir, "brix_v3_customization_layer.json"),
                    os.path.join(intel_dir, "brix_v2.json"),
                    os.path.join(jd_dir, "brix.txt")),
        ("brix",    os.path.join(output_dir, "brix_resume.md"),
                    os.path.join(output_dir, "brix_cover_letter.md"),
                    None,
                    os.path.join(intel_dir, "brix.json"),
                    os.path.join(jd_dir, "brix.txt")),
    ]
    chosen = None
    for tag, r, l, c, i, j in candidate_files:
        if os.path.isfile(r) and os.path.isfile(l) and os.path.isfile(i) and os.path.isfile(j):
            chosen = (tag, r, l, c, i, j)
            break

    if chosen is None:
        print("Cannot run Agent D v2 test — no brix output set found.")
        sys.exit(1)

    tag, r_path, l_path, c_path, i_path, j_path = chosen
    print(f"Agent D v2 — Application Validator (test set: {tag})")
    print(f"  resume:     {r_path}")
    print(f"  letter:     {l_path}")
    print(f"  cust_layer: {c_path if c_path else '(none)'}")
    print(f"  intel:      {i_path}")
    print(f"  jd:         {j_path}")

    tailored_resume = _load_text_file(r_path)
    cover_letter    = _load_text_file(l_path)
    jd_text         = _load_text_file(j_path)
    cl              = c_path if c_path and os.path.isfile(c_path) else None

    out = run_agent_d(tailored_resume, cover_letter, jd_text, i_path,
                      customization_layer=cl)

    if "error" in out and "full_validation" not in out:
        print("\nAgent D failed:")
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        # Save under tag-specific filenames (e.g. brix_v3_validation.json)
        # by overriding the metadata company name to match the tag.
        out["_metadata"]["company"] = tag
        out["full_validation"]["_metadata"]["company"] = tag
        save_validation(out)
        print("\n--- Headline summary ---")
        ip = (out.get("assessment_report", {}) or {}).get("interview_probability", {}) or {}
        print(json.dumps({
            "hr_verdict":            out.get("hr_verdict"),
            "ats_coverage":          out.get("ats_coverage"),
            "interview_probability": ip.get("overall"),
            "estimated_range":       ip.get("estimated_range"),
            "weighted_total":        ip.get("weighted_total"),
            "retry_needed":          out.get("retry_needed"),
            "n_questions":           len(out.get("interview_questions", [])),
            "n_gaps":                len((out.get("assessment_report") or {}).get("gap_analysis", [])),
        }, indent=2, ensure_ascii=False))

    print_usage()
