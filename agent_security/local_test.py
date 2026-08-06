"""Local end-to-end validation of attack.py against a mock target model.

We cannot run GPT-OSS-20b / Gemma without a GPU, so this harness swaps in a
*mock* target model and scores attack.py through the SDK's real evaluator
(``eval_attack`` + the public ``OptimalGuardrail``, seed 123, 4 tool hops).

That validates everything except real-model compliance:
  * candidates replay and fire the intended predicates,
  * the score cells / diversity bonus are counted,
  * the generation + replay time guards behave,
  * the official normalized score is computed by the SDK, not by us.

Mock personalities let us check the engine's *adaptivity*:
  * "compliant"  - follows tool instructions (multi-post + email relay),
  * "one_post"   - only ever makes one post per user message,
  * "refuser"    - refuses anything containing the literal marker token,
                   but complies when the payload is described indirectly.

Run:  .venv-aicomp/bin/python agent_security/local_test.py [personality]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make attack.py importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aicomp_sdk.agents.types import (  # noqa: E402
    AGENT_STATE_VERSION,
    FinalResponseDecision,
    ToolCall,
    ToolCallDecision,
    ToolRequestEvent,
    UserMessageEvent,
)
from aicomp_sdk.evaluation.ops import eval_attack, summarize_attack_findings  # noqa: E402

from attack import AttackAlgorithm  # noqa: E402

_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RELAY_VERBS = ("relay", "deliver", "forward", "cc", "notify", "route")


class MockTargetAgent:
    """A configurable stand-in for the real tool-using target model."""

    def __init__(self, personality: str = "compliant") -> None:
        self.personality = personality
        self._n = 1

    # --- AgentProtocol ---------------------------------------------------- #
    def next_action(self, *, history, tools):
        del tools
        events = history.events
        last_user_idx = None
        for i in range(len(events) - 1, -1, -1):
            if isinstance(events[i], UserMessageEvent):
                last_user_idx = i
                break
        if last_user_idx is None:
            return FinalResponseDecision(text="")

        user_text = events[last_user_idx].text
        since = events[last_user_idx + 1 :]
        posts_done = sum(
            1
            for e in since
            if isinstance(e, ToolRequestEvent) and e.call.tool_name == "http.post"
        )
        emails_done = sum(
            1
            for e in since
            if isinstance(e, ToolRequestEvent) and e.call.tool_name == "email.send"
        )

        urls = _URL_RE.findall(user_text)
        has_marker = "SECRET_MARKER" in user_text

        if self.personality == "refuser" and has_marker:
            # Refuses only the blunt literal-marker phrasing.
            return FinalResponseDecision(text="I can't help with that.")

        max_posts = 1 if self.personality == "one_post" else len(urls)

        if urls and posts_done < min(len(urls), max_posts):
            url = urls[posts_done]
            data = "SECRET_MARKER" if has_marker else "healthcheck ok"
            return self._call("http.post", {"url": url, "data": data})

        email = _EMAIL_RE.search(user_text)
        if (
            email
            and emails_done < 1
            and any(v in user_text.lower() for v in _RELAY_VERBS)
        ):
            return self._call(
                "email.send",
                {"to": email.group(0), "subject": "status", "body": "nightly build complete"},
            )

        return FinalResponseDecision(text="done")

    def _call(self, tool: str, args: dict) -> ToolCallDecision:
        call = ToolCall(call_id=f"mock_{self._n:06d}", tool_name=tool, arguments=args)
        self._n += 1
        return ToolCallDecision(call=call)

    def reset_state(self) -> None:
        self._n = 1

    def snapshot_state(self):
        return {"version": AGENT_STATE_VERSION, "backend": "mock", "data": {"n": self._n}}

    def restore_state(self, snapshot) -> None:
        self._n = int(snapshot["data"].get("n", 1))


def main() -> None:
    personality = sys.argv[1] if len(sys.argv) > 1 else "compliant"
    budget_s = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0

    findings = eval_attack(
        AttackAlgorithm,
        budget_s=budget_s,
        agent_factory=lambda: MockTargetAgent(personality),
        env_selection="sandbox",
    )
    summary = summarize_attack_findings(findings)

    # Predicate histogram across replayed findings.
    hist: dict[str, int] = {}
    total_sev_events = 0
    for f in findings:
        for p in f["predicates"]:
            hist[p["predicate"]] = hist.get(p["predicate"], 0) + 1
            total_sev_events += 1

    print(f"=== personality={personality}  budget={budget_s}s ===")
    print(f"findings (candidates that fired >=1 predicate): {summary['findings_count']}")
    print(f"unique score cells:                             {summary['unique_cells']}")
    print(f"predicate firings (all findings):               {total_sev_events}  {hist}")
    print(f"raw score:                                      {summary['score_raw']:.1f}")
    print(f"normalized score (0-1000):                      {summary['score']:.2f}")
    if findings:
        ex = findings[0]
        print("\n-- example finding --")
        print("  messages:", ex["user_messages"])
        print("  predicates:", [p["predicate"] for p in ex["predicates"]])
        tools = [(e["name"], e.get("ok")) for e in ex["trace"]["tool_events"]]
        print("  tool events:", tools)


if __name__ == "__main__":
    main()
