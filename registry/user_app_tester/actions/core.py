"""Core actions for the user_app_tester skill.

Simulates a real user (age 20-30) exploring an unknown Android app,
records the journey, and produces structured LLM-generated feedback.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

from gitd.services import device_context
from gitd.skills.base import Action, ActionResult


# ── Helpers ───────────────────────────────────────────────────────────────────


def _unique_run_dir(device_serial: str) -> Path:
    """Return a unique directory for this exploration run."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = Path(os.environ.get("USER_APP_TESTER_OUTPUT", "/tmp"))
    run_dir = base / f"user_app_tester_{device_serial}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _save_step(run_dir: Path, step: int, xml: str, tree: str, elements: list, screenshot_b64: str, action: str):
    """Persist one exploration step."""
    step_dir = run_dir / f"step_{step:03d}"
    step_dir.mkdir(exist_ok=True)
    (step_dir / "action.txt").write_text(action)
    (step_dir / "ui_tree.txt").write_text(tree)
    (step_dir / "elements.json").write_text(json.dumps(elements, indent=2, default=str))
    (step_dir / "raw_xml.xml").write_text(xml or "")
    if screenshot_b64:
        import base64

        (step_dir / "screenshot.jpg").write_bytes(base64.b64decode(screenshot_b64))


# ── Actions ───────────────────────────────────────────────────────────────────


