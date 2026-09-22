from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE_ROOT = REPO_ROOT / "docs-site" / "docs"
SYNC_SCRIPT = REPO_ROOT / "docs-site" / "scripts" / "sync-docs.js"


def _read_docs_site(path: str) -> str:
    return (DOCS_SITE_ROOT / path).read_text(encoding="utf-8")


def _docs_specs_map_entries() -> dict[str, str]:
    content = SYNC_SCRIPT.read_text(encoding="utf-8")
    return dict(
        re.findall(
            r"'specs/([^']+\.md)'\s*:\s*'specs/([^']+\.md)'",
            content,
        )
    )


def _docs_mirror_map_entries() -> dict[str, str]:
    """Return the full DOC_MAP from sync-docs.js as {source: destination}."""
    content = SYNC_SCRIPT.read_text(encoding="utf-8")
    doc_map_block = re.search(r"const DOC_MAP = \{(.*?)\n\};", content, re.DOTALL)
    if not doc_map_block:
        raise RuntimeError("Could not locate DOC_MAP in sync-docs.js")
    return dict(
        re.findall(
            r"'([^']+\.md)'\s*:\s*'([^']+\.md)'",
            doc_map_block.group(1),
        )
    )


def _docs_mirror_dest_to_source() -> dict[str, str]:
    """Reverse DOC_MAP so we can look up the claimed source for a destination page."""
    return {dest: src for src, dest in _docs_mirror_map_entries().items()}


def test_documentation_index_rewrites_status_and_planning_links() -> None:
    content = _read_docs_site("contributing/documentation-index.md")

    expected_links = [
        "[Aragora Conductor Workflow](../guides/conductor-workflow)",
        "[Aragora Worker Prompt Pack](../guides/worker-prompt-pack)",
        "[Dev Swarm Coordination](./dev-swarm-coordination)",
        "[Conductor Control Plane Implementation Spec](./conductor-control-plane-implementation-spec)",
        "[Feature Discovery](./feature-discovery)",
        "[Feature Gap List](./feature-gap-list)",
        "[Next Steps (Canonical)](./next-steps-canonical)",
        "[Active 6-Week Execution Plan](./execution-next-6-weeks-2026-03-05)",
        "[Documentation Hygiene Register](./documentation-hygiene-and-gap-register)",
        "[Roadmap](./roadmap)",
    ]
    for link in expected_links:
        assert link in content

    unresolved_source_links = [
        "guides/CONDUCTOR_WORKFLOW.md",
        "guides/WORKER_PROMPT_PACK.md",
        "architecture/DEV_SWARM_COORDINATION.md",
        "plans/2026-03-07-conductor-control-plane.md",
        "status/FEATURE_DISCOVERY.md",
        "FEATURE_GAP_LIST.md",
        "status/NEXT_STEPS_CANONICAL.md",
        "status/EXECUTION_NEXT_6_WEEKS_2026-03-05.md",
        "status/DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md",
        "../ROADMAP.md",
    ]
    for link in unresolved_source_links:
        assert link not in content


def test_features_guide_points_to_current_state_docs_site_pages() -> None:
    content = _read_docs_site("guides/features.md")

    expected_links = [
        "[STATUS](../contributing/status)",
        "[FEATURE_DISCOVERY](../contributing/feature-discovery)",
        "[FEATURE_GAP_LIST](../contributing/feature-gap-list)",
        "[DOCUMENTATION_HYGIENE_AND_GAP_REGISTER](../contributing/documentation-hygiene-and-gap-register)",
    ]
    for link in expected_links:
        assert link in content

    unresolved_source_links = [
        "[FEATURE_DISCOVERY](FEATURE_DISCOVERY.md)",
        "[FEATURE_GAP_LIST](../FEATURE_GAP_LIST.md)",
        "[DOCUMENTATION_HYGIENE_AND_GAP_REGISTER](DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md)",
    ]
    for link in unresolved_source_links:
        assert link not in content


def test_commercial_overview_rewrites_current_proof_status_links() -> None:
    content = _read_docs_site("enterprise/commercial-overview.md")

    expected_links = [
        "[status/NEXT_STEPS_CANONICAL.md](../contributing/next-steps-canonical)",
        "[status/ACTIVE_EXECUTION_ISSUES.md](../contributing/active-execution-issues)",
        "[status/B0_BENCHMARK_TRUTH_STATUS.md](../contributing/b0-benchmark-truth-status)",
        "[status/TW03_RESCUE_PRODUCTIZATION_STATUS.md](../contributing/tw03-rescue-productization-status)",
    ]
    for link in expected_links:
        assert link in content

    unresolved_source_links = [
        "[status/NEXT_STEPS_CANONICAL.md](status/NEXT_STEPS_CANONICAL.md)",
        "[status/ACTIVE_EXECUTION_ISSUES.md](status/ACTIVE_EXECUTION_ISSUES.md)",
        "[status/B0_BENCHMARK_TRUTH_STATUS.md](status/B0_BENCHMARK_TRUTH_STATUS.md)",
        "[status/TW03_RESCUE_PRODUCTIZATION_STATUS.md](status/TW03_RESCUE_PRODUCTIZATION_STATUS.md)",
    ]
    for link in unresolved_source_links:
        assert link not in content


