"""Shared actions for app review skills.

CollectScreenshotsAndTrees: opens an app and records an exploration trace.
RunLlmReview: turns a trace into a structured LLM-generated report.
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


def unique_run_dir(prefix: str, device_serial: str) -> Path:
    """Return a unique directory for this review run."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = Path(os.environ.get("REVIEW_SKILL_OUTPUT", "/tmp"))
    run_dir = base / f"{prefix}_{device_serial}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_step(run_dir: Path, step: int, xml: str, tree: str, elements: list, screenshot_b64: str, action: dict):
    """Persist one exploration step."""
    import base64

    step_dir = run_dir / f"step_{step:03d}"
    step_dir.mkdir(exist_ok=True)
    (step_dir / "action.json").write_text(json.dumps(action, indent=2, default=str))
    (step_dir / "ui_tree.txt").write_text(tree)
    (step_dir / "elements.json").write_text(json.dumps(elements, indent=2, default=str))
    (step_dir / "raw_xml.xml").write_text(xml or "")
    if screenshot_b64:
        (step_dir / "screenshot.jpg").write_bytes(base64.b64decode(screenshot_b64))


def call_llm(provider: str, model: str, prompt: str) -> str:
    """Call the configured LLM provider."""
    if provider == "deepseek":
        return _call_deepseek(model, prompt)
    if provider == "openrouter":
        return _call_openrouter(model, prompt)
    if provider == "ollama":
        return _call_ollama(model, prompt)
    return _call_deepseek(model, prompt)


def _call_deepseek(model: str, prompt: str) -> str:
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
            model=model or "deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f'{{"error": "LLM call failed: {e}"}}'


def _call_openrouter(model: str, prompt: str) -> str:
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
            model=model or "anthropic/claude-sonnet-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f'{{"error": "LLM call failed: {e}"}}'


def _call_ollama(model: str, prompt: str) -> str:
    try:
        import requests
    except ImportError:
        return ""
    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model or "llama3.2:3b", "prompt": prompt, "stream": False},
            timeout=120,
        )
        return r.json().get("response", "")
    except Exception as e:
        return f'{{"error": "LLM call failed: {e}"}}'


# ── Actions ───────────────────────────────────────────────────────────────────


class CollectScreenshotsAndTrees(Action):
    """Open an app and explore it while saving screenshots and UI trees."""

    name = "collect_screenshots_and_trees"
    description = "Open an app and explore it while saving screenshots and UI trees"

    def __init__(
        self,
        device,
        elements,
        *,
        app_package: str = "",
        steps: int = 12,
        prefix: str = "review",
        **kwargs,
    ):
        super().__init__(device, elements)
        self.app_package = app_package
        self.steps = max(1, min(steps, 30))
        self.prefix = prefix
        self.run_dir = unique_run_dir(prefix, getattr(device, "serial", "unknown"))

    def precondition(self) -> bool:
        return bool(self.app_package)

    def execute(self) -> ActionResult:
        # Screen dimensions
        width, height = 1080, 1920
        try:
            size_out = self.device.adb("shell", "wm", "size", timeout=5)
            if "x" in size_out:
                part = size_out.split(":")[-1].strip()
                w, h = part.split("x")
                width, height = int(w), int(h)
        except Exception:
            pass

        # Launch app
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

            action_name, action_detail = self._choose_action(elements, width, height)
            performed.append(action_detail)

            save_step(
                self.run_dir,
                step,
                xml,
                tree,
                elements,
                shot.get("image", ""),
                action_detail,
            )

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
                elif action_name == "home":
                    self.device.adb("shell", "input", "keyevent", "KEYCODE_HOME")
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
                performed.append({"step": step, "error": str(e)})

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
        """Pick the next exploration action."""
        if random.random() < 0.15:
            return "back", {"action": "press_back", "reason": "reset / go back"}
        if random.random() < 0.08:
            return "home", {"action": "relaunch_from_home", "reason": "fresh start"}
        if random.random() < 0.25 and elements:
            cx, cy = width // 2, height // 2
            direction = random.choice(["up", "down", "left", "right"])
            if direction == "up":
                return "swipe", {"action": "swipe_up", "x1": cx, "y1": cy + 400, "x2": cx, "y2": cy - 400}
            elif direction == "down":
                return "swipe", {"action": "swipe_down", "x1": cx, "y1": cy - 400, "x2": cx, "y2": cy + 400}
            elif direction == "left":
                return "swipe", {"action": "swipe_left", "x1": cx + 300, "y1": cy, "x2": cx - 300, "y2": cy}
            else:
                return "swipe", {"action": "swipe_right", "x1": cx - 300, "y1": cy, "x2": cx + 300, "y2": cy}

        candidates = [el for el in elements if el.get("clickable") and el.get("center")]
        if candidates:
            labeled = [el for el in candidates if el.get("text") or el.get("content_desc")]
            target = random.choice(labeled if labeled and random.random() > 0.3 else candidates)
            cx, cy = target["center"]["x"], target["center"]["y"]
            label = target.get("text") or target.get("content_desc") or target.get("resource_id", "")
            return "tap", {
                "action": "tap_element",
                "x": cx,
                "y": cy,
                "label": label[:60],
                "reason": "explore interactive element",
            }

        return "swipe", {
            "action": "swipe_up",
            "x1": width // 2,
            "y1": height * 3 // 4,
            "x2": width // 2,
            "y2": height // 4,
            "reason": "fallback scroll",
        }


class RunLlmReview(Action):
    """Generate a structured LLM review report from an exploration run directory."""

    name = "run_llm_review"
    description = "Generate a structured LLM review report from an exploration run directory"

    def __init__(
        self,
        device,
        elements,
        *,
        run_dir: str = "",
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        system_prompt: str = "",
        rubric: str = "",
        report_name: str = "report.json",
        extra_context: str = "",
        **kwargs,
    ):
        super().__init__(device, elements)
        self.run_dir = Path(run_dir) if run_dir else None
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt
        self.rubric = rubric
        self.report_name = report_name
        self.extra_context = extra_context

    def precondition(self) -> bool:
        return self.run_dir is not None and self.run_dir.exists()

    def execute(self) -> ActionResult:
        steps = sorted(self.run_dir.glob("step_*"))
        if not steps:
            return ActionResult(success=False, error="No exploration steps found")

        trace_lines = []
        for step_dir in steps:
            action = json.loads((step_dir / "action.json").read_text())
            tree = (step_dir / "ui_tree.txt").read_text().strip()
            tree_short = "\n".join(tree.splitlines()[:40])
            trace_lines.append(
                f"--- {step_dir.name} ---\nAction: {json.dumps(action)}\nScreen tree:\n{tree_short}\n"
            )
        trace = "\n".join(trace_lines)

        extra = f"\n\nAdditional context about the app:\n{self.extra_context}" if self.extra_context else ""

        prompt = f"""{self.system_prompt}

Below is a trace of screens seen while exploring the app. Each step shows the action taken and the UI tree of the screen before the action.

{trace}{extra}

{self.rubric}

Return ONLY valid JSON. Do not wrap it in markdown."""

        feedback = call_llm(self.provider, self.model, prompt)
        if not feedback:
            return ActionResult(success=False, error="LLM did not return feedback")

        try:
            parsed = json.loads(feedback)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            parsed = {"raw": feedback}
            pretty = feedback

        out_path = self.run_dir / self.report_name
        out_path.write_text(pretty, encoding="utf-8")

        return ActionResult(success=True, data={"report": parsed, "output_path": str(out_path)})
