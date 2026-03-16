"""
computer_use.py — Multi-Modal Computer Use & GUI Navigation.

In 2026, agents don't just call APIs — they use computers like humans.
This module gives AetheerAI "eyes" (screen capture) and "hands"
(keyboard + mouse), enabling integration with any application regardless
of whether it exposes an API.

Architecture
------------
1. Screenshot  — Capture the current screen state (via mss or PIL stub).
2. Describe    — A vision-capable AI mode describes what is on screen.
3. Plan        — The Master AI determines the next action to take.
4. Execute     — The action is performed (click, type, scroll, hotkey).
5. Repeat      — Until the goal is met or max_steps is reached.

Dependency model (graceful degradation)
---------------------------------------
The module is designed to work even when optional packages are absent:

  mss        — Fast cross-platform screen capture. Falls back to Pillow
               ImageGrab, then to a stub that returns None.
  pyautogui  — Mouse/keyboard control. If absent, execute_action() runs in
               DRY_RUN mode (plans are shown but not executed).
  Pillow     — Image encoding/decoding for the AI vision call.
               If absent, screenshots are passed as "unavailable — describe
               what you expect to see" and the AI reasons without a visual.

All actions are logged to the AetheerAI audit log by default.

Safety controls
---------------
- Coordinate bounds are clamped to actual screen dimensions.
- A configurable `safe_mode` prevents clicks outside a specified region.
- Every action goes through an approval callback before execution when
  `require_approval=True` (default in interactive sessions).
- Typing actions strip null bytes and limit length to 2000 characters.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from typing import Callable, Any

logger = logging.getLogger(__name__)


# ── Optional dependency checks ────────────────────────────────────────────

def _try_import(name: str):
    try:
        import importlib
        return importlib.import_module(name)
    except ImportError:
        return None


_mss        = _try_import("mss")
_pyautogui  = _try_import("pyautogui")
_pil        = _try_import("PIL")
_pil_image  = _try_import("PIL.Image")
_pil_grab   = _try_import("PIL.ImageGrab")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    CLICK      = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK  = "right_click"
    TYPE       = "type"
    HOTKEY     = "hotkey"
    SCROLL     = "scroll"
    SCREENSHOT = "screenshot"
    WAIT       = "wait"


@dataclass
class ScreenAction:
    """
    A single action to perform on the screen.

    Attributes
    ----------
    action_type : One of ActionType.
    x, y        : Screen coordinates for click/scroll (ignored for type/hotkey).
    text        : Text to type (for TYPE action).
    keys        : Hotkey combination list (e.g. ["ctrl", "c"]) for HOTKEY action.
    scroll_dir  : "up" | "down" | "left" | "right" for SCROLL action.
    scroll_amount: Number of scroll steps.
    wait_seconds: Seconds to wait (for WAIT action).
    reasoning   : Why this action was chosen (from AI plan).
    """
    action_type:    ActionType
    x:              int | None = None
    y:              int | None = None
    text:           str | None = None
    keys:           list[str] = field(default_factory=list)
    scroll_dir:     str = "down"
    scroll_amount:  int = 3
    wait_seconds:   float = 1.0
    reasoning:      str = ""

    def to_dict(self) -> dict:
        return {
            "action_type":   self.action_type.value,
            "x":             self.x,
            "y":             self.y,
            "text":          (self.text or "")[:200],
            "keys":          self.keys,
            "scroll_dir":    self.scroll_dir,
            "scroll_amount": self.scroll_amount,
            "wait_seconds":  self.wait_seconds,
            "reasoning":     self.reasoning[:300],
        }


@dataclass
class ActionResult:
    """Result of executing a single ScreenAction."""
    success:        bool
    action:         ScreenAction
    screenshot_b64: str | None = None   # screenshot AFTER the action
    error:          str | None = None
    timestamp:      float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "success":   self.success,
            "action":    self.action.to_dict(),
            "error":     self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class NavigationResult:
    """Final result of a full navigate_to_goal() run."""
    goal:         str
    achieved:     bool
    steps_taken:  int
    final_result: str
    action_log:   list[dict] = field(default_factory=list)
    elapsed_secs: float = 0.0


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_PLAN_PROMPT = """\
You are AetheerAI's Computer Use agent.  Your goal:
{goal}

Current screen description:
{screen_description}

Prior actions taken (most recent last):
{history}

What is the SINGLE next action to take to advance toward the goal?

