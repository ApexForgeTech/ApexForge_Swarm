"""
Mission templates for ApexForge Swarm.
Pre-configured supervisor + worker teams for common task types.
"""
from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {
    "code_review": {
        "supervisor": {"role": "Senior Code Reviewer"},
        "workers": [
            {"role": "Security Analyst — identify vulnerabilities, auth issues, injection risks, secrets in code"},
            {"role": "Architecture Reviewer — evaluate structure, coupling, design patterns, scalability"},
            {"role": "Test Coverage Analyst — assess missing tests, test quality, edge cases"},
        ],
        "hint": "Read the full code carefully. Prioritize critical issues. Give specific, actionable fix suggestions.",
        "description": "Security + Architecture + Test Coverage analysts review the codebase.",
    },
    "research": {
        "supervisor": {"role": "Research Lead"},
        "workers": [
            {"role": "Web Researcher — find current information, authoritative sources, links, numbers"},
            {"role": "Analyst — synthesize findings, identify patterns, draw conclusions"},
            {"role": "Fact Checker — verify claims, flag contradictions, assess source quality"},
        ],
        "hint": "Research thoroughly, verify claims, structure the final output clearly with sources.",
        "description": "Web Researcher + Analyst + Fact Checker for deep topic research.",
    },
    "repo_audit": {
        "supervisor": {"role": "Project Architect"},
        "workers": [
            {"role": "Codebase Explorer — map file structure, module boundaries, dependencies, entry points"},
            {"role": "Risk Analyst — identify technical debt, anti-patterns, hidden bugs, security issues"},
            {"role": "Improvement Planner — write specific, prioritized, actionable improvement recommendations"},
        ],
        "hint": "Analyze the full repository. Prioritize findings by severity. Output a structured audit report.",
        "description": "Codebase Explorer + Risk Analyst + Planner for full repository audits.",
    },
    "document_processing": {
        "supervisor": {"role": "Document Analyst"},
        "workers": [
            {"role": "Content Extractor — extract key facts, figures, dates, entities, and data from the document"},
            {"role": "Summarizer — write a concise executive summary for different audience levels"},
            {"role": "Action Item Extractor — identify tasks, decisions, deadlines, and follow-up items"},
        ],
        "hint": "Read the entire document. Each worker focuses on their specific extraction task.",
        "description": "Content Extractor + Summarizer + Action Item Extractor for document analysis.",
    },
    "bug_investigation": {
        "supervisor": {"role": "Lead Debugger"},
        "workers": [
            {"role": "Root Cause Analyst — trace the bug to its origin, identify failing assumptions"},
            {"role": "Impact Assessor — determine affected code paths, users, and severity"},
            {"role": "Fix Designer — propose concrete, minimal, safe fixes with code examples"},
        ],
        "hint": "Reproduce the bug mentally, trace the call path, identify the root cause, propose the minimal fix.",
        "description": "Root Cause + Impact + Fix Designer for systematic bug investigation.",
    },
    "feature_planning": {
        "supervisor": {"role": "Product Architect"},
        "workers": [
            {"role": "Requirements Analyst — clarify scope, edge cases, acceptance criteria, and constraints"},
            {"role": "Technical Designer — design the implementation: data models, APIs, interfaces, dependencies"},
            {"role": "Risk & Effort Estimator — identify risks, blockers, effort estimates, phasing strategy"},
        ],
        "hint": "Define the feature completely before designing. Identify what could go wrong early.",
        "description": "Requirements + Technical Design + Risk Estimation for new feature planning.",
    },
    "data_analysis": {
        "supervisor": {"role": "Data Science Lead"},
        "workers": [
            {"role": "Data Explorer — examine structure, distributions, missing values, outliers in the dataset"},
            {"role": "Statistical Analyst — compute key metrics, correlations, trends, and statistical significance"},
            {"role": "Insight Reporter — translate findings into business-relevant conclusions and visualizations"},
        ],
        "hint": "Use tools to actually examine and compute. Return specific numbers, not generic observations.",
        "description": "Explorer + Statistical Analyst + Reporter for data and dataset analysis.",
    },
}


def get_template(name: str) -> dict[str, Any] | None:
    """Return a template by name, or None if not found."""
    return TEMPLATES.get(name)


def list_templates() -> list[str]:
    """Return all available template names."""
    return list(TEMPLATES.keys())


def describe_templates() -> list[dict[str, str]]:
    """Return name + description for each template."""
    return [
        {"name": name, "description": tmpl["description"]}
        for name, tmpl in TEMPLATES.items()
    ]


def apply_template(
    template_name: str,
    supervisor_override: dict | None = None,
    workers_override: list | None = None,
) -> tuple[dict, list] | None:
    """
    Return (supervisor_data, workers_data) for a template.
    Caller can override supervisor or workers after applying.
    Returns None if template not found.
    """
    tmpl = get_template(template_name)
    if not tmpl:
        return None
    supervisor = dict(supervisor_override or tmpl["supervisor"])
    workers = list(workers_override or tmpl["workers"])
    return supervisor, workers