# Pre-existing fallback mirror destinations: pages that were already mirrored
# into the docs-site before the docs/specs DOC_MAP work. The original guard
# only asserted their existence; the parity test below also asserts that each
# destination still matches the source claimed by sync-docs.js's DOC_MAP.
DOCS_SITE_FALLBACK_MIRROR_PAGES: list[Path] = [
    DOCS_SITE_ROOT / "contributing" / "2026-03-26-pmf-14-day-execution-plan.md",
    DOCS_SITE_ROOT / "contributing" / "active-execution-issues.md",
    DOCS_SITE_ROOT / "contributing" / "b0-benchmark-truth-status.md",
    DOCS_SITE_ROOT / "contributing" / "aragora-evolution-roadmap.md",
    DOCS_SITE_ROOT / "contributing" / "canonical-goals.md",
    DOCS_SITE_ROOT / "contributing" / "claude.md",
    DOCS_SITE_ROOT / "contributing" / "conductor-control-plane-implementation-spec.md",
    DOCS_SITE_ROOT / "contributing" / "dev-swarm-coordination.md",
    DOCS_SITE_ROOT / "contributing" / "documentation-hygiene-and-gap-register.md",
    DOCS_SITE_ROOT / "contributing" / "execution-next-6-weeks-2026-03-05.md",
    DOCS_SITE_ROOT / "contributing" / "extended-readme.md",
    DOCS_SITE_ROOT / "contributing" / "feature-discovery.md",
    DOCS_SITE_ROOT / "contributing" / "feature-gap-list.md",
    DOCS_SITE_ROOT / "contributing" / "mission-cadence-m0-m1.md",
    DOCS_SITE_ROOT / "contributing" / "next-steps-canonical.md",
    DOCS_SITE_ROOT / "contributing" / "pmf-dogfood-execution-plan.md",
    DOCS_SITE_ROOT / "contributing" / "pmf-scorecard.md",
    DOCS_SITE_ROOT / "contributing" / "roadmap.md",
    DOCS_SITE_ROOT / "contributing" / "roadmap-intake-register.md",
    DOCS_SITE_ROOT / "contributing" / "strategy-as-bounded-mission-cadence-design.md",
    DOCS_SITE_ROOT / "contributing" / "tw03-rescue-productization-status.md",
    DOCS_SITE_ROOT / "guides" / "conductor-workflow.md",
    DOCS_SITE_ROOT / "guides" / "marketplace.md",
    DOCS_SITE_ROOT / "guides" / "swarm-dogfood-operator.md",
    DOCS_SITE_ROOT / "guides" / "worker-prompt-pack.md",
    DOCS_SITE_ROOT / "enterprise" / "secrets.md",
]


def test_docs_site_sync_creates_linked_status_and_planning_pages() -> None:
    expected_pages = DOCS_SITE_FALLBACK_MIRROR_PAGES

    for page in expected_pages:
        assert page.exists(), f"Expected synced docs-site page missing: {page}"


