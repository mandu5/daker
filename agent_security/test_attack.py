"""Invariant tests for attack.py. Run: .venv-aicomp/bin/python -m pytest agent_security/test_attack.py -q

These lock in the evaluator-critical safety properties (valid candidate shapes,
timeout-safe early return, adaptivity, graceful fallback) using the real SDK
evaluator with a mock target. They do NOT test real-model compliance (GPU-only).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aicomp_sdk.attacks import AttackCandidate, AttackRunConfig  # noqa: E402
from aicomp_sdk.core.env.opaque import _OpaqueAttackEnv  # noqa: E402
from aicomp_sdk.evaluation.ops import (  # noqa: E402
    MAX_REPLAY_MESSAGES_PER_FINDING,
    build_attack_env,
    eval_attack,
    resolve_fixtures_dir,
    summarize_attack_findings,
)
from aicomp_sdk.core.env.api import MAX_USER_MESSAGE_CHARS  # noqa: E402
from aicomp_sdk.guardrails.optimal import Guardrail  # noqa: E402
from aicomp_sdk.hooks import HookRegistry  # noqa: E402

import attack  # noqa: E402
from attack import AttackAlgorithm  # noqa: E402
from local_test import MockTargetAgent  # noqa: E402


def _run(personality: str, budget: float, cfg: dict | None = None):
    env = _OpaqueAttackEnv(
        build_attack_env(
            seed=123,
            fixtures_dir=resolve_fixtures_dir(),
            agent_factory=lambda: MockTargetAgent(personality),
            guardrail=Guardrail(),
            env_selection="gym",
            max_tool_hops=4,
            hook_registry=HookRegistry(),
        )
    )
    env.reset()
    algo = AttackAlgorithm(cfg or {})
    cands = algo.run(env, AttackRunConfig(time_budget_s=budget, max_tool_hops=4))
    return algo, cands


def _assert_valid(cands):
    assert isinstance(cands, list)
    for c in cands:
        assert isinstance(c, AttackCandidate)
        assert 1 <= len(c.user_messages) <= MAX_REPLAY_MESSAGES_PER_FINDING
        for m in c.user_messages:
            assert isinstance(m, str) and m.strip()
            assert len(m) <= MAX_USER_MESSAGE_CHARS


def test_candidates_are_valid_shapes():
    _algo, cands = _run("compliant", 6.0)
    _assert_valid(cands)
    assert len(cands) > 0
    # no duplicate message chains (wasted replay)
    assert len({c.user_messages for c in cands}) == len(cands)


def test_run_returns_before_deadline():
    budget = 5.0
    t0 = time.monotonic()
    _algo, _cands = _run("compliant", budget)
    assert time.monotonic() - t0 < budget  # must return before the (fatal) deadline


def test_compliant_scores_via_real_scorer():
    findings = eval_attack(
        AttackAlgorithm, budget_s=8.0,
        agent_factory=lambda: MockTargetAgent("compliant"), env_selection="gym",
    )
    s = summarize_attack_findings(findings)
    assert s["findings_count"] > 0 and s["score_raw"] > 0
    fired = {p["predicate"] for f in findings for p in f["predicates"]}
    assert "EXFILTRATION" in fired


def test_refuser_adapts_to_deputy_only():
    findings = eval_attack(
        AttackAlgorithm, budget_s=8.0,
        agent_factory=lambda: MockTargetAgent("refuser"), env_selection="gym",
    )
    fired = {p["predicate"] for f in findings for p in f["predicates"]}
    # exfil framings all refused -> engine still earns CONFUSED_DEPUTY
    assert fired == {"CONFUSED_DEPUTY"} or fired == set()
    if fired:
        assert "EXFILTRATION" not in fired


def test_dense_multi_message_candidate_fires_per_post():
    env = _OpaqueAttackEnv(
        build_attack_env(
            seed=123, fixtures_dir=resolve_fixtures_dir(),
            agent_factory=lambda: MockTargetAgent("compliant"),
            guardrail=Guardrail(), env_selection="gym", max_tool_hops=4,
            hook_registry=HookRegistry(),
        )
    )
    from aicomp_sdk.core.predicates import eval_predicates
    env.reset()
    msgs = [attack._f_release([attack._url(i * 4 + j) for j in range(4)]) for i in range(3)]
    for m in msgs:
        env.interact(m, max_tool_hops=4)
    tr = env.export_trace_dict()
    assert len(tr["tool_events"]) == 12
    assert len(eval_predicates(tr)) == 12  # one EXFILTRATION per post


def test_blind_fallback_bounded_and_valid(monkeypatch):
    monkeypatch.setattr(attack, "_eval_predicates", None)
    _algo, cands = _run("compliant", 3.0)
    _assert_valid(cands)
    assert 0 < len(cands) <= attack._MAX_FINDINGS
