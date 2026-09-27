from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aragora.agents.transports.claude_vibeproxy import ClaudeVibeProxyAttempt
from aragora.agents.transports.vibeproxy import (
    ResolvedModelRoute,
    TransportMode,
    VibeProxyCatalog,
    VibeProxyResponseError,
    VibeProxyUnavailableError,
)
from scripts import vibeproxy_burnin_recorder as cli


class _Policy:
    mode = TransportMode.REQUIRED

    def resolve(
        self,
        provider: str,
        model: str,
        capabilities: tuple[str, ...],
    ) -> ResolvedModelRoute:
        assert provider == "anthropic"
        assert capabilities == ("chat",)
        return ResolvedModelRoute(
            provider="anthropic",
            requested_model=model,
            resolved_model="anthropic/claude-opus-4.8",
            transport="vibeproxy",
            base_url="http://127.0.0.1:8318/v1",
            capabilities=frozenset({"chat"}),
        )


class _InferenceClient:
    def __init__(
        self,
        models: set[str],
        *,
        owners: dict[str, str] | None = None,
        owner_entries: frozenset[tuple[str, str]] | None = None,
    ) -> None:
        self.models = frozenset(models)
        default_owners = {
            model: (
                "antigravity"
                if model.startswith(("gemini", "google/"))
                else "xai"
                if model.startswith(("grok", "xai/", "x-ai/"))
                else "moonshot"
                if model.startswith(("kimi", "moonshot"))
                else "openai"
                if model.startswith(("gpt-", "openai/"))
                else "anthropic"
                if model.startswith(("claude", "anthropic/"))
                else ""
            )
            for model in models
        }
        self.owners = default_owners if owners is None else owners
        self.owner_entries = (
            frozenset((model, owner) for model, owner in self.owners.items() if owner)
            if owner_entries is None
            else owner_entries
        )
        self.response_model: str | None = None
        self.response_text = "ARAGORA_VIBEPROXY_BURNIN_OK"
        self.failure: BaseException | None = None

    def catalog(self, *, timeout: float) -> VibeProxyCatalog:
        assert timeout > 0
        return VibeProxyCatalog(
            models=self.models,
            fetched_at=0,
            model_owners=self.owner_entries,
        )

    def openai_catalog_alias_request(
        self,
        *,
        protocol: object,
        model: str,
        catalog: VibeProxyCatalog,
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        assert timeout > 0
        assert payload["model"] == model
        assert payload["messages"][0]["content"] == cli.INFERENCE_PROMPT
        assert self.owners[model] == catalog.owner_for(model)
        if self.failure is not None:
            raise self.failure
        return {
            "model": self.response_model or model,
            "choices": [
                {
                    "message": {"content": self.response_text},
                    "finish_reason": "stop",
                }
            ],
        }

    def anthropic_message(
        self,
        *,
        model: str,
        prompt: str,
        timeout: float,
        max_tokens: int,
    ) -> str:
        assert timeout > 0
        assert max_tokens > 0
        assert prompt == cli.INFERENCE_PROMPT
        if self.failure is not None:
            raise self.failure
        return self.response_text


class _InferencePolicy:
    mode = TransportMode.REQUIRED

    def __init__(
        self,
        client: _InferenceClient,
        aliases: dict[str, str] | None = None,
    ) -> None:
        self.client = client
        self.aliases = aliases or {}

    def resolve(
        self,
        provider: str,
        model: str,
        capabilities: tuple[str, ...],
        *,
        timeout: float | None = None,
    ) -> ResolvedModelRoute:
        assert capabilities == ("chat",)
        resolved = self.aliases.get(f"{provider}:{model}", self.aliases.get(model, model))
        catalog = self.client.catalog(timeout=timeout or 1)
        if resolved not in catalog.models:
            raise VibeProxyUnavailableError(f"model not in VibeProxy catalog: {resolved}")
        return ResolvedModelRoute(
            provider=provider,
            requested_model=model,
            resolved_model=resolved,
            transport="vibeproxy",
            base_url="http://127.0.0.1:8318/v1",
            capabilities=frozenset(capabilities),
        )


def _pr(head: str = "a" * 40) -> dict[str, Any]:
    return {
        "number": 9483,
        "state": "OPEN",
        "isDraft": True,
        "title": "VibeProxy transport",
        "body": "Part of #9409",
        "headRefOid": head,
        "url": "https://github.com/synaptent/aragora/pull/9483",
        "files": [{"path": "aragora/agents/transports/claude_vibeproxy.py"}],
    }


def test_inference_records_observed_model_without_response_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({"gemini-3-flash"})
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family="gemini",
        model="gemini-3-flash",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 0
    assert result["record"]["family"] == "gemini"
    assert result["record"]["response_model"] == "gemini-3-flash"
    assert result["record"]["clean"] is True
    assert result["response_body_persisted"] is False
    assert result["countable"] is False
    persisted = (tmp_path / "calls.jsonl").read_text(encoding="utf-8")
    assert client.response_text not in persisted


def test_claude_inference_records_proxy_verified_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({"claude-opus-4-8"})
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family="claude",
        model="claude-opus-4-8",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 0
    assert result["record"]["response_model"] == "claude-opus-4-8"
    assert result["record"]["family_identity_ok"] is True


def test_inference_resolves_alias_and_preserves_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({"google/gemini-3-flash"})
    monkeypatch.setattr(
        cli,
        "_required_policy",
        lambda: _InferencePolicy(
            client,
            aliases={"gemini-3-flash": "google/gemini-3-flash"},
        ),
    )

    code, result = cli.run_inference(
        family="gemini",
        model="gemini-3-flash",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 0
    assert result["record"]["requested_model"] == "gemini-3-flash"
    assert result["record"]["resolved_model"] == "google/gemini-3-flash"
    assert result["record"]["response_model"] == "google/gemini-3-flash"
    assert result["record"]["alias_disclosure"] == {
        "applied": True,
        "source": "ARAGORA_VIBEPROXY_MODEL_MAP",
        "preserved": True,
    }


@pytest.mark.parametrize(
    ("family", "requested_model", "catalog_owner", "response_model"),
    [
        ("openai", "gpt-5.4-mini", "openai", "gpt-5.4-mini-2026-03-17"),
        ("grok", "grok-3-mini-fast", "xai", "grok-4.3"),
    ],
)
def test_inference_preserves_catalog_owner_alias_disclosure(
    family: str,
    requested_model: str,
    catalog_owner: str,
    response_model: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient(
        {requested_model, response_model},
        owners={
            requested_model: catalog_owner,
            response_model: catalog_owner,
        },
    )
    client.response_model = response_model
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family=family,
        model=requested_model,
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 0
    assert result["record"]["requested_model"] == requested_model
    assert result["record"]["resolved_model"] == response_model
    assert result["record"]["response_model"] == response_model
    assert result["record"]["family_identity_ok"] is True
    assert result["record"]["alias_disclosure"] == {
        "applied": True,
        "source": f"VibeProxy /v1/models owned_by={catalog_owner}",
        "family": family,
        "preserved": True,
    }


def test_inference_rejects_opaque_response_model_without_family_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient(
        {"kimi-k2", "k2"},
        owners={
            "kimi-k2": "moonshot",
            "k2": "moonshot",
        },
    )
    client.response_model = "k2"
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family="kimi",
        model="kimi-k2",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["ok"] is True
    assert result["record"]["clean"] is False
    assert result["record"]["error_class"] == "family_identity_error"
    assert result["record"]["identity_errors"] == [
        "resolved_model_family_mismatch",
        "response_model_family_mismatch",
    ]


def test_inference_rejects_cross_family_alias_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient(
        {"grok-3-mini-fast", "gpt-5.5"},
        owners={
            "grok-3-mini-fast": "xai",
            "gpt-5.5": "openai",
        },
    )
    client.response_model = "gpt-5.5"
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family="grok",
        model="grok-3-mini-fast",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["ok"] is False
    assert result["record"]["clean"] is False
    assert result["record"]["error_class"] == "family_identity_error"
    assert "resolved_model_family_mismatch" in result["record"]["identity_errors"]


def test_inference_rejects_missing_catalog_owner_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({"gpt-5.4-mini"}, owners={})
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family="openai",
        model="gpt-5.4-mini",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["ok"] is False
    assert result["record"]["clean"] is False
    assert result["record"]["error_class"] == "alias_disclosure_error"


@pytest.mark.parametrize(
    ("response_in_catalog", "response_owner_entries"),
    [
        (False, frozenset()),
        (
            True,
            frozenset(
                {
                    ("gpt-5.4-mini-2026-03-17", "openai"),
                    ("gpt-5.4-mini-2026-03-17", "xai"),
                }
            ),
        ),
    ],
)
def test_inference_rejects_response_without_unique_catalog_owner(
    response_in_catalog: bool,
    response_owner_entries: frozenset[tuple[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_model = "gpt-5.4-mini"
    response_model = "gpt-5.4-mini-2026-03-17"
    client = _InferenceClient(
        {requested_model, *([response_model] if response_in_catalog else [])},
        owners={requested_model: "openai"},
        owner_entries=frozenset({(requested_model, "openai")}) | response_owner_entries,
    )
    client.response_model = response_model
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family="openai",
        model=requested_model,
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["ok"] is False
    assert result["record"]["clean"] is False
    assert result["record"]["error_class"] == "alias_disclosure_error"


def test_inference_counts_missing_response_model_as_identity_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({"gpt-5.4-mini"})
    client.failure = VibeProxyResponseError("VibeProxy alias response omitted its model identity")
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family="openai",
        model="gpt-5.4-mini",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["response_model"] is None
    assert result["record"]["clean"] is False
    assert result["record"]["error_class"] == "family_identity_error"
    assert result["proof"]["gates"]["family_identity_errors"]["observed"] == 1


@pytest.mark.parametrize(
    ("family", "model"),
    [
        ("claude", "claude-opus-4-8"),
        ("gemini", "gemini-3-flash"),
    ],
)
def test_inference_rejects_wrong_sentinel_response(
    family: str,
    model: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({model})
    client.response_text = "Burn-in complete"
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family=family,
        model=model,
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["ok"] is False
    assert result["record"]["clean"] is False
    assert result["record"]["error_class"] == "sentinel_mismatch"
    assert client.response_text not in (tmp_path / "calls.jsonl").read_text(encoding="utf-8")


def test_inference_rejects_truncated_openai_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({"gemini-3-flash"})
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))
    original_request = client.openai_catalog_alias_request

    def truncated_request(**kwargs: Any) -> dict[str, Any]:
        body = original_request(**kwargs)
        body["choices"][0]["finish_reason"] = "length"
        return body

    monkeypatch.setattr(client, "openai_catalog_alias_request", truncated_request)

    code, result = cli.run_inference(
        family="gemini",
        model="gemini-3-flash",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["ok"] is False
    assert result["record"]["error_class"] == "truncated_response"


def test_inference_failure_is_sanitized_and_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({"grok-4.3"})
    client.failure = VibeProxyUnavailableError("credential=super-secret")
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    code, result = cli.run_inference(
        family="grok",
        model="grok-4.3",
        timeout=10,
        max_tokens=16,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["clean"] is False
    assert result["record"]["error_class"] == "credential_error"
    assert "super-secret" not in json.dumps(result)
    assert "super-secret" not in (tmp_path / "calls.jsonl").read_text(encoding="utf-8")


def test_inference_rejects_declared_family_mismatch_before_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InferenceClient({"gpt-5.5"})
    monkeypatch.setattr(cli, "_required_policy", lambda: _InferencePolicy(client))

    with pytest.raises(cli.BurninRecordError, match="not 'gemini'"):
        cli.run_inference(
            family="gemini",
            model="gpt-5.5",
            timeout=10,
            max_tokens=16,
            records_path=tmp_path / "calls.jsonl",
            proof_path=tmp_path / "latest.json",
        )


def test_shadow_review_is_non_countable_and_never_posts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen_prompts: list[str] = []
    monkeypatch.setattr(cli, "_load_pr", lambda _repo, _pr_number: _pr())
    monkeypatch.setattr(cli, "_load_diff", lambda _repo, _pr_number: "diff --git a/a b/a")
    monkeypatch.setattr(cli, "_required_policy", lambda: _Policy())

    def fake_run(prompt: str, **_kwargs: object) -> ClaudeVibeProxyAttempt:
        seen_prompts.append(prompt)
        return ClaudeVibeProxyAttempt(
            attempted=True,
            required=True,
            ok=True,
            text="No blocking findings.\nVerdict: PASS",
            response_model="anthropic/claude-opus-4.8",
            harness="local VibeProxy",
            timeout_seconds=10,
        )

    monkeypatch.setattr(cli, "run_claude_vibeproxy", fake_run)
    records = tmp_path / "calls.jsonl"
    proof = tmp_path / "latest.json"

    code = cli.main(
        [
            "--json",
            "--records",
            str(records),
            "--proof",
            str(proof),
            "shadow-review",
            "--pr",
            "9483",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["ok"] is True
    assert output["comment_posted"] is False
    assert output["evidence_composed"] is False
    assert output["review_body_persisted"] is False
    assert output["record"]["countable"] is False
    assert output["record"]["shadow_review"]["verdict"] == "PASS"
    assert output["record"]["shadow_review"]["posted"] is False
    assert output["record"]["alias_disclosure"]["source"] == ("ARAGORA_VIBEPROXY_MODEL_MAP")
    assert "NON-COUNTABLE" in seen_prompts[0]
    assert "Exact head: " + "a" * 40 in seen_prompts[0]
    persisted = records.read_text(encoding="utf-8")
    assert "No blocking findings" not in persisted
    assert "gh pr comment" not in Path(cli.__file__).read_text(encoding="utf-8")


def test_shadow_head_drift_is_recorded_but_not_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = iter([_pr(), _pr(), _pr("c" * 40)])
    monkeypatch.setattr(cli, "_load_pr", lambda _repo, _pr_number: next(states))
    monkeypatch.setattr(cli, "_load_diff", lambda _repo, _pr_number: "diff --git a/a b/a")
    monkeypatch.setattr(cli, "_required_policy", lambda: _Policy())
    monkeypatch.setattr(
        cli,
        "run_claude_vibeproxy",
        lambda *_args, **_kwargs: ClaudeVibeProxyAttempt(
            attempted=True,
            required=True,
            ok=True,
            text="Verdict: PASS",
            response_model="anthropic/claude-opus-4.8",
        ),
    )

    code, result = cli.run_shadow_review(
        repo="synaptent/aragora",
        pr_number=9483,
        model="claude-opus-4-8",
        reviewer_timeout=10,
        max_diff_chars=10_000,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["ok"] is True
    assert result["record"]["clean"] is False
    assert result["record"]["error_class"] == "head_drift"
    assert result["record"]["shadow_review"]["head_stable"] is False
    assert result["proof"]["gates"]["shadow_reviews"]["observed"] == 0


def test_shadow_review_without_observed_response_model_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_load_pr", lambda _repo, _pr_number: _pr())
    monkeypatch.setattr(cli, "_load_diff", lambda _repo, _pr_number: "diff --git a/a b/a")
    monkeypatch.setattr(cli, "_required_policy", lambda: _Policy())
    monkeypatch.setattr(
        cli,
        "run_claude_vibeproxy",
        lambda *_args, **_kwargs: ClaudeVibeProxyAttempt(
            attempted=True,
            required=True,
            ok=True,
            text="Verdict: PASS",
        ),
    )

    code, result = cli.run_shadow_review(
        repo="synaptent/aragora",
        pr_number=9483,
        model="claude-opus-4-8",
        reviewer_timeout=10,
        max_diff_chars=10_000,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["response_model"] is None
    assert result["record"]["error_class"] == "missing_response_model"
    assert result["record"]["family_identity_ok"] is False
    assert "missing_response_model" in result["record"]["identity_errors"]
    assert result["proof"]["gates"]["shadow_reviews"]["observed"] == 0


def test_transport_failure_records_stable_error_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_load_pr", lambda _repo, _pr_number: _pr())
    monkeypatch.setattr(cli, "_load_diff", lambda _repo, _pr_number: "diff --git a/a b/a")
    monkeypatch.setattr(cli, "_required_policy", lambda: _Policy())
    monkeypatch.setattr(
        cli,
        "run_claude_vibeproxy",
        lambda *_args, **_kwargs: ClaudeVibeProxyAttempt(
            attempted=True,
            required=True,
            ok=False,
            error="VibeProxy request timed out",
        ),
    )

    code, result = cli.run_shadow_review(
        repo="synaptent/aragora",
        pr_number=9483,
        model="claude-opus-4-8",
        reviewer_timeout=10,
        max_diff_chars=10_000,
        records_path=tmp_path / "calls.jsonl",
        proof_path=tmp_path / "latest.json",
    )

    assert code == 1
    assert result["record"]["error_class"] == "timeout"
    assert result["record"]["response_model"] is None
    assert result["record"]["clean"] is False


def test_summarize_emits_empty_not_ready_schema(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proof = tmp_path / "latest.json"

    code = cli.main(
        [
            "--json",
            "--records",
            str(tmp_path / "missing.jsonl"),
            "--proof",
            str(proof),
            "summarize",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["schema_version"] == "aragora.vibeproxy-burnin-proof.v1"
    assert result["ready"] is False
    assert result["total_records"] == 0
    assert json.loads(proof.read_text(encoding="utf-8")) == result