def test_docs_site_sync_fallback_mirror_pages_match_source_content() -> None:
    """Regenerate the docs-site mirror in a temp directory and assert parity.

    The existence-only check above can be fooled by a stale destination file
    that no longer corresponds to its claimed docs/ source. This test runs
    sync-docs.js against a clean copy of the docs sources and compares each
    pre-existing fallback mirror destination to the freshly generated page.
    If a destination differs from the source it is claimed to come from, the
    test fails.
    """
    dest_to_source = _docs_mirror_dest_to_source()
    root_source_files = {src for src in dest_to_source.values() if src.startswith("../")}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shutil.copytree(REPO_ROOT / "docs", tmp_path / "docs")
        shutil.copytree(
            REPO_ROOT / "docs-site" / "scripts",
            tmp_path / "docs-site" / "scripts",
        )
        for src_rel in root_source_files:
            src = (REPO_ROOT / "docs" / src_rel).resolve()
            shutil.copy2(src, tmp_path / src.name)

        subprocess.run(
            ["node", str(tmp_path / "docs-site" / "scripts" / "sync-docs.js")],
            cwd=tmp_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        mismatches: list[str] = []
        for page in DOCS_SITE_FALLBACK_MIRROR_PAGES:
            rel = page.relative_to(DOCS_SITE_ROOT)
            generated = tmp_path / "docs-site" / "docs" / rel
            if not generated.exists():
                mismatches.append(f"{rel}: generated page missing from fresh sync")
                continue
            if generated.read_text(encoding="utf-8") != page.read_text(encoding="utf-8"):
                mismatches.append(f"{rel}: content differs from fresh sync")

        assert not mismatches, "\n".join(
            [
                "Pre-existing fallback mirror destinations do not match a fresh sync-docs.js run. "
                "Either the mirror is stale or the destination is no longer generated from the claimed source.",
                *mismatches,
            ]
        )


# Pre-existing docs/reference mirror pairs: docs/reference/<NAME>.md source
# files that were already mirrored into the docs-site through a pre-existing
# DOC_MAP entry (an unambiguous basename fallback or an explicit
# non-`reference/`-prefixed key) BEFORE the docs/reference/** DOC_MAP work.
# Each pair binds a claimed SOURCE to its specific checked-in DESTINATION via
# an expected-content marker read from the SOURCE file at test time --
# independent of running sync-docs.js, so a wrong-source resolver mapping
# cannot regenerate matching wrong content and pass (the resolver is not its
# own oracle here).
#
# The pair table below is derived from PR #9066's review context
# (DOCS_REFERENCE_PRE_EXISTING_MIRROR, read via `gh pr diff 9066`) as a
# READ-ONLY reference for the claimed source->destination pairs. No #9066
# hunks are included in this diff: this is a tests-only literal, and #9066's
# sync-docs.js edits remain unmerged (parked Tier-2 operator-review). When PR
# #9066 merges, its DOCS_REFERENCE_PRE_EXISTING_MIRROR dict should be unified
# with this pair table (cosmetic follow-up -- comment only, no behavior change
# here; do not resubmit #9066's sync-docs.js diff).
DOCS_REFERENCE_PRE_EXISTING_MIRROR_PAIRS: dict[str, str] = {
    "ACCOUNTING.md": "guides/accounting.md",
    "ADMIN.md": "admin/overview.md",
    "BILLING.md": "enterprise/billing.md",
    "BILLING_UNITS.md": "enterprise/billing-units.md",
    "CLI_REFERENCE.md": "api/cli.md",
    "CONFIGURATION.md": "getting-started/configuration.md",
    "CONTROL_PLANE.md": "enterprise/control-plane-overview.md",
    "DATABASE.md": "deployment/database.md",
    "DATABASE_SCHEMA.md": "deployment/database-schema.md",
    "DEPENDENCIES.md": "contributing/dependencies.md",
    "DEPRECATION_POLICY.md": "contributing/deprecation.md",
    "DOCUMENTS.md": "guides/documents.md",
    "ENVIRONMENT.md": "getting-started/environment.md",
    "HANDLERS.md": "contributing/handlers.md",
    "LIBRARY_USAGE.md": "guides/library-usage.md",
}


def _source_h1_marker(path: Path) -> str:
    """Return the first H1 heading text from a markdown source.

    Frontmatter (if present) is skipped first. Used as a distinctive content
    marker read from the SOURCE file at test time, independent of sync-docs.js.
    """
    content = path.read_text(encoding="utf-8")
    body = re.sub(r"\A---\n.*?\n---\n", "", content, count=1, flags=re.DOTALL)
    match = re.search(r"^# (.+)$", body, re.MULTILINE)
    if not match:
        raise AssertionError(f"No H1 heading found in source {path}")
    return match.group(1).strip()


def test_docs_reference_pre_existing_mirror_binds_source_to_destination() -> None:
    """Independent source-identity binding for the docs/reference mirrors.

    The fallback-pages parity test above regenerates via sync-docs.js and
    compares, so the resolver is its own oracle: a wrong-source mapping still
    regenerates matching wrong content and passes. This test does NOT invoke
    sync-docs.js. For each claimed pair it reads the SOURCE
    docs/reference/<NAME>.md file at test time, extracts a distinctive content
    marker (the source H1 heading), and asserts that marker appears in the
    checked-in DESTINATION docs-site page. A wrong-source mapping fails because
    the wrong source's H1 will not be present in the real destination; a stale
    destination fails because its content no longer carries the source marker.
    """
    for source_name, dest_rel in DOCS_REFERENCE_PRE_EXISTING_MIRROR_PAIRS.items():
        source_path = REPO_ROOT / "docs" / "reference" / source_name
        dest_path = DOCS_SITE_ROOT / dest_rel

        assert source_path.exists(), (
            f"DOCS_REFERENCE_PRE_EXISTING_MIRROR_PAIRS claims source "
            f"docs/reference/{source_name}, but that file is missing."
        )
        assert dest_path.exists(), (
            f"DOCS_REFERENCE_PRE_EXISTING_MIRROR_PAIRS claims destination "
            f"docs-site/docs/{dest_rel} for docs/reference/{source_name}, "
            f"but that page is missing."
        )

        marker = _source_h1_marker(source_path)
        dest_content = dest_path.read_text(encoding="utf-8")
        assert marker in dest_content, (
            f"docs/reference/{source_name} (H1 marker {marker!r}) is claimed to "
            f"be mirrored at docs-site/docs/{dest_rel}, but the destination does "
            f"not contain that marker. The destination may be stale, mapped from "
            f"the wrong source, or the source H1 may have changed without a sync."
        )


def test_active_execution_links_to_synced_roadmap_intake_register() -> None:
    active = _read_docs_site("contributing/active-execution-issues.md")
    roadmap = _read_docs_site("contributing/roadmap.md")

    assert "[the intake register](./roadmap-intake-register#strategy-mission-queue)" in active
    assert "[Strategy Mission Queue](./roadmap-intake-register#strategy-mission-queue)" in active
    assert "[Roadmap intake register](./roadmap-intake-register)" in roadmap
    assert "ROADMAP_INTAKE_REGISTER.md" not in active
    assert "docs/status/ROADMAP_INTAKE_REGISTER.md" not in roadmap


def test_roadmap_intake_register_links_to_synced_superpowers_pages() -> None:
    content = _read_docs_site("contributing/roadmap-intake-register.md")

    assert (
        "[`docs/superpowers/specs/2026-06-26-strategy-as-bounded-mission-cadence-design.md`]"
        "(./strategy-as-bounded-mission-cadence-design)"
    ) in content
    assert (
        "[`docs/superpowers/plans/2026-06-26-mission-cadence-m0-m1.md`](./mission-cadence-m0-m1)"
    ) in content
    assert "../superpowers/" not in content


def test_synced_plan_preserves_python_f_string_braces_inside_fences() -> None:
    content = _read_docs_site("contributing/mission-cadence-m0-m1.md")

    assert 'f"unexpected columns: {header}"' in content
    assert 'f"missing mission rows: {ids}"' in content
    assert r"\{header\}" not in content
    assert r"\{ids\}" not in content


def test_cli_reference_preserves_generated_catalog_description() -> None:
    content = _read_docs_site("api/cli.md")

    assert "title: Aragora CLI Reference" in content
    assert "description: Generated Aragora CLI command catalog from live parser" in content


def test_disaster_recovery_links_resolve_by_source_directory_not_last_doc_map_entry() -> None:
    # DISASTER_RECOVERY.md is the basename of three DOC_MAP entries (deployment/,
    # runbooks/, enterprise/). A bare "DISASTER_RECOVERY.md" link must resolve
    # relative to the linking source's own directory, not to whichever DOC_MAP
    # entry for that basename happens to be defined last.
    deployment_async = _read_docs_site("deployment/async-gateway.md")
    deployment_volumes = _read_docs_site("deployment/container-volumes.md")
    enterprise_compliance = _read_docs_site("enterprise/compliance.md")
    production_readiness = _read_docs_site("operations/production-readiness.md")
    runbook_backup = _read_docs_site("operations/runbook-backup-automation.md")
    runbook_multi_region = _read_docs_site("operations/runbook-multi-region-setup.md")
    runbook_pg_migration = _read_docs_site("operations/runbook-postgresql-migration.md")
    runbook_pg_replication = _read_docs_site("operations/runbook-postgresql-replication.md")
    disaster_recovery_runbook = _read_docs_site("operations/disaster-recovery-runbook.md")

    # deployment/ siblings resolve to the deployment DR page. Previously these
    # silently mis-resolved to the runbooks DR page (the last DOC_MAP entry
    # sharing the "DISASTER_RECOVERY.md" basename).
    assert "[DISASTER_RECOVERY.md](./disaster-recovery)" in deployment_async
    assert "[DISASTER_RECOVERY.md](./disaster-recovery)" in deployment_volumes

    # PRODUCTION_READINESS.md's source lives in docs/deployment/, so its two bare
    # links are deployment/ sibling references too, not runbooks/ references.
    assert (
        production_readiness.count("[DISASTER_RECOVERY.md](../deployment/disaster-recovery)") == 2
    )

    # COMPLIANCE.md's source lives in docs/enterprise/, so its bare link is a
    # sibling reference to the (newly mapped) enterprise DR overview.
    assert "[DISASTER_RECOVERY.md](./disaster-recovery)" in enterprise_compliance

    # runbooks/ siblings correctly resolve to the runbooks DR page. Pin this down
    # so a future DOC_MAP reordering cannot silently break it the way the
    # deployment/ and enterprise/ links were broken.
    assert "[DISASTER_RECOVERY.md](./disaster-recovery-runbook)" in runbook_backup
    assert "[DISASTER_RECOVERY.md](./disaster-recovery-runbook)" in runbook_multi_region
    assert "[DISASTER_RECOVERY.md](./disaster-recovery-runbook)" in runbook_pg_migration
    assert "[DISASTER_RECOVERY.md](./disaster-recovery-runbook)" in runbook_pg_replication

    # The runbook route itself is public-safe generated output, so it should keep
    # navigable links to the related public-safe DR pages without exposing the
    # source runbook body.
    assert (
        "[Deployment disaster recovery overview](../deployment/disaster-recovery)"
        in disaster_recovery_runbook
    )
    assert (
        "[Enterprise disaster recovery overview](../enterprise/disaster-recovery)"
        in disaster_recovery_runbook
    )

    for content in [
        deployment_async,
        deployment_volumes,
        enterprise_compliance,
        production_readiness,
        runbook_backup,
        runbook_multi_region,
        runbook_pg_migration,
        runbook_pg_replication,
        disaster_recovery_runbook,
    ]:
        assert "DISASTER_RECOVERY.md)" not in content


def test_disaster_recovery_docs_site_pages_are_mapped_and_public_safe() -> None:
    # Source DR docs include operational runbook details. The docs-site routes
    # must stay valid without publishing internal topology, commands, or response
    # rosters.
    expected_pages = {
        "deployment/disaster-recovery.md": "Deployment Disaster Recovery Overview",
        "enterprise/disaster-recovery.md": "Enterprise Disaster Recovery Overview",
        "operations/disaster-recovery-runbook.md": (
            "Operations Disaster Recovery Runbook Overview"
        ),
    }

    for rel_path, title in expected_pages.items():
        page = DOCS_SITE_ROOT / rel_path
        assert page.exists(), f"Expected synced docs-site page missing: {page}"

        content = page.read_text(encoding="utf-8")
        assert f"title: {title}" in content
        assert "restricted to authorized" in content
        assert "Classification: Internal" not in content
        assert "Primary Region (us-east-1)" not in content
        assert "s3://aragora-backups" not in content
        assert "kubectl --context backup" not in content
        assert "Incident commander" not in content
        assert "grafana.aragora.internal" not in content
        assert "verify-backup-region" not in content


def test_ambiguous_readme_basename_links_resolve_to_valid_targets() -> None:
    # README.md is also a multi-way-ambiguous basename (case-studies/README.md and
    # ADR/README.md both map to it), and several other source docs link to
    # non-docs-site README.md files (e.g. aragora/mcp/README.md, deploy/README.md)
    # that are intentionally outside DOC_MAP. The resolver must still fail closed
    # instead of guessing the ADR README, but known repo docs and docs-site pages
    # should rewrite to stable valid destinations instead of leaving broken
    # source-relative links in relocated generated docs.
    reference = _read_docs_site("api/reference.md")
    status = _read_docs_site("contributing/status.md")
    extended_readme = _read_docs_site("contributing/extended-readme.md")
    sdk_consolidation = _read_docs_site("guides/sdk-consolidation.md")
    sdk_quickstart = _read_docs_site("guides/sdk-quickstart.md")
    eu_ai_act_guide = _read_docs_site("security/eu-ai-act-guide.md")

    assert (
        "[MCP README]"
        "(https://github.com/synaptent/aragora/blob/main/aragora/mcp/README.md)" in reference
    )
    assert "[README](https://github.com/synaptent/aragora/blob/main/README.md)" in status
    assert "[README](https://github.com/synaptent/aragora/blob/main/README.md)" in extended_readme
    assert (
        "[algorithms/README.md]"
        "(https://github.com/synaptent/aragora/blob/main/docs/algorithms/README.md)"
        in extended_readme
    )
    assert (
        "[sdk/typescript/README.md]"
        "(https://github.com/synaptent/aragora/blob/main/sdk/typescript/README.md)"
        in sdk_consolidation
    )
    assert (
        "[`deploy/README.md`]"
        "(https://github.com/synaptent/aragora/blob/main/deploy/README.md)" in sdk_quickstart
    )
    assert "[Gauntlet Testing](../guides/gauntlet)" in eu_ai_act_guide

    for content in [
        reference,
        status,
        extended_readme,
        sdk_consolidation,
        sdk_quickstart,
        eu_ai_act_guide,
    ]:
        assert "analysis/adr" not in content
        for target in [
            "../../aragora/mcp/README.md",
            "../README.md",
            "algorithms/README.md",
            "../deploy/README.md",
            "../../aragora/gauntlet/README.md",
        ]:
            assert f"]({target})" not in content


# docs/specs/*.md files that are deliberately excluded from the docs-site
# mirror (e.g. a draft or an operator-gated spec not meant for public
# publication). Every current docs/specs/*.md file is either mirrored via
# DOC_MAP or listed here; test_docs_specs_directory_is_mirrored consults this
# set so a future deliberate exclusion has an explicit, reviewable home instead
# of a silent special case grown into the assertion logic below.
DOCS_SPECS_MIRROR_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Archival Tier-4 packet; operator-gated and not meant for public docs-site
        # publication unless a future DOC_MAP entry is explicitly approved.
        "2026-07-01-adjudicator-wiring-tier4-packet.md",
        # Proposed Tier-4 merge-authority policy; keep it private until the
        # required human preapproval explicitly authorizes publication.
        "OPERATOR_ADVISORY_SETTLEMENT.md",
    }
)


