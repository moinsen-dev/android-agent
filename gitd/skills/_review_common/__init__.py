"""Shared review actions — exploration + LLM report generation."""

from pathlib import Path

from gitd.skills.base import Skill

_SKILL_DIR = Path(__file__).parent


def load() -> Skill:
    """Load the shared review actions (no workflows)."""
    from gitd.skills._review_common.actions.core import CollectScreenshotsAndTrees, RunLlmReview

    skill = Skill(_SKILL_DIR)
    skill.register_action(CollectScreenshotsAndTrees)
    skill.register_action(RunLlmReview)
    return skill
