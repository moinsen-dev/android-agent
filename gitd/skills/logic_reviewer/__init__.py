"""Logic Reviewer skill — structured logic/feature review of an Android app."""

from pathlib import Path

from gitd.skills.base import Skill

_SKILL_DIR = Path(__file__).parent


def load() -> Skill:
    """Load the logic reviewer skill."""
    from gitd.skills._review_common.actions.core import CollectScreenshotsAndTrees, RunLlmReview
    from gitd.skills.logic_reviewer.workflows.review_logic import ReviewLogic

    skill = Skill(_SKILL_DIR)
    skill.register_action(CollectScreenshotsAndTrees)
    skill.register_action(RunLlmReview)
    skill.register_workflow(ReviewLogic)
    return skill