def _default_specs_mirror_dest(source_name: str) -> str:
    return f"{source_name.removesuffix('.md').lower().replace('_', '-')}.md"


def _allowlisted_spec_publication_artifacts(source_names: frozenset[str] | set[str]) -> list[str]:
    index_content = _read_docs_site("specs/index.md")
    artifacts: list[str] = []

    for source_name in sorted(source_names):
        dest_name = _default_specs_mirror_dest(source_name)
        slug = dest_name.removesuffix(".md")
        page = DOCS_SITE_ROOT / "specs" / dest_name

        if page.exists():
            artifacts.append(str(page.relative_to(REPO_ROOT)))
        if f"](./{slug})" in index_content:
            artifacts.append(f"docs-site/docs/specs/index.md -> ./{slug}")

    return artifacts


def test_docs_specs_directory_is_mirrored() -> None:
    # docs/specs/** was previously entirely outside DOC_MAP: any relative link
    # from a mirrored doc into it survived sync unmodified and 404d on the
    # deployed docs-site. The expected mirror set is derived from a live glob
    # of docs/specs/*.md -- never a hard-coded page list -- so a future spec
    # file added without a DOC_MAP entry fails here instead of silently
    # shipping unmirrored.
    mapped_specs = _docs_specs_map_entries()
    source_specs = sorted(path.name for path in (REPO_ROOT / "docs" / "specs").glob("*.md"))
    expected_mirrored = [name for name in source_specs if name not in DOCS_SPECS_MIRROR_ALLOWLIST]

    still_mapped_allowlisted = sorted(set(mapped_specs) & DOCS_SPECS_MIRROR_ALLOWLIST)
    assert not still_mapped_allowlisted, (
        "docs/specs/*.md file(s) are listed in DOCS_SPECS_MIRROR_ALLOWLIST but "
        f"still have DOC_MAP entries: {still_mapped_allowlisted}. Remove the "
        "DOC_MAP entry when a spec is deliberately excluded from the docs-site mirror."
    )

    allowlisted_publication_artifacts = _allowlisted_spec_publication_artifacts(
        DOCS_SPECS_MIRROR_ALLOWLIST
    )
    assert not allowlisted_publication_artifacts, (
        "docs/specs/*.md file(s) are listed in DOCS_SPECS_MIRROR_ALLOWLIST but "
        "still have docs-site publication artifacts: "
        f"{allowlisted_publication_artifacts}. Remove stale generated pages and "
        "index links when a spec is deliberately excluded from the docs-site mirror."
    )

    missing_doc_map_entries = sorted(set(expected_mirrored) - set(mapped_specs))
    assert not missing_doc_map_entries, (
        "docs/specs/*.md file(s) missing a DOC_MAP entry in "
        f"docs-site/scripts/sync-docs.js: {missing_doc_map_entries}. Add a "
        "'specs/<NAME>.md': 'specs/<slug>.md' DOC_MAP entry, or add the "
        "filename to DOCS_SPECS_MIRROR_ALLOWLIST above if it is deliberately "
        "excluded from the mirror."
    )

    stale_doc_map_entries = sorted(set(mapped_specs) - set(source_specs))
    assert not stale_doc_map_entries, (
        "docs-site/scripts/sync-docs.js has specs/ DOC_MAP entries for file(s) "
        f"no longer present under docs/specs/: {stale_doc_map_entries}"
    )

    for source_name, dest in mapped_specs.items():
        page = DOCS_SITE_ROOT / "specs" / dest
        assert page.exists(), (
            f"Expected synced docs-site page missing for docs/specs/{source_name}: {page}"
        )

    assert (DOCS_SITE_ROOT / "specs" / "index.md").exists()


