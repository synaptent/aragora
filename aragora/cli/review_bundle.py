"""Offline exports of one review result; no provider or GitHub calls."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class ReviewBundle:
    """Keep artifact provenance and incomplete execution separate from findings."""

    def __init__(self, args: Any) -> None:
        self.directory = Path(args.output_dir)
        self.context: dict[str, Any] = {
            "review_run_id": str(uuid.uuid4()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pr_url": getattr(args, "pr_url", None),
            "head_sha": getattr(args, "head_sha", None),
            "head_source": "caller_supplied" if getattr(args, "head_sha", None) else "unknown",
            "requested_agents": [a.strip() for a in args.agents.split(",") if a.strip()],
            "demo": bool(getattr(args, "demo", False)),
        }
        parts = urlparse(self.context["pr_url"] or "").path.strip("/").split("/")
        if len(parts) == 4 and parts[2] == "pull" and parts[3].isdigit():
            self.context.update(repository="/".join(parts[:2]), pr_number=int(parts[3]))
        self.reasons: list[str] = []
        self.findings: dict[str, Any] | None = None
        self.result: Any = None
        self.status = "failed"

    def bind_diff(self, diff: str, *, truncated: bool) -> None:
        self.context.update(
            input_diff_sha256=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            input_diff_bytes=len(diff.encode("utf-8")),
            diff_truncated=truncated,
        )
        if truncated:
            self.reasons.append("Only a truncated diff was reviewed.")

    def capture(self, result: Any, findings: dict[str, Any]) -> None:
        self.result, self.findings = result, findings
        if self.context["demo"]:
            self.reasons.append("Demo findings are fabricated; no providers were called.")
        else:
            observed = {
                message.agent
                for message in getattr(result, "messages", [])
                if getattr(message, "content", "").strip()
            }
            missing = [
                agent
                for agent in self.context["requested_agents"]
                if not any(name == agent or name.startswith(agent + "_") for name in observed)
            ]
            self.context.update(
                responding_agents=sorted(observed),
                missing_agents=missing,
                duration_seconds=getattr(result, "duration_seconds", None),
                total_tokens=getattr(result, "total_tokens", None),
                total_cost_usd=getattr(result, "total_cost_usd", None),
            )
            if missing:
                self.reasons.append(
                    "Requested reviewers have no recorded response: " + ", ".join(missing)
                )
            failures = getattr(result, "agent_failures", {})
            if failures:
                self.reasons.append(
                    "Provider failures were recorded: " + ", ".join(sorted(failures))
                )
            state = getattr(result, "debate_status", "completed")
            if state != "completed" or not getattr(result, "final_answer", "").strip():
                self.reasons.append("The debate did not produce a completed result.")
        self.status = "incomplete" if self.reasons else "complete"
        findings["review_context"] = {
            **self.context,
            "status": self.status,
            "limitations": self.reasons[:],
        }

    def write(self, exit_code: int, *, findings_exit: bool = False) -> None:
        # Local imports avoid importing the debate engine when inspecting a manifest.
        from aragora.cli.review import findings_to_sarif, format_github_comment

        if exit_code and not findings_exit:
            self.status = "failed"
            self.reasons.append(f"Review command failed (exit {exit_code}); inspect review.log.")
        if self.findings is None:
            self.reasons.append(
                "No completed review findings are available; this is not a clean review."
            )
        data = {
            key: value for key, value in (self.findings or {}).items() if key != "all_critiques"
        }
        data["summary"] = data.pop("final_summary", "Review unavailable.")
        data["review_context"] = {
            **self.context,
            "status": self.status,
            "limitations": self.reasons[:],
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": "1",
            **data["review_context"],
            "exit_code": exit_code
            or (3 if self.status != "complete" and not self.context["demo"] else 0),
            "files": {},
        }
        try:
            comment = (
                format_github_comment(self.result, self.findings)
                if self.findings is not None
                else "No review verdict is available. Do not treat missing findings as approval."
            )
            context = json.dumps(data["review_context"], indent=2, ensure_ascii=True)
            comment = f"## Review execution: {self.status}\n\n```json\n{context}\n```\n\n{comment}"
            sarif = findings_to_sarif(self.findings or {})
            sarif["runs"][0]["properties"] = {"review_context": data["review_context"]}
            sarif["runs"][0]["invocations"] = [{"executionSuccessful": self.status == "complete"}]
            artifacts = {
                "comment.md": comment,
                "review.json": json.dumps(data, indent=2),
                "review.sarif": json.dumps(sarif, indent=2),
            }
            for name, content in artifacts.items():
                payload = (content + "\n").encode("utf-8")
                (self.directory / name).write_bytes(payload)
                manifest["files"][name] = hashlib.sha256(payload).hexdigest()
        except (OSError, ValueError, TypeError, KeyError):
            manifest.update(
                status="failed", limitations=[*self.reasons, "Artifact rendering failed."]
            )
            raise
        finally:
            (self.directory / "bundle.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