class OpenApp(Action):
    """Launch the target app and wait for it to settle."""

    name = "open_app"
    description = "Launch the target app and wait for it to settle"

    def __init__(self, device, elements, *, app_package: str = "", **kwargs):
        super().__init__(device, elements)
        self.app_package = app_package

    def precondition(self) -> bool:
        return bool(self.app_package)

    def execute(self) -> ActionResult:
        self.device.adb("shell", "am", "force-stop", self.app_package)
        time.sleep(0.5)
        self.device.adb(
            "shell",
            "monkey",
            "-p",
            self.app_package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
        time.sleep(3.0)
        # Dismiss common startup popups
        for _ in range(3):
            xml = self.device.dump_xml()
            if xml and self.device.dismiss_popups(xml):
                time.sleep(1.0)
            else:
                break
        return ActionResult(success=True, data={"app_package": self.app_package})

    def postcondition(self) -> bool:
        output = self.device.adb("shell", "dumpsys", "window", timeout=5)
        return self.app_package in output


class ExploreApp(Action):
    """Explore the app for N steps while recording screenshots and UI trees."""

    name = "explore_app"
    description = "Explore the app for N steps while recording screenshots and UI trees"

    def __init__(self, device, elements, *, app_package: str = "", steps: int = 12, **kwargs):
        super().__init__(device, elements)
        self.app_package = app_package
        self.steps = max(1, min(steps, 30))
        self.run_dir = _unique_run_dir(device.serial if hasattr(device, "serial") else "unknown")

    def execute(self) -> ActionResult:
        width, height = 1080, 1920
        try:
            size_out = self.device.adb("shell", "wm", "size", timeout=5)
            # Output looks like: Physical size: 1080x2400
            if "x" in size_out:
                part = size_out.split(":")[-1].strip()
                w, h = part.split("x")
                width, height = int(w), int(h)
        except Exception:
            pass

        # Reset: start from a known state inside the app
        self.device.adb("shell", "am", "force-stop", self.app_package)
        time.sleep(0.3)
        self.device.adb(
            "shell",
            "monkey",
            "-p",
            self.app_package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
        time.sleep(2.5)

        performed = []
        for step in range(1, self.steps + 1):
            time.sleep(1.0)
            xml = self.device.dump_xml() or ""
            tree = device_context.get_screen_tree(self.device.serial)
            elements = device_context.get_interactive_elements(self.device.serial)
            shot = device_context.screenshot(self.device.serial)

            # Decide what to do next
            action_name, action_detail = self._choose_action(elements, width, height)
            performed.append(action_detail)

            # Persist BEFORE the action so we capture the state that led to it
            _save_step(
                self.run_dir,
                step,
                xml,
                tree,
                elements,
                shot.get("image", ""),
                action_detail,
            )

            # Execute action
            try:
                if action_name == "tap":
                    self.device.tap(action_detail["x"], action_detail["y"])
                elif action_name == "swipe":
                    self.device.swipe(
                        action_detail["x1"],
                        action_detail["y1"],
                        action_detail["x2"],
                        action_detail["y2"],
                        ms=500,
                    )
                elif action_name == "back":
                    self.device.back()
                elif action_name == "type":
                    text = action_detail["text"].replace(" ", "%s")
                    self.device.adb("shell", "input", "text", text)
                elif action_name == "home":
                    self.device.adb("shell", "input", "keyevent", "KEYCODE_HOME")
                    # Relaunch app to continue exploration
                    time.sleep(0.5)
                    self.device.adb(
                        "shell",
                        "monkey",
                        "-p",
                        self.app_package,
                        "-c",
                        "android.intent.category.LAUNCHER",
                        "1",
                    )
                    time.sleep(1.5)
            except Exception as e:
                performed.append(f"step {step} error: {e}")

            # Dismiss any popups after action
            try:
                xml2 = self.device.dump_xml()
                if xml2 and self.device.dismiss_popups(xml2):
                    time.sleep(0.8)
            except Exception:
                pass

        return ActionResult(
            success=True,
            data={
                "steps": self.steps,
                "run_dir": str(self.run_dir),
                "performed": performed,
            },
        )

    def _choose_action(self, elements: list[dict], width: int, height: int) -> tuple[str, dict]:
        """Pick the next action. Tries to behave like a curious but impatient user."""
        # 15% chance to go back (user realises they are lost)
        if random.random() < 0.15:
            return "back", {"action": "press_back", "reason": "user felt lost"}

        # 10% chance to go home and relaunch (fresh start)
        if random.random() < 0.10:
            return "home", {"action": "relaunch_from_home", "reason": "fresh start"}

        # 25% chance to swipe if the screen looks scrollable
        if random.random() < 0.25 and elements:
            direction = random.choice(["up", "down", "left", "right"])
            cx, cy = width // 2, height // 2
            if direction == "up":
                return "swipe", {"action": "swipe_up", "x1": cx, "y1": cy + 400, "x2": cx, "y2": cy - 400, "reason": "scroll down"}
            elif direction == "down":
                return "swipe", {"action": "swipe_down", "x1": cx, "y1": cy - 400, "x2": cx, "y2": cy + 400, "reason": "scroll up"}
            elif direction == "left":
                return "swipe", {"action": "swipe_left", "x1": cx + 300, "y1": cy, "x2": cx - 300, "y2": cy, "reason": "go to next page"}
            else:
                return "swipe", {"action": "swipe_right", "x1": cx - 300, "y1": cy, "x2": cx + 300, "y2": cy, "reason": "go back a page"}

        # Tap a candidate element
        candidates = [
            el for el in elements
            if el.get("clickable") and el.get("center")
        ]
        if candidates:
            # Prefer elements with labels (buttons, links) over blank areas
            labeled = [el for el in candidates if el.get("text") or el.get("content_desc")]
            target = random.choice(labeled if labeled and random.random() > 0.3 else candidates)
            cx, cy = target["center"]["x"], target["center"]["y"]
            label = target.get("text") or target.get("content_desc") or target.get("resource_id", "")
            return "tap", {
                "action": "tap_element",
                "x": cx,
                "y": cy,
                "label": label[:40],
                "reason": "curious tap",
            }

        # Fallback: random swipe
        return "swipe", {"action": "swipe_up", "x1": width // 2, "y1": height * 3 // 4, "x2": width // 2, "y2": height // 4, "reason": "fallback scroll"}


class GenerateFeedback(Action):
    """Generate structured user feedback from the recorded exploration."""

    name = "generate_feedback"
    description = "Generate structured user feedback from the recorded exploration"

    def __init__(
        self,
        device,
        elements,
        *,
        run_dir: str = "",
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        output_path: str = "",
        **kwargs,
    ):
        super().__init__(device, elements)
        self.run_dir = Path(run_dir) if run_dir else None
        self.provider = provider
        self.model = model
        self.output_path = output_path

    def precondition(self) -> bool:
        return self.run_dir is not None and self.run_dir.exists()

    def execute(self) -> ActionResult:
        steps = sorted(self.run_dir.glob("step_*"))
        if not steps:
            return ActionResult(success=False, error="No exploration steps found")

        # Build a compact trace for the LLM
        trace_lines = []
        for step_dir in steps:
            action = (step_dir / "action.txt").read_text().strip()
            tree = (step_dir / "ui_tree.txt").read_text().strip()
            # Truncate tree to keep prompt size reasonable
            tree_short = "\n".join(tree.splitlines()[:40])
            trace_lines.append(f"--- Step {step_dir.name} ---\nAction: {action}\nScreen tree:\n{tree_short}\n")
        trace = "\n".join(trace_lines)

        prompt = f"""You are a 25-year-old everyday smartphone user who just downloaded a new Android app for the first time.
You are tech-savvy but not a developer. You want the app to solve a problem for you, and you are easily frustrated when things are unclear.

Below is a trace of your first session with the app. Each step shows what you saw on screen and what you tried to do.

{trace}

Based on this first-time user experience, write a structured feedback report in JSON format with exactly these keys:
- summary: a 1-2 sentence overall impression
- understanding_score: integer 1-5 (how understandable the app felt)
- usability_score: integer 1-5 (how easy it was to navigate and act)
- logic_score: integer 1-5 (whether flows and labels made sense)
- overall_rating: integer 1-5
- positives: list of strings, things that worked well or felt good
- confusion_points: list of strings, moments where you did not know what to do or what would happen
- problems: list of strings, concrete bugs, errors, or blockers you encountered
- logic_issues: list of strings, things that felt logically inconsistent or badly designed
- suggestions: list of strings, concrete improvements from a user perspective
- verbatim_quote: one sentence you might say to a friend about the app

Return ONLY valid JSON. Do not wrap it in markdown."""

        feedback = self._call_llm(prompt)
        if not feedback:
            return ActionResult(success=False, error="LLM did not return feedback")

        # Try to parse and pretty-print
        try:
            parsed = json.loads(feedback)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            parsed = {"raw": feedback}
            pretty = feedback

        # Save to file
        out_path = Path(self.output_path) if self.output_path else self.run_dir / "feedback.json"
        out_path.write_text(pretty, encoding="utf-8")

        return ActionResult(success=True, data={"feedback": parsed, "output_path": str(out_path)})

    def _call_llm(self, prompt: str) -> str:
        """Call the configured LLM provider. Defaults to DeepSeek."""
        if self.provider == "deepseek":
            return self._call_deepseek(prompt)
        if self.provider == "openrouter":
            return self._call_openrouter(prompt)
        if self.provider == "ollama":
            return self._call_ollama(prompt)
        return self._call_deepseek(prompt)

    def _call_deepseek(self, prompt: str) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            return ""
        client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        )
        try:
            resp = client.chat.completions.create(
                model=self.model or "deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return f'{{"error": "LLM call failed: {e}"}}'

    def _call_openrouter(self, prompt: str) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            return ""
        client = OpenAI(
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            base_url="https://openrouter.ai/api/v1",
        )
        try:
            resp = client.chat.completions.create(
                model=self.model or "anthropic/claude-sonnet-4",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return f'{{"error": "LLM call failed: {e}"}}'

    def _call_ollama(self, prompt: str) -> str:
        try:
            import requests
        except ImportError:
            return ""
        try:
            r = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": self.model or "llama3.2:3b", "prompt": prompt, "stream": False},
                timeout=120,
            )
            return r.json().get("response", "")
        except Exception as e:
            return f'{{"error": "LLM call failed: {e}"}}'