def test_docs_specs_allowlist_artifact_detector_finds_published_specs() -> None:
    artifacts = _allowlisted_spec_publication_artifacts({"OPEN_DECISION_RECEIPT.md"})

    assert "docs-site/docs/specs/open-decision-receipt.md" in artifacts
    assert "docs-site/docs/specs/index.md -> ./open-decision-receipt" in artifacts


def test_docs_specs_index_lists_mirrored_children() -> None:
    content = _read_docs_site("specs/index.md")

    assert "## In This Section" in content
    for dest in _docs_specs_map_entries().values():
        slug = dest.removesuffix(".md")
        assert f"](./{slug})" in content


def test_specs_sidebar_is_registered() -> None:
    content = (REPO_ROOT / "docs-site" / "sidebars.js").read_text(encoding="utf-8")

    assert "specsSidebar" in content
    assert "dirName: 'specs'" in content


def test_mdx_prose_brace_sets_are_escaped_outside_fences() -> None:
    content = _read_docs_site("specs/tamper-evident-trail.md")

    assert r"\{push, merge, branch delete," in content
    assert "class {push, merge, branch delete," not in content


def test_docs_specs_intra_directory_links_resolve_to_mirrored_siblings() -> None:
    # Links between docs/specs/*.md files (e.g. OPEN_DECISION_RECEIPT.md <->
    # TAMPER_EVIDENT_TRAIL.md) must resolve via the source-relative lookup to
    # their mirrored specs/ siblings, not survive as raw source-relative .md
    # targets that 404 once relocated under docs-site/docs/specs/.
    open_decision_receipt = _read_docs_site("specs/open-decision-receipt.md")
    receipt_lineage = _read_docs_site("specs/receipt-lineage-reconciliation.md")
    independent_verifier = _read_docs_site("specs/independent-verifier-guide.md")
    odr_native_mapping = _read_docs_site("specs/odr-native-mapping.md")

    assert "[`docs/specs/TAMPER_EVIDENT_TRAIL.md`](./tamper-evident-trail)" in open_decision_receipt
    assert "[`TAMPER_EVIDENT_TRAIL.md`](./tamper-evident-trail)" in open_decision_receipt
    assert "[`odr-native-mapping.md`](./odr-native-mapping)" in open_decision_receipt

    assert "[`docs/specs/OPEN_DECISION_RECEIPT.md`](./open-decision-receipt)" in receipt_lineage
    assert "[`docs/specs/odr-native-mapping.md`](./odr-native-mapping)" in receipt_lineage

    assert (
        "[`docs/specs/OPEN_DECISION_RECEIPT.md`](./open-decision-receipt)" in independent_verifier
    )
    assert (
        "[`docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md`](./receipt-lineage-reconciliation)"
        in independent_verifier
    )
    assert "[`OPEN_DECISION_RECEIPT.md`](./open-decision-receipt)" in independent_verifier

    assert "[`OPEN_DECISION_RECEIPT.md`](./open-decision-receipt)" in odr_native_mapping

    for content in [
        open_decision_receipt,
        receipt_lineage,
        independent_verifier,
        odr_native_mapping,
    ]:
        assert "TAMPER_EVIDENT_TRAIL.md)" not in content
        assert "OPEN_DECISION_RECEIPT.md)" not in content
        assert "RECEIPT_LINEAGE_RECONCILIATION.md)" not in content
        assert "odr-native-mapping.md)" not in content


