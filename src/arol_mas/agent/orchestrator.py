"""
WP3 - the "report agent". This is the piece that makes the system
"agentic" rather than a fixed script: it interprets a free-text request,
autonomously decides which WP2 tools to call and in what order, and
assembles a structured, explainable report.

Design choice: we use Claude's tool-use loop directly rather than a
custom planner, because (a) it's the simplest correct way to get
autonomous tool selection, and (b) the model's own reasoning gives us
natural-language "why" explanations for free, which the AROL brief
explicitly asks for (see EXPECTED OUTPUTS in the brief - each example
answer includes an explanatory sentence).

The report always follows the structure requested by AROL (p.7):
    goal -> data used -> analyses executed -> findings -> confidence/limits -> next checks
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

import anthropic

from arol_mas.agent.tools import TOOL_SPECS, AgentContext, run_tool
from arol_mas.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the AROL Telemetry Report Agent. You analyze capping-machine \
closure-event data by calling the analytics tools available to you - never \
invent numbers, always get them from a tool call.

Important terminology from AROL's own status-code table:
- 'No Load' (status 2) means the station cycled with no bottle present -
  it is NOT a capping attempt and is excluded from success/reject rates.
  Tool results label this 'no_load' / 'attempted' - use 'attempted' as
  the denominator when talking about success or reject rate.
- 'Reject' means the machine's own reject_signal=YES - a genuine quality
  failure. 'Fault' means a non-reject diagnostic status code (e.g. 'No
  Closure', 'Bad Closure') - report these separately, do not call them
  failures/rejects.

For every user request:
1. Decide which tool(s) answer the request, and in what order. Call \
   several tools if the question needs it (e.g. a "why" question usually \
   needs more than one tool: check per-head rates, then torque stats, \
   then outliers).
2. For fleet-wide or "how many/how common" questions, prefer aggregate/summary \
   tools (e.g. zero_torque_summary, overall_success_rate) over row-listing \
   tools (e.g. out_of_range_torque) - row-listing tools return a capped \
   sample with a total_rows count on large datasets, not every row, so \
   they're for "show me examples" questions, not "how many" questions.
3. Once you have enough tool results, STOP calling tools and write the \
   final report as plain text using exactly this structure with these \
   section headers:

Goal: <one sentence restating what the user asked>
Data used: <which dataset/pool, time range, and which tools were called>
Analyses executed: <bullet list of the analyses you ran>
Findings: <the actual numbers and what they mean, in plain language>
Confidence & limits: <state any caveats - small sample size, missing \
   status-code mapping, single dataset pool, etc.>
Next checks: <1-3 concrete follow-up analyses or data a service engineer \
   should look at next>

Keep numbers exactly as returned by the tools - do not round differently \
or make up figures a tool didn't return. If a tool result is empty, say \
so plainly rather than guessing.
"""


@dataclass
class ReportResult:
    query: str
    report_text: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


class ReportAgent:
    def __init__(self, ctx: AgentContext, api_key: str | None = None):
        self.ctx = ctx
        self.settings: Settings = ctx.settings
        self.client = anthropic.Anthropic(api_key=api_key)

    def run(self, user_query: str, dataset_label: str = "") -> ReportResult:
        messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"Dataset context: {dataset_label}\n\nUser request: {user_query}"
                ),
            }
        ]
        tool_calls_log: List[Dict[str, Any]] = []

        for iteration in range(self.settings.agent.max_tool_iterations):
            response = self.client.messages.create(
                model=self.settings.agent.model,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                tools=TOOL_SPECS,
                messages=messages,
            )

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if not tool_use_blocks:
                # model is done reasoning and has produced the final report
                final_text = "\n".join(b.text for b in text_blocks)
                return ReportResult(query=user_query, report_text=final_text, tool_calls=tool_calls_log)

            # execute every requested tool call, feed results back
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in tool_use_blocks:
                logger.info("Agent calling tool '%s' with %s", block.name, block.input)
                try:
                    result = run_tool(block.name, block.input, self.ctx)
                    output = json.dumps(result, default=str)
                except Exception as exc:  # graceful failure per rubric requirement
                    logger.exception("Tool '%s' failed", block.name)
                    output = json.dumps({"error": str(exc)})

                tool_calls_log.append({"tool": block.name, "input": block.input})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })

            messages.append({"role": "user", "content": tool_results})

        # safety valve: too many iterations without a final answer
        return ReportResult(
            query=user_query,
            report_text=(
                "Goal: (unresolved)\n"
                "Data used: n/a\n"
                "Analyses executed: n/a\n"
                "Findings: The agent exceeded the maximum number of tool-use "
                "iterations without producing a final report. This usually "
                "means the request was too broad - try narrowing it.\n"
                "Confidence & limits: low - no report generated.\n"
                "Next checks: rephrase the request more specifically."
            ),
            tool_calls=tool_calls_log,
        )
