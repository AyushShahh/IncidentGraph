"""Prompts package for Stage 4 Autonomous Investigation Agent."""
from backend.agent.prompts.planner import PLANNER_SYSTEM_PROMPT, build_planner_user_prompt
from backend.agent.prompts.hypothesis import HYPOTHESIS_SYSTEM_PROMPT, build_hypothesis_user_prompt
from backend.agent.prompts.reviewer import REVIEWER_SYSTEM_PROMPT, build_reviewer_user_prompt
from backend.agent.prompts.report import REPORT_SYSTEM_PROMPT, build_report_user_prompt

__all__ = [
    "PLANNER_SYSTEM_PROMPT",
    "build_planner_user_prompt",
    "HYPOTHESIS_SYSTEM_PROMPT",
    "build_hypothesis_user_prompt",
    "REVIEWER_SYSTEM_PROMPT",
    "build_reviewer_user_prompt",
    "REPORT_SYSTEM_PROMPT",
    "build_report_user_prompt",
]