def test_documentation_index_links_into_specs_use_mirrored_relative_paths() -> None:
    # docs/INDEX.md used to route these three links through absolute GitHub blob
    # URLs (and a "Notes" caveat) specifically because docs/specs/ wasn't
    # mirrored. Now that it is, the mirrored index must link to the real
    # docs-site specs/ pages instead of GitHub, and the stale caveat must be gone.
    content = _read_docs_site("contributing/documentation-index.md")

    assert "[Open Decision Receipt Spec](../specs/open-decision-receipt)" in content
    assert "[Receipt Lineage Reconciliation](../specs/receipt-lineage-reconciliation)" in content
    assert "[Independent Verifier Guide](../specs/independent-verifier-guide)" in content

    assert "github.com/synaptent/aragora/blob/main/docs/specs" not in content
    assert "is not mirrored into" not in content


def test_receipt_contract_link_resolves_to_absolute_repo_url_not_mirrored() -> None:
    # docs/RECEIPT_CONTRACT.md is an operator-gated canonical statement (see
    # mission AGENTS.md "Operator-gated" list) that specs quote and link to. It
    # is intentionally NOT given a DOC_MAP mirror entry -- publishing it onto the
    # docs site for the first time is a gated decision outside this feature's
    # scope -- so its links resolve to an absolute GitHub blob URL instead of
    # 404ing as a raw relative path.
    receipt_lineage = _read_docs_site("specs/receipt-lineage-reconciliation.md")

    assert (
        "[`docs/RECEIPT_CONTRACT.md`]"
        "(https://github.com/synaptent/aragora/blob/main/docs/RECEIPT_CONTRACT.md)"
    ) in receipt_lineage
    assert "](../RECEIPT_CONTRACT.md)" not in receipt_lineage


def test_aragora_verify_readme_link_resolves_to_absolute_repo_url() -> None:
    # aragora-verify/ is a standalone top-level package (like the root, mcp,
    # deploy, and sdk README.md targets already pinned above), not part of the
    # docs/ mirror boundary. It is intentionally left unmirrored and pointed at
    # an absolute GitHub blob URL rather than given a DOC_MAP entry.
    content = _read_docs_site("specs/independent-verifier-guide.md")

    assert (
        "[`aragora-verify/README.md`]"
        "(https://github.com/synaptent/aragora/blob/main/aragora-verify/README.md)"
    ) in content
    assert "](../../aragora-verify/README.md)" not in content


def test_architecture_charter_links_resolve_to_absolute_repo_urls() -> None:
    # docs/architecture/ARCHITECTURE.md links to two siblings -- INTENDED_ARCHITECTURE.md
    # and charters.yaml (not markdown, so it can never get a DOC_MAP mirror entry) --
    # that are outside the mirror set. Left bare, these are source-relative links that
    # would otherwise survive the sync unrewritten and 404 from core-concepts/ on the
    # live site, the same failure mode this feature closes for docs/specs/**.
    content = _read_docs_site("core-concepts/architecture.md")

    assert (
        "[`docs/architecture/INTENDED_ARCHITECTURE.md`]"
        "(https://github.com/synaptent/aragora/blob/main/"
        "docs/architecture/INTENDED_ARCHITECTURE.md)"
    ) in content
    assert (
        "[`charters.yaml`]"
        "(https://github.com/synaptent/aragora/blob/main/docs/architecture/charters.yaml)"
    ) in content
    assert "](INTENDED_ARCHITECTURE.md)" not in content
    assert "](charters.yaml)" not in content


def test_agent_operating_loop_link_resolves_to_canonical_repo_url() -> None:
    content = _read_docs_site("contributing/aragora-evolution-roadmap.md")

    assert (
        "[Agent Operating Loop]"
        "(https://github.com/synaptent/aragora/blob/main/"
        "docs/architecture/agent-operating-loop.md)"
    ) in content
    assert "](../architecture/agent-operating-loop.md)" not in content


# docs/reference/*.md files that are already mirrored into the docs-site
# through a pre-existing DOC_MAP entry whose destination is not under
# `reference/` through an unambiguous basename fallback or an explicit
# non-reference/-prefixed key (CLI_REFERENCE.md, under API Reference). Left as-is rather than duplicated
# under `reference/` to avoid publishing the same content at two docs-site
# URLs. test_docs_reference_directory_is_mirrored treats these as
# already-covered and separately asserts their claimed destination still
# exists, so drift (the file moving, or its DOC_MAP entry disappearing)
# still fails loudly.
DOCS_REFERENCE_PRE_EXISTING_MIRROR: dict[str, str] = {
    "ACCOUNTING.md": "guides/accounting.md",
    "ADMIN.md": "admin/overview.md",
    "BILLING.md": "enterprise/billing.md",
    "BILLING_UNITS.md": "enterprise/billing-units.md",
    "CLI_REFERENCE.md": "api/cli.md",
    "CONFIGURATION.md": "getting-started/configuration.md",
    "CONTROL_PLANE.md": "enterprise/control-plane-overview.md",
    "DATABASE.md": "deployment/database.md",
    "DATABASE_SCHEMA.md": "deployment/database-schema.md",
    "DEPENDENCIES.md": "contributing/dependencies.md",
    "DEPRECATION_POLICY.md": "contributing/deprecation.md",
    "DOCUMENTS.md": "guides/documents.md",
    "ENVIRONMENT.md": "getting-started/environment.md",
    "HANDLERS.md": "contributing/handlers.md",
    "LIBRARY_USAGE.md": "guides/library-usage.md",
    "SLA.md": "enterprise/sla.md",
}

