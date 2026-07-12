"""Logic Reviewer workflow — full logic/feature review of an Android app."""

from gitd.skills.base import Action, Workflow

LOGIC_PERSONA = """You are a pragmatic product manager and QA lead with 10 years of experience building consumer Android apps.
You review apps for logical consistency and feature completeness.
You care about:
- Does the app do what a reasonable user would expect?
- Are there missing features that are essential for the app's purpose?
- Are flows logically ordered, or do they feel backwards?
- Are there dead ends, contradictory labels, or confusing state changes?
- Does the app ask for permissions or data at the right time?
- Are errors handled gracefully and explained clearly?

Be honest and concrete. Reference specific screens, buttons, or flows from the trace."""

LOGIC_RUBRIC_TEMPLATE = """Based on the exploration trace above, write a structured logic/feature review report in JSON format with exactly these keys:

- summary: a 1-3 sentence overall impression
- overall_score: integer 1-5
- completeness_score: integer 1-5 (does the app have the features expected for its purpose?)
- consistency_score: integer 1-5 (are flows and labels logically consistent?)
- usefulness_score: integer 1-5 (does the app solve a real problem well?)
- app_purpose_inferred: string, the purpose you believe the app is trying to serve
- missing_features: list of strings, features that seem essential but are missing
- logic_issues: list of objects, each with {severity: "low"|"medium"|"high", screen: string, expected_behavior: string, actual_behavior: string, suggestion: string}
- confusing_flows: list of strings, flows that feel out of order or unclear
- top_fixes: list of strings, the highest-impact logic improvements
- verbatim: one sentence you would say to the product team

Return ONLY valid JSON. Do not wrap it in markdown."""


class ReviewLogic(Workflow):
    """Launch app, explore it, and generate a structured logic review."""

    name = "review_logic"
    description = "Full logic/feature review of an Android app"

    def __init__(
        self,
        device,
        elements,
        *,
        app_package: str = "",
        steps: int = 14,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        app_context: str = "",
        **kwargs,
    ):
        super().__init__(device, elements)
        self.app_package = app_package
        self.explore_steps = steps
        self.provider = provider
        self.model = model
        self.app_context = app_context
        self._collect_action = None

    def steps(self) -> list[Action]:
        from gitd.skills._review_common.actions.core import CollectScreenshotsAndTrees, RunLlmReview

        self._collect_action = CollectScreenshotsAndTrees(
            self.device,
            self.elements,
            app_package=self.app_package,
            steps=self.explore_steps,
            prefix="logic_review",
        )

        class _GenerateLogicReport(RunLlmReview):
            def precondition(inner_self) -> bool:
                inner_self.run_dir = getattr(self._collect_action, "run_dir", None)
                inner_self.provider = self.provider
                inner_self.model = self.model
                inner_self.system_prompt = LOGIC_PERSONA
                inner_self.rubric = LOGIC_RUBRIC_TEMPLATE
                inner_self.report_name = "logic_report.json"
                inner_self.extra_context = self.app_context
                return inner_self.run_dir is not None and inner_self.run_dir.exists()

        return [
            self._collect_action,
            _GenerateLogicReport(self.device, self.elements),
        ]
