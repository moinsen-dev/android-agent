"""Tests for the review skills (static loading only)."""

from gitd.skills._review_common import load as load_review_common
from gitd.skills.logic_reviewer import load as load_logic_reviewer
from gitd.skills.ui_ux_reviewer import load as load_ui_ux_reviewer


class TestReviewCommon:
    def test_shared_actions_load(self):
        skill = load_review_common()
        assert skill.name == "_review_common"
        assert "collect_screenshots_and_trees" in skill.list_actions()
        assert "run_llm_review" in skill.list_actions()
        assert skill.list_workflows() == []


class TestUiUxReviewer:
    def test_skill_loads(self):
        skill = load_ui_ux_reviewer()
        assert skill.name == "ui_ux_reviewer"
        assert "collect_screenshots_and_trees" in skill.list_actions()
        assert "run_llm_review" in skill.list_actions()
        assert "review_ui_ux" in skill.list_workflows()

    def test_workflow_steps(self):
        from gitd.bots.common.adb import Device
        from gitd.skills.ui_ux_reviewer.workflows.review_ui_ux import ReviewUiUx

        wf = ReviewUiUx(Device("fake-serial"), {}, app_package="com.example.app", steps=5)
        steps = wf.steps()
        assert len(steps) == 2
        assert steps[0].name == "collect_screenshots_and_trees"
        assert steps[1].name == "run_llm_review"


class TestLogicReviewer:
    def test_skill_loads(self):
        skill = load_logic_reviewer()
        assert skill.name == "logic_reviewer"
        assert "collect_screenshots_and_trees" in skill.list_actions()
        assert "run_llm_review" in skill.list_actions()
        assert "review_logic" in skill.list_workflows()

    def test_workflow_steps(self):
        from gitd.bots.common.adb import Device
        from gitd.skills.logic_reviewer.workflows.review_logic import ReviewLogic

        wf = ReviewLogic(Device("fake-serial"), {}, app_package="com.example.app", steps=5)
        steps = wf.steps()
        assert len(steps) == 2
        assert steps[0].name == "collect_screenshots_and_trees"
        assert steps[1].name == "run_llm_review"