# docs/reference/*.md files that are deliberately excluded from the
# docs-site mirror. PRICING_TIERS.md contains stale commercial terms that
# conflict with the public docs/PRICING.md surface. Keep it repository-visible
# for reconciliation without publishing a second customer-facing promise.
DOCS_REFERENCE_MIRROR_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PRICING_TIERS.md",
    }
)

DOCS_REFERENCE_WITHHELD_PUBLICATION_PATHS: dict[str, str] = {
    "PRICING_TIERS.md": "reference/pricing-tiers.md",
}


def _docs_reference_map_entries() -> dict[str, str]:
    content = SYNC_SCRIPT.read_text(encoding="utf-8")
    return dict(
        re.findall(
            r"'reference/([^']+\.md)'\s*:\s*'reference/([^']+\.md)'",
            content,
        )
    )


def test_docs_reference_directory_is_mirrored() -> None:
    # docs/reference/** was previously outside DOC_MAP except for a handful of
    # files that happened to resolve via resolveSourcePath()'s basename
    # fallback or an explicit non-reference/-prefixed entry (both tracked in
    # DOCS_REFERENCE_PRE_EXISTING_MIRROR). Any other relative link from a
    # mirrored doc into it (e.g. docs/INDEX.md -> INSTALL_MATRIX.md) survived
    # sync unmodified and 404d on the deployed docs-site. The expected mirror
    # set is derived from a live glob of docs/reference/*.md -- never a
    # hard-coded page list -- so a future reference file added without a
    # DOC_MAP entry fails here instead of silently shipping unmirrored.
    mapped_reference = _docs_reference_map_entries()
    source_reference = sorted(path.name for path in (REPO_ROOT / "docs" / "reference").glob("*.md"))
    expected_mirrored = [
        name
        for name in source_reference
        if name not in DOCS_REFERENCE_MIRROR_ALLOWLIST
        and name not in DOCS_REFERENCE_PRE_EXISTING_MIRROR
    ]

    still_mapped_allowlisted = sorted(set(mapped_reference) & DOCS_REFERENCE_MIRROR_ALLOWLIST)
    assert not still_mapped_allowlisted, (
        "docs/reference/*.md file(s) are listed in DOCS_REFERENCE_MIRROR_ALLOWLIST "
        f"but still have DOC_MAP entries: {still_mapped_allowlisted}. Remove the "
        "DOC_MAP entry when a reference doc is deliberately excluded from the "
        "docs-site mirror."
    )

    assert set(DOCS_REFERENCE_WITHHELD_PUBLICATION_PATHS) == set(DOCS_REFERENCE_MIRROR_ALLOWLIST)
    allowlisted_publication_artifacts = sorted(
        dest
        for dest in DOCS_REFERENCE_WITHHELD_PUBLICATION_PATHS.values()
        if (DOCS_SITE_ROOT / dest).exists()
    )
    assert not allowlisted_publication_artifacts, (
        "docs/reference/*.md file(s) are deliberately excluded from the docs-site "
        "mirror but still have publication artifacts: "
        f"{allowlisted_publication_artifacts}. Remove stale generated pages when "
        "a reference is withheld."
    )

    missing_doc_map_entries = sorted(set(expected_mirrored) - set(mapped_reference))
    assert not missing_doc_map_entries, (
        "docs/reference/*.md file(s) missing a DOC_MAP entry in "
        f"docs-site/scripts/sync-docs.js: {missing_doc_map_entries}. Add a "
        "'reference/<NAME>.md': 'reference/<slug>.md' DOC_MAP entry, list the "
        "filename in DOCS_REFERENCE_PRE_EXISTING_MIRROR above if it is already "
        "mirrored under a different destination, or add it to "
        "DOCS_REFERENCE_MIRROR_ALLOWLIST if it is deliberately excluded."
    )

    stale_doc_map_entries = sorted(set(mapped_reference) - set(source_reference))
    assert not stale_doc_map_entries, (
        "docs-site/scripts/sync-docs.js has reference/ DOC_MAP entries for "
        f"file(s) no longer present under docs/reference/: {stale_doc_map_entries}"
    )

    stale_pre_existing = sorted(set(DOCS_REFERENCE_PRE_EXISTING_MIRROR) - set(source_reference))
    assert not stale_pre_existing, (
        "DOCS_REFERENCE_PRE_EXISTING_MIRROR references file(s) no longer present "
        f"under docs/reference/: {stale_pre_existing}"
    )

    for source_name, dest in mapped_reference.items():
        page = DOCS_SITE_ROOT / "reference" / dest
        assert page.exists(), (
            f"Expected synced docs-site page missing for docs/reference/{source_name}: {page}"
        )

    for source_name, dest in DOCS_REFERENCE_PRE_EXISTING_MIRROR.items():
        page = DOCS_SITE_ROOT / dest
        assert page.exists(), (
            "DOCS_REFERENCE_PRE_EXISTING_MIRROR claims docs/reference/"
            f"{source_name} is mirrored at {dest}, but that page is missing: {page}"
        )

    assert (DOCS_SITE_ROOT / "reference" / "index.md").exists()


def test_public_commercial_sources_do_not_gain_duplicate_reference_pages() -> None:
    sync_script = SYNC_SCRIPT.read_text(encoding="utf-8")
    assert re.search(
        r"^\s*'PRICING\.md':\s*'enterprise/pricing\.md',\s*$",
        sync_script,
        re.MULTILINE,
    )
    assert re.search(
        r"^\s*'SLA\.md':\s*'enterprise/sla\.md',\s*$",
        sync_script,
        re.MULTILINE,
    )
    assert not re.search(r"^\s*'reference/PRICING_TIERS\.md':", sync_script, re.MULTILINE)
    assert not re.search(r"^\s*'reference/SLA\.md':", sync_script, re.MULTILINE)
    assert not re.search(r"^\s*'enterprise/SLA\.md':", sync_script, re.MULTILINE)

    enterprise_pricing = _read_docs_site("enterprise/pricing.md")
    assert "$49/seat/mo" in enterprise_pricing
    assert "10/month" in enterprise_pricing


