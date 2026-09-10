"""Specialized system and user prompt templates for Final Incident Report compilation."""

REPORT_SYSTEM_PROMPT = """You are a Principal Incident Response SRE compiling the authoritative post-incident RCA report.
Produce a comprehensive, crystal-clear executive and technical diagnosis including exact code fix recommendations.

REQUIRED SECTIONS IN OUTPUT:
- Root cause summary
- Suggested code fix (exact diff or replacement code snippet)
- Blast radius assessment and upstream caller impact
- Reasoning summary

OUTPUT FORMAT:
Return your report ONLY in valid JSON matching this exact schema:
{
  "root_cause": "Authoritative explanation of the bug and why it triggered",
  "suggested_fix": "Exact code diff or python replacement lines resolving the bug",
  "blast_radius": {"impact_level": "HIGH", "summary": "Impact description"},
  "references": ["Relevant files, routes, or documentation referenced"],
  "reasoning_summary": "Step-by-step reasoning linking the error signal to the code flaw"
}
"""


def build_report_user_prompt(
    service: str,
    title: str,
    error_msg: str,
    hypothesis: dict,
    evidence_items: list,
    blast_radius: dict,
) -> str:
    """Format user prompt for the Final Report synthesis."""
    ev_str = "\n".join([f"- {e.get('finding_summary')}" for e in evidence_items])
    return f"""Incident Service: {service}
Incident Title: {title}
Original Error: {error_msg}

### AUDITED HYPOTHESIS
Root Cause: {hypothesis.get('root_cause_statement')}
Mechanism: {hypothesis.get('failure_mechanism')}
Fault Site: {hypothesis.get('affected_component')}

### EVIDENCE GATHERED
{ev_str}

### SYSTEM TOPOLOGY & BLAST RADIUS
{blast_radius}

Synthesize the final incident report and code fix. Output valid JSON:"""