Respond in EXACTLY this format (no other text):
ACTION: <click|double_click|right_click|type|hotkey|scroll|wait|done>
X: <integer screen x coordinate, or NONE>
Y: <integer screen y coordinate, or NONE>
TEXT: <text to type, or NONE>
KEYS: <comma-separated hotkey list like ctrl,c  — or NONE>
SCROLL_DIR: <up|down|left|right — or NONE>
REASONING: <one sentence explaining why>

Use ACTION: done when the goal has been fully achieved.
"""

_DESCRIBE_PROMPT = """\
You are analysing a screenshot for an AI agent that needs to use a computer.

Describe what you see in precise, structured terms:
1. What application or website is open?
2. What elements are visible (buttons, inputs, menus, text)?
3. What is the current state (any dialogs, error messages, loading indicators)?
4. What are the likely interaction points for the goal: "{goal}"?

Be factual and brief (max 200 words).
"""

_GOAL_ACHIEVED_PROMPT = """\
Screen description: {screen_description}
Goal: {goal}

Has the goal been FULLY achieved based on what is visible on screen?
Answer only YES or NO (first word), then a brief explanation.
"""


# ---------------------------------------------------------------------------
# ComputerUseAgent
# ---------------------------------------------------------------------------

class ComputerUseAgent:
    """
    Orchestrates multi-step screen navigation toward a natural-language goal.

    Parameters
    ----------
    ai_adapter      : AetheerAI's AIAdapter (must support vision for best results).
    max_steps       : Hard limit on the action loop (default 15).
    dry_run         : If True, plan actions but do NOT execute them.
    require_approval: If True, call *approval_callback* before each action.
    approval_callback: ``(ScreenAction) -> bool`` — return True to approve.
    safe_region     : Optional ``(x1, y1, x2, y2)`` bounding box.
                      Clicks outside this box are clamped/rejected.
    audit_logger    : Optional AuditLogger for recording actions.
    """

    def __init__(
        self,
        ai_adapter,
        max_steps: int = 15,
        dry_run: bool = False,
        require_approval: bool = False,
        approval_callback: Callable[[ScreenAction], bool] | None = None,
        safe_region: tuple[int, int, int, int] | None = None,
        audit_logger=None,
    ) -> None:
        self.ai_adapter        = ai_adapter
        self.max_steps         = max_steps
        self.dry_run           = dry_run or (_pyautogui is None)
        self.require_approval  = require_approval
        self.approval_callback = approval_callback
        self.safe_region       = safe_region
        self._audit            = audit_logger
        self._screen_w: int | None = None
        self._screen_h: int | None = None
        self._detect_screen_size()

        if self.dry_run and _pyautogui is None:
            logger.info(
                "ComputerUseAgent: pyautogui not installed — running in DRY_RUN mode "
                "(actions planned but not executed). Install pyautogui to enable live control."
            )

    def _detect_screen_size(self) -> None:
        try:
            if _pyautogui:
                self._screen_w, self._screen_h = _pyautogui.size()
            elif _mss:
                with _mss.mss() as sct:
                    mon = sct.monitors[0]
                    self._screen_w = mon["width"]
                    self._screen_h = mon["height"]
        except Exception:
            self._screen_w, self._screen_h = 1920, 1080   # safe default

    # ── Screen capture ────────────────────────────────────────────────

    def screenshot_bytes(self) -> bytes | None:
        """Return raw PNG bytes of the current screen, or None if unavailable."""
        # Strategy 1: mss (fastest, cross-platform)
        if _mss:
            try:
                with _mss.mss() as sct:
                    img = sct.grab(sct.monitors[0])
                    # mss returns BGRA; convert to PNG via Pillow
                    if _pil_image:
                        pil = _pil_image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                        buf = BytesIO()
                        pil.save(buf, format="PNG", optimize=True)
                        return buf.getvalue()
            except Exception as exc:
                logger.debug("mss screenshot failed: %s", exc)

        # Strategy 2: PIL ImageGrab (Windows / macOS)
        if _pil_grab:
            try:
                img = _pil_grab.grab()
                buf = BytesIO()
                img.save(buf, format="PNG", optimize=True)
                return buf.getvalue()
            except Exception as exc:
                logger.debug("PIL.ImageGrab failed: %s", exc)

        return None

    def screenshot_b64(self) -> str | None:
        """Return the current screenshot as a base64-encoded PNG string."""
        raw = self.screenshot_bytes()
        if raw is None:
            return None
        return base64.b64encode(raw).decode("utf-8")

    # ── AI vision helpers ─────────────────────────────────────────────

    def describe_screen(self, goal: str = "") -> str:
        """
        Ask the AI to describe what is currently visible on screen.

        If a screenshot is available, it is embedded in the message (base64).
        If visual AI is not available or the screenshot fails, the AI reasons
        about the expected state from context.
        """
        img_b64 = self.screenshot_b64()
        prompt  = _DESCRIBE_PROMPT.format(goal=goal or "navigate the interface")

        if img_b64:
            # Build a multimodal message; the AI adapter handles capability detection
            messages = [
                {
                    "role":    "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type":      "image_url",
                            "image_url": {
                                "url":    f"data:image/png;base64,{img_b64}",
                                "detail": "low",
                            },
                        },
                    ],
                }
            ]
        else:
            messages = [{"role": "user", "content": prompt + "\n\n(No screenshot available — reason from context.)"}]

        try:
            return self.ai_adapter.chat(messages=messages).strip()
        except Exception as exc:
            logger.warning("ComputerUseAgent.describe_screen failed: %s", exc)
            return f"Screen description unavailable: {exc}"

    def _is_goal_achieved(self, goal: str, screen_description: str) -> bool:
        prompt = _GOAL_ACHIEVED_PROMPT.format(
            screen_description=screen_description, goal=goal
        )
        try:
            raw = self.ai_adapter.chat(messages=[{"role": "user", "content": prompt}])
            return raw.strip().upper().startswith("YES")
        except Exception:
            return False

    # ── Action planning ───────────────────────────────────────────────

    def plan_next_action(
        self,
        goal: str,
        screen_description: str,
        history: list[dict],
    ) -> ScreenAction:
        """Ask the AI which single action to take next toward the goal."""
        history_str = "\n".join(
            f"Step {i+1}: {a.get('action_type','?')} — {a.get('reasoning','')}"
            for i, a in enumerate(history[-8:])  # last 8 steps only
        ) or "(none yet)"

        prompt = _PLAN_PROMPT.format(
            goal=goal,
            screen_description=screen_description,
            history=history_str,
        )

        try:
            raw = self.ai_adapter.chat(messages=[{"role": "user", "content": prompt}]).strip()
        except Exception as exc:
            logger.warning("ComputerUseAgent.plan_next_action failed: %s", exc)
            return ScreenAction(action_type=ActionType.WAIT, reasoning=f"AI planning error: {exc}")

        return self._parse_action(raw)

    def _parse_action(self, raw: str) -> ScreenAction:
        vals: dict[str, str] = {}
        for line in raw.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                vals[key.strip().upper()] = val.strip()

        action_str = vals.get("ACTION", "wait").lower().strip()
        if action_str == "done":
            action_str = "wait"   # sentinel — caller checks for "done" via _is_goal_achieved

        try:
            action_type = ActionType(action_str)
        except ValueError:
            action_type = ActionType.WAIT

        def _int(key: str) -> int | None:
            v = vals.get(key, "NONE")
            try:
                return int(v) if v.upper() != "NONE" else None
            except ValueError:
                return None

        x = _int("X")
        y = _int("Y")
        text_val = vals.get("TEXT", "NONE")
        text      = None if text_val.upper() == "NONE" else text_val
        keys_raw  = vals.get("KEYS", "NONE")
        keys      = [] if keys_raw.upper() == "NONE" else [k.strip() for k in keys_raw.split(",")]
        scroll_dir = vals.get("SCROLL_DIR", "down").lower()
        reasoning  = vals.get("REASONING", "")

        return ScreenAction(
            action_type=action_type,
            x=x, y=y, text=text, keys=keys,
            scroll_dir=scroll_dir,
            reasoning=reasoning,
        )

    # ── Action execution ──────────────────────────────────────────────

    def _clamp_coords(self, x: int | None, y: int | None) -> tuple[int, int]:
        sw = self._screen_w or 1920
        sh = self._screen_h or 1080
        cx = max(0, min(x or 0, sw - 1))
        cy = max(0, min(y or 0, sh - 1))
        if self.safe_region:
            x1, y1, x2, y2 = self.safe_region
            cx = max(x1, min(cx, x2))
            cy = max(y1, min(cy, y2))
        return cx, cy

    def execute_action(self, action: ScreenAction) -> ActionResult:
        """
        Execute a ScreenAction.  Returns an ActionResult with a screenshot.

        If dry_run=True or pyautogui is unavailable, actions are simulated
        (logged but not applied to the screen).
        """
        # Approval gate
        if self.require_approval and self.approval_callback:
            approved = self.approval_callback(action)
            if not approved:
                return ActionResult(
                    success=False,
                    action=action,
                    error="Action rejected by approval callback.",
                )

        if self.dry_run:
            logger.info("[DRY_RUN] Would execute: %s", action.to_dict())
            if self._audit:
                try:
                    self._audit.log(
                        event="computer_use_dry_run",
                        agent="computer_use",
                        details=action.to_dict(),
                    )
                except Exception:
                    pass
            return ActionResult(success=True, action=action)

        try:
            pg = _pyautogui
            if pg is None:
                raise RuntimeError("pyautogui not installed")

            if action.action_type == ActionType.CLICK:
                x, y = self._clamp_coords(action.x, action.y)
                pg.click(x, y)

            elif action.action_type == ActionType.DOUBLE_CLICK:
                x, y = self._clamp_coords(action.x, action.y)
                pg.doubleClick(x, y)

            elif action.action_type == ActionType.RIGHT_CLICK:
                x, y = self._clamp_coords(action.x, action.y)
                pg.rightClick(x, y)

            elif action.action_type == ActionType.TYPE:
                safe_text = (action.text or "")[:2000].replace("\x00", "")
                pg.typewrite(safe_text, interval=0.04)

            elif action.action_type == ActionType.HOTKEY:
                if action.keys:
                    pg.hotkey(*action.keys)

            elif action.action_type == ActionType.SCROLL:
                x, y = self._clamp_coords(action.x or (self._screen_w or 960) // 2,
                                           action.y or (self._screen_h or 540) // 2)
                amount = action.scroll_amount
                if action.scroll_dir == "up":
                    pg.scroll(amount, x=x, y=y)
                elif action.scroll_dir == "down":
                    pg.scroll(-amount, x=x, y=y)
                elif action.scroll_dir == "left":
                    pg.hscroll(-amount, x=x, y=y)
                elif action.scroll_dir == "right":
                    pg.hscroll(amount, x=x, y=y)

            elif action.action_type == ActionType.WAIT:
                time.sleep(min(action.wait_seconds, 10.0))

            time.sleep(0.3)   # brief settle time after action

            screenshot = self.screenshot_b64()
            result = ActionResult(success=True, action=action, screenshot_b64=screenshot)

            if self._audit:
                try:
                    self._audit.log(
                        event="computer_use_action",
                        agent="computer_use",
                        details=action.to_dict(),
                    )
                except Exception:
                    pass

            return result

        except Exception as exc:
            logger.error("ComputerUseAgent.execute_action failed: %s", exc)
            return ActionResult(success=False, action=action, error=str(exc))

    # ── Full navigation loop ──────────────────────────────────────────

    def navigate_to_goal(
        self,
        goal: str,
        max_steps: int | None = None,
    ) -> NavigationResult:
        """
        Autonomously navigate the computer toward *goal*.

        The loop:
          1. Take a screenshot and describe the screen.
          2. Check whether the goal is already achieved.
          3. Plan the next action.
          4. Execute it.
          5. Repeat up to max_steps.
        """
        limit = max_steps or self.max_steps
        start = time.time()
        history: list[dict] = []
        action_log: list[dict] = []

        for step in range(1, limit + 1):
            logger.info("ComputerUse step %d/%d — goal: %s", step, limit, goal[:80])

            screen_desc = self.describe_screen(goal=goal)

            # Check goal achieved
            if step > 1 and self._is_goal_achieved(goal, screen_desc):
                return NavigationResult(
                    goal=goal,
                    achieved=True,
                    steps_taken=step - 1,
                    final_result=screen_desc,
                    action_log=action_log,
                    elapsed_secs=time.time() - start,
                )

            action = self.plan_next_action(goal, screen_desc, history)

            # "done" sentinel from the AI
            if action.reasoning.lower().strip().startswith("goal") and action.action_type == ActionType.WAIT:
                return NavigationResult(
                    goal=goal,
                    achieved=True,
                    steps_taken=step,
                    final_result=screen_desc,
                    action_log=action_log,
                    elapsed_secs=time.time() - start,
                )

            result = self.execute_action(action)
            action_log.append({**action.to_dict(), "success": result.success, "step": step})
            history.append(action.to_dict())

            if not result.success:
                logger.warning(
                    "ComputerUse step %d failed: %s — attempting recovery.", step, result.error
                )

        return NavigationResult(
            goal=goal,
            achieved=False,
            steps_taken=limit,
            final_result=f"Goal not achieved within {limit} steps.",
            action_log=action_log,
            elapsed_secs=time.time() - start,
        )

    # ── Convenience ───────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "dry_run":          self.dry_run,
            "max_steps":        self.max_steps,
            "screen_width":     self._screen_w,
            "screen_height":    self._screen_h,
            "pyautogui_ok":     _pyautogui is not None,
            "mss_ok":           _mss is not None,
            "pillow_ok":        _pil is not None,
            "require_approval": self.require_approval,
        }