def test_docs_reference_pages_have_no_dead_relative_md_links() -> None:
    # Mirroring docs/reference/** for the first time exposes every internal
    # and outbound link in these files to the same source-relative rewriting
    # as the rest of the docs-site. A raw, unrewritten "](something.md)" or
    # "](something.md#anchor)" surviving in any of these generated pages means
    # a link target has no DOC_MAP entry and no REPO_MARKDOWN_LINKS fallback,
    # so it would 404 on the deployed site.
    dead_link_pattern = re.compile(r"\]\([A-Za-z0-9_./-]+\.md[)#]")

    for dest in _docs_reference_map_entries().values():
        page = DOCS_SITE_ROOT / "reference" / dest
        content = page.read_text(encoding="utf-8")
        matches = dead_link_pattern.findall(content)
        assert not matches, f"Unrewritten relative .md link(s) in {page}: {matches}"


def test_reference_install_matrix_quickstart_uses_repo_fallback() -> None:
    content = _read_docs_site("reference/install-matrix.md")

    assert (
        "[public Python SDK quickstart]"
        "(https://github.com/synaptent/aragora/blob/main/docs/SDK_QUICKSTART_PYTHON.md)" in content
    )
    assert "](../SDK_QUICKSTART_PYTHON.md)" not in content


def test_docs_reference_index_lists_mirrored_children() -> None:
    content = _read_docs_site("reference/index.md")

    assert "## In This Section" in content
    for dest in _docs_reference_map_entries().values():
        slug = dest.removesuffix(".md")
        assert f"](./{slug})" in content


def test_reference_sidebar_is_registered() -> None:
    content = (REPO_ROOT / "docs-site" / "sidebars.js").read_text(encoding="utf-8")

    assert "referenceSidebar" in content
    assert "dirName: 'reference'" in content


def test_reference_sidebar_is_exposed_in_primary_navbar() -> None:
    sidebars = (REPO_ROOT / "docs-site" / "sidebars.js").read_text(encoding="utf-8")
    config = (REPO_ROOT / "docs-site" / "docusaurus.config.js").read_text(encoding="utf-8")

    registered_sidebars = set(re.findall(r"^\s{2}([A-Za-z]\w*):\s*\[", sidebars, re.MULTILINE))
    navbar_sidebars = set(re.findall(r"sidebarId:\s*'([^']+)'", config))

    assert "referenceSidebar" in registered_sidebars
    assert "referenceSidebar" in navbar_sidebars


def test_documentation_index_links_into_reference_use_mirrored_relative_paths() -> None:
    # PR #8967 added docs/reference/INSTALL_MATRIX.md but deliberately did not
    # link it from docs/INDEX.md: docs/reference/** had no DOC_MAP entries at
    # the time, so the link would have survived sync as a raw, unrewritten
    # ".md" path. Now that the boundary is closed, the link must be present
    # and resolve to the real mirrored page.
    content = _read_docs_site("contributing/documentation-index.md")

    assert "[Install Matrix](../reference/install-matrix)" in content
    assert "docs/reference/` is mirrored into `docs-site/`" in content
    assert "](reference/INSTALL_MATRIX.md)" not in content
    assert "](../reference/INSTALL_MATRIX.md)" not in content


def test_reference_index_self_link_resolves_to_its_own_mirrored_page() -> None:
    # docs/reference/INDEX.md has no basename match anywhere else in DOC_MAP,
    # so before reference/INDEX.md had its own entry, a "Reference Index" link
    # to it fell back to the *top-level* docs/INDEX.md's own mirrored
    # destination -- a silent self-loop back to the linking page itself, worse
    # than a raw dead link because it looks like a normal working link.
    index_page = _read_docs_site("contributing/documentation-index.md")
    reference_index_page = _read_docs_site("reference/reference-index.md")

    assert "[Reference Index](../reference/reference-index)" in index_page
    assert "[Reference Index](./documentation-index)" not in index_page

    assert "title: Aragora Documentation Index" in index_page
    assert "title: Documentation Index" in reference_index_page
    assert "title: Aragora Documentation Index" not in reference_index_page


def test_install_matrix_outbound_links_resolve_without_dead_links() -> None:
    # INSTALL_MATRIX.md links to two docs/specs/ siblings (mirrored) and to
    # docs/architecture/PACKAGING_AND_DISTRIBUTION.md, docs/PACKAGING.md,
    # DEVELOPMENT.md, and INSTALL.md, all of which sit outside the docs-site
    # mirror. Mirroring this file for the first time must not introduce new
    # dead raw-.md links for any of these.
    content = _read_docs_site("reference/install-matrix.md")

    assert "[Independent Verifier Guide](../specs/independent-verifier-guide)" in content
    assert (
        "[Independent Verifier Guide](../specs/independent-verifier-guide#exit-code-contract)"
        in content
    )
    assert (
        "[`docs/specs/INDEPENDENT_VERIFIER_GUIDE.md`](../specs/independent-verifier-guide)"
        in content
    )
    assert (
        "[`docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md`](../specs/receipt-lineage-reconciliation)"
    ) in content
    assert (
        "[`docs/architecture/PACKAGING_AND_DISTRIBUTION.md`]"
        "(https://github.com/synaptent/aragora/blob/main/"
        "docs/architecture/PACKAGING_AND_DISTRIBUTION.md)"
    ) in content
    assert (
        "[`docs/PACKAGING.md`](https://github.com/synaptent/aragora/blob/main/docs/PACKAGING.md)"
    ) in content
    assert (
        "[`DEVELOPMENT.md`](https://github.com/synaptent/aragora/blob/main/DEVELOPMENT.md)"
    ) in content
    assert ("[`INSTALL.md`](https://github.com/synaptent/aragora/blob/main/INSTALL.md)") in content

    assert "](../specs/INDEPENDENT_VERIFIER_GUIDE.md)" not in content
    assert "](../specs/INDEPENDENT_VERIFIER_GUIDE.md#exit-code-contract)" not in content
    assert "](../specs/RECEIPT_LINEAGE_RECONCILIATION.md)" not in content
    assert "](../architecture/PACKAGING_AND_DISTRIBUTION.md)" not in content
    assert "](../PACKAGING.md)" not in content
    assert "](../../DEVELOPMENT.md)" not in content
    assert "](../../INSTALL.md)" not in content
