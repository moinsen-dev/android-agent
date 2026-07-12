"""User App Tester skill — simulate a real user exploring an unknown app."""

from pathlib import Path

from gitd.skills.base import Skill

_SKILL_DIR = Path(__file__).parent


def load() -> Skill:
    """Load the user_app_tester skill."""
    from gitd.skills.user_app_tester.actions.core import ExploreApp, GenerateFeedback, OpenApp
    from gitd.skills.user_app_tester.workflows.test_app import TestAppAsUser

    skill = Skill(_SKILL_DIR)
    for cls in [OpenApp, ExploreApp, GenerateFeedback]:
        skill.register_action(cls)
    skill.register_workflow(TestAppAsUser)
    return skill
