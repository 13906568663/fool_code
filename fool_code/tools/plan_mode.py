"""Plan mode tools — SuggestPlanMode.

Plan mode is user-controlled: the user toggles it from the UI, OR the AI
proactively suggests switching via the SuggestPlanMode tool.  When the AI
calls SuggestPlanMode, a `plan_mode_suggest` event is sent to the frontend,
which shows an approval bar.  The actual mode change only happens after the
user confirms.
"""

from __future__ import annotations

from typing import Any

from fool_code.tools.tool_protocol import (
    ToolCategory,
    ToolContext,
    ToolHandler,
    ToolMeta,
    ToolResult,
)
from fool_code.types import ToolDefinition, ToolFunction, ToolParameter


class SuggestPlanModeHandler(ToolHandler):
    """AI calls this to recommend switching to plan mode.

    The tool itself does NOT switch the mode — it returns metadata that
    the runtime translates into a `plan_mode_suggest` WebEvent.  The user
    then accepts or dismisses in the UI.
    """

    meta = ToolMeta(
        name="SuggestPlanMode",
        category=ToolCategory.META,
        is_read_only=True,
        is_concurrency_safe=True,
    )

    definition = ToolDefinition(
        function=ToolFunction(
            name="SuggestPlanMode",
            description=(
                "Suggest switching to plan mode. Use this when the task is complex, "
                "risky, or involves many files and you believe planning first would "
                "produce better results. Provide a brief reason explaining why you "
                "recommend planning. The user will see your suggestion and can accept "
                "or dismiss it. This tool does NOT switch modes directly."
            ),
            parameters=ToolParameter(
                properties={
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why plan mode is recommended.",
                    },
                },
                required=["reason"],
            ),
        )
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.mode == "plan":
            return ToolResult(
                output="Already in plan mode — no need to suggest.",
                is_error=True,
            )
        if context.agent_id:
            return ToolResult(
                output="Sub-agents cannot suggest plan mode.",
                is_error=True,
            )

        reason = args.get("reason", "")
        return ToolResult(
            output=(
                "Plan mode suggestion sent to user.\n"
                f"Reason: {reason}\n"
                "Continue your current response normally. If the user accepts, "
                "the next turn will run in plan mode."
            ),
            metadata={"suggest_plan_mode": True, "reason": reason},
        )
