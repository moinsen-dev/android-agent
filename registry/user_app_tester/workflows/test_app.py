"""User App Tester workflow — full user-journey test of an unknown app."""

from gitd.skills.base import Action, Workflow

from gitd.skills.user_app_tester.actions.core import ExploreApp, GenerateFeedback, OpenApp


class TestAppAsUser(Workflow):
    """Launch an app, explore it like a first-time user, and generate feedback."""

    name = "test_app_as_user"
    description = "Full user-journey test of an unknown app"

    def __init__(
        self,
        device,
        elements,
        *,
        app_package: str = "",
        steps: int = 12,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        output_path: str = "",
        **kwargs,
    ):
        super().__init__(device, elements)
        self.app_package = app_package
        self.explore_steps = steps
        self.provider = provider
        self.model = model
        self.output_path = output_path
        self._run_dir = None

    def steps(self) -> list[Action]:
        open_action = OpenApp(self.device, self.elements, app_package=self.app_package)
        explore_action = ExploreApp(
            self.device,
            self.elements,
            app_package=self.app_package,
            steps=self.explore_steps,
        )

        # The run_dir is set by ExploreApp during execute; we need to pass it
        # to GenerateFeedback. We solve this by wrapping GenerateFeedback in a
        # tiny action that reads the run_dir from the ExploreApp result.
        class _GenerateFeedbackFromRun(GenerateFeedback):
            def __init__(inner_self, device, elements, explore_action_ref: ExploreApp):
                super().__init__(device, elements)
                inner_self.explore_action_ref = explore_action_ref

            def precondition(inner_self) -> bool:
                inner_self.run_dir = getattr(inner_self.explore_action_ref, "run_dir", None)
                inner_self.provider = self.provider
                inner_self.model = self.model
                inner_self.output_path = self.output_path
                return inner_self.run_dir is not None and inner_self.run_dir.exists()

        return [
            open_action,
            explore_action,
            _GenerateFeedbackFromRun(self.device, self.elements, explore_action),
        ]
