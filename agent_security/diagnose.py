"""Fast per-family compliance probe against a chosen target model.

Runs AttackAlgorithm.run() against the *real* target (or a local stand-in) inside
the exact opaque, fixed-seed, gym environment the evaluator uses, and prints
`last_run_summary` — including the per-family probe report that shows which prompt
framings this model actually obeys. Use it on a Kaggle GPU for a quick read before
committing a full run.

Examples:
  # local, no GPU (engine sanity):
  .venv-aicomp/bin/python agent_security/diagnose.py mock 20
  .venv-aicomp/bin/python agent_security/diagnose.py deterministic 15
  # Kaggle GPU (real compliance signal, short budget):
  python agent_security/diagnose.py gpt_oss 300
  python agent_security/diagnose.py gemma_4 300
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aicomp_sdk.attacks import AttackRunConfig  # noqa: E402
from aicomp_sdk.core.env.opaque import _OpaqueAttackEnv  # noqa: E402
from aicomp_sdk.evaluation.ops import (  # noqa: E402
    EVALUATION_DEFAULT_MAX_TOOL_HOPS,
    build_attack_env,
    resolve_fixtures_dir,
)
from aicomp_sdk.guardrails.optimal import Guardrail as OptimalGuardrail  # noqa: E402
from aicomp_sdk.hooks import HookRegistry  # noqa: E402

from attack import AttackAlgorithm  # noqa: E402


def make_agent_factory(name: str):
    if name == "mock":
        from local_test import MockTargetAgent

        return lambda: MockTargetAgent("compliant")
    from aicomp_sdk.agents import build_agent_factory

    return build_agent_factory(name)


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "mock"
    budget_s = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
    hops = int(sys.argv[3]) if len(sys.argv) > 3 else EVALUATION_DEFAULT_MAX_TOOL_HOPS

    env = _OpaqueAttackEnv(
        build_attack_env(
            seed=123,
            fixtures_dir=resolve_fixtures_dir(),
            agent_factory=make_agent_factory(name),
            guardrail=OptimalGuardrail(),
            env_selection="gym",
            max_tool_hops=hops,
            hook_registry=HookRegistry(),
        )
    )
    env.reset()

    algo = AttackAlgorithm({})
    candidates = algo.run(env, AttackRunConfig(time_budget_s=budget_s, max_tool_hops=hops))

    print(f"=== diagnose target={name} budget={budget_s}s hops={hops} ===")
    print(f"returned candidates: {len(candidates)}")
    print(json.dumps(algo.last_run_summary, indent=2))


if __name__ == "__main__":
    main()
