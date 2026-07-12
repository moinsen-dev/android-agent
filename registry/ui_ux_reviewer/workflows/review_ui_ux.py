"""UI/UX Reviewer workflow — full review of an Android app."""

from gitd.skills.base import Action, Workflow

UI_UX_PERSONA = """You are a senior UI/UX designer whose work has won Apple Design Awards and Google Material Design awards.
You review Android apps from the perspective of an empathetic, everyday user aged 20-35.
You deeply care about:
- Clarity: the user always knows what is happening and what to do next.
- Affordances: interactive things look interactive; static things look static.
- Visual hierarchy: the most important information is prominent and scannable.
- Consistency: typography, colors, spacing, icons, and language feel like one system.
- Feedback: every action produces a visible, understandable response.
- Accessibility: text is readable, touch targets are adequate, contrast is sufficient.
- Emotional tone: the app feels respectful of the user's time and attention.

Be precise, constructive, and honest. Mention concrete screens or elements whenever possible."""

UI_UX_RUBRIC = """Based on the exploration trace above, write a structured UI/UX review report in JSON format with exactly these keys:

- summary: a 1-3 sentence overall impression
- overall_score: integer 1-5
- clarity_score: integer 1-5
- consistency_score: integer 1-5
- hierarchy_score: integer 1-5
- feedback_score: integer 1-5
- accessibility_score: integer 1-5
- strengths: list of strings, things the app does well from a design perspective
- issues: list of objects, each with {severity: "low"|"medium"|"high", screen: string, description: string, principle: string, suggestion: string}
- top_fixes: list of strings, the highest-impact improvements to make
- verbatim: one sentence you would say to the product team in a design review

Return ONLY valid JSON. Do not wrap it in markdown."""


class ReviewUiUx(Workflow):
    """Launch app, explore it, and generate a structured UI/UX review."""

    name = "review_ui_ux"
    description = "Full UI/UX review of an Android app"

    def __init__(
        self,
        device,
        elements,
        *,
        app_package: str = "",
        steps: int = 14,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        **kwargs,
    ):
        super().__init__(device, elements)
        self.app_package = app_package
        self.explore_steps = steps
        self.provider = provider
        self.model = model
        self._collect_action = None

    def steps(self) -> list[Action]:
        from gitd.skills._review_common.actions.core import CollectScreenshotsAndTrees, RunLlmReview

        self._collect_action = CollectScreenshotsAndTrees(
            self.device,
            self.elements,
            app_package=self.app_package,
            steps=self.explore_steps,
            prefix="ui_ux_review",
        )

        # Inner action that pulls the run_dir from the preceding collect action.
        class _GenerateUiUxReport(RunLlmReview):
            def precondition(inner_self) -> bool:
                inner_self.run_dir = getattr(self._collect_action, "run_dir", None)
                inner_self.provider = self.provider
                inner_self.model = self.model
                inner_self.system_prompt = UI_UX_PERSONA
                inner_self.rubric = UI_UX_RUBRIC
                inner_self.report_name = "ui_ux_report.json"
                inner_self.extra_context = ""
                return inner_self.run_dir is not None and inner_self.run_dir.exists()

        return [
            self._collect_action,
            _GenerateUiUxReport(self.device, self.elements),
        ]
