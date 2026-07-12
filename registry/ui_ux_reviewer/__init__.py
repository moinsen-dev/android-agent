"""UI/UX Reviewer skill — structured UI/UX review of an Android app."""

from pathlib import Path

from gitd.skills.base import Skill

_SKILL_DIR = Path(__file__).parent


def load() -> Skill:
    """Load the UI/UX reviewer skill."""
    from gitd.skills._review_common.actions.core import CollectScreenshotsAndTrees, RunLlmReview
    from gitd.skills.ui_ux_reviewer.workflows.review_ui_ux import ReviewUiUx

    skill = Skill(_SKILL_DIR)
    skill.register_action(CollectScreenshotsAndTrees)
    skill.register_action(RunLlmReview)
    skill.register_workflow(ReviewUiUx)
    return skill
