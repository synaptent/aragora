"""
Workflow Engine CLI commands.

Provides CLI access to the workflow engine for running and managing workflows.
Commands:
- gt workflow list - List workflows
- gt workflow run <workflow_id> - Execute a workflow
- gt workflow status <execution_id> - Get execution status
- gt workflow templates - List available templates
- gt workflow patterns - List workflow patterns
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
from datetime import datetime
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


async def _resolve(value: Any) -> Any:
    """Await a value if it's a coroutine, otherwise return it directly."""
    if inspect.isawaitable(value):
        return await value
    return value


def cmd_workflow(args: argparse.Namespace) -> None:
    """Handle 'workflow' command - dispatch to subcommands."""
    subcommand = getattr(args, "workflow_command", None)

    if subcommand == "list":
        asyncio.run(_cmd_list(args))
    elif subcommand == "run":
        asyncio.run(_cmd_run(args))
    elif subcommand == "status":
        asyncio.run(_cmd_status(args))
    elif subcommand == "templates":
        asyncio.run(_cmd_templates(args))
    elif subcommand == "patterns":
        asyncio.run(_cmd_patterns(args))
    elif subcommand == "categories":
        asyncio.run(_cmd_categories(args))
    else:
        # Default: show help
        print("\nUsage: aragora workflow <command>")
        print("\nCommands:")
        print("  list                       List saved workflows")
        print("  run <workflow_id>          Execute a workflow")
        print("  status <execution_id>      Get execution status")
        print("  templates [--category]     List available templates")
        print("  patterns                   List workflow patterns")
        print("  categories                 List template categories")
        print("\nOptions for 'run':")
        print("  --inputs <json>            JSON inputs for the workflow")
        print("  --async                    Run in background (don't wait)")
        print("  --json                     Output as JSON")


async def _cmd_list(args: argparse.Namespace) -> None:
    """List workflows."""
    category = getattr(args, "category", None)
    limit = getattr(args, "limit", 20)
    as_json = getattr(args, "json", False)

    try:
        from aragora.workflow.persistent_store import get_workflow_store

        store = get_workflow_store()
        workflows = await _resolve(store.list_workflows(category=category, limit=limit))

        if as_json:
            workflow_dicts = [w.to_dict() for w in workflows]
            print(json.dumps(workflow_dicts, indent=2, default=str))
            return

        print("\n" + "=" * 60)
        print("WORKFLOWS")
        print("=" * 60)

        if not workflows:
            print("\n  No workflows found.")
            print("  Create one with: aragora workflow create --file workflow.yaml")
            return

        print(f"\n  Found {len(workflows)} workflow(s):\n")

        for wf in workflows:
            print(f"  [{wf.id}] {wf.name}")
            print(f"    Version: {wf.version}")
            print(
                f"    Category: {wf.category.value if hasattr(wf.category, 'value') else wf.category}"
            )
            if wf.description:
                desc = wf.description[:60] + "..." if len(wf.description) > 60 else wf.description
                print(f"    {desc}")
            if wf.tags:
                print(f"    Tags: {', '.join(wf.tags[:5])}")
            print()

    except (OSError, RuntimeError, ValueError) as e:
        print(f"\nError listing workflows: {e}")


async def _cmd_run(args: argparse.Namespace) -> None:
    """Execute a workflow."""
    workflow_id = getattr(args, "workflow_id", None)
    inputs_json = getattr(args, "inputs", None)
    _run_async = getattr(args, "run_async", False)
    as_json = getattr(args, "json", False)

    if not workflow_id:
        print("\nError: workflow_id is required")
        print("Usage: aragora workflow run <workflow_id>")
        return

    # Parse inputs
    inputs: dict[str, Any] = {}
    if inputs_json:
        try:
            inputs = json.loads(inputs_json)
        except json.JSONDecodeError as e:
            print(f"\nError: Invalid JSON inputs: {e}")
            return

    try:
        from aragora.workflow.persistent_store import get_workflow_store
        from aragora.workflow.engine import get_workflow_engine

        store = get_workflow_store()
        engine = get_workflow_engine()

        # Get workflow definition
        workflow = await _resolve(store.get_workflow(workflow_id))
        if not workflow:
            # Try as template
            workflow = await _resolve(store.get_template(workflow_id))
            if not workflow:
                print(f"\nError: Workflow or template '{workflow_id}' not found.")
                return

        if not as_json:
            print(f"\nExecuting workflow: {workflow.name}")
            print(f"  ID: {workflow.id}")
            print(f"  Steps: {len(workflow.steps)}")
            if inputs:
                print(f"  Inputs: {json.dumps(inputs)[:50]}...")
            print()

        # Execute
        start_time = datetime.now()
        result = await engine.execute(workflow, inputs=inputs)
        duration = (datetime.now() - start_time).total_seconds()

        if as_json:
            output = {
                "workflow_id": workflow.id,
                "execution_id": result.workflow_id,
                "success": result.success,
                "duration_seconds": duration,
                "steps_completed": len([s for s in result.steps if s.status.value == "completed"]),
                "steps_total": len(result.steps),
                "final_output": result.final_output,
                "error": result.error,
            }
            print(json.dumps(output, indent=2, default=str))
            return

        status = "SUCCESS" if result.success else "FAILED"
        print("=" * 60)
        print(f"WORKFLOW {status}")
        print("=" * 60)
        print(f"\n  Duration: {duration:.1f}s")
        print(
            f"  Steps: {len([s for s in result.steps if s.status.value == 'completed'])}/{len(result.steps)} completed"
        )

        if result.error:
            print(f"\n  Error: {result.error}")

        if result.final_output:
            print("\n  Output:")
            output_str = json.dumps(result.final_output, indent=4, default=str)
            for line in output_str.split("\n")[:10]:
                print(f"    {line}")

        # Show step summary
        print("\n  Step Results:")
        for step in result.steps:
            icon = "+" if step.status.value == "completed" else "-"
            print(f"    [{icon}] {step.step_name}: {step.status.value} ({step.duration_ms:.0f}ms)")

    except (OSError, RuntimeError, ValueError) as e:
        logger.exception("Workflow execution failed")
        print(f"\nError: {e}")


async def _cmd_status(args: argparse.Namespace) -> None:
    """Get workflow execution status."""
    execution_id = getattr(args, "execution_id", None)
    as_json = getattr(args, "json", False)

    if not execution_id:
        print("\nError: execution_id is required")
        print("Usage: aragora workflow status <execution_id>")
        return

    try:
        from aragora.workflow.persistent_store import get_workflow_store

        store = get_workflow_store()
        execution = await _resolve(store.get_execution(execution_id))

        if not execution:
            print(f"\nError: Execution '{execution_id}' not found.")
            return

        if as_json:
            print(json.dumps(execution, indent=2, default=str))
            return

        print("\n" + "=" * 60)
        print("WORKFLOW EXECUTION")
        print("=" * 60)

        print(f"\n  Execution ID: {execution.get('execution_id', execution_id)}")
        print(f"  Workflow ID:  {execution.get('workflow_id', 'N/A')}")
        print(f"  Status:       {execution.get('status', 'unknown')}")

        started = execution.get("started_at")
        if started:
            if isinstance(started, str):
                print(f"  Started:      {started}")
            else:
                print(
                    f"  Started:      {datetime.fromtimestamp(started).strftime('%Y-%m-%d %H:%M:%S')}"
                )

        completed = execution.get("completed_at")
        if completed:
            if isinstance(completed, str):
                print(f"  Completed:    {completed}")
            else:
                print(
                    f"  Completed:    {datetime.fromtimestamp(completed).strftime('%Y-%m-%d %H:%M:%S')}"
                )

        # Show steps if available
        steps = execution.get("steps", [])
        if steps:
            print(f"\n  Steps ({len(steps)}):")
            for step in steps[:10]:
                if isinstance(step, dict):
                    name = step.get("step_name", step.get("name", "unknown"))
                    status = step.get("status", "unknown")
                    print(f"    - {name}: {status}")

        # Show error if any
        error = execution.get("error")
        if error:
            print(f"\n  Error: {error}")

    except (OSError, RuntimeError, ValueError) as e:
        print(f"\nError getting status: {e}")


async def _cmd_templates(args: argparse.Namespace) -> None:
    """List available workflow templates."""
    category = getattr(args, "category", None)
    limit = getattr(args, "limit", 50)
    as_json = getattr(args, "json", False)

    try:
        from aragora.workflow.persistent_store import get_workflow_store

        store = get_workflow_store()
        templates = await _resolve(store.list_templates(category=category, limit=limit))

        if as_json:
            template_dicts = [t.to_dict() for t in templates]
            print(json.dumps(template_dicts, indent=2, default=str))
            return

        print("\n" + "=" * 60)
        print("WORKFLOW TEMPLATES")
        print("=" * 60)

        if not templates:
            print("\n  No templates found.")
            return

        # Group by category
        by_category: dict[str, list] = {}
        for t in templates:
            cat = t.category.value if hasattr(t.category, "value") else str(t.category)
            by_category.setdefault(cat, []).append(t)

        for cat, cat_templates in sorted(by_category.items()):
            print(f"\n  {cat.upper()}:")
            for t in cat_templates[:10]:
                print(f"    [{t.id}] {t.name}")
                if t.description:
                    desc = t.description[:50] + "..." if len(t.description) > 50 else t.description
                    print(f"      {desc}")

        print(f"\n  Total: {len(templates)} templates")
        print("  Run with: aragora workflow run <template_id>")

    except (OSError, RuntimeError, ValueError) as e:
        print(f"\nError listing templates: {e}")


async def _cmd_patterns(args: argparse.Namespace) -> None:
    """List workflow patterns."""
    as_json = getattr(args, "json", False)

    try:
        from aragora.workflow.templates.pattern_factory import list_pattern_templates

        patterns = list_pattern_templates()

        if as_json:
            print(json.dumps(patterns, indent=2, default=str))
            return

        print("\n" + "=" * 60)
        print("WORKFLOW PATTERNS")
        print("=" * 60)

        if not patterns:
            print("\n  No patterns available.")
            return

        print(f"\n  Available patterns ({len(patterns)}):\n")

        for p in patterns:
            print(f"  [{p.get('id', 'unknown')}] {p.get('name', 'Unnamed')}")
            if p.get("description"):
                print(f"    {p['description'][:60]}...")
            if p.get("agents_required"):
                print(f"    Agents: {p['agents_required']}")
            print()

        print("  Instantiate with: aragora workflow run --pattern <pattern_id>")

    except ImportError:
        print("\n  Pattern factory not available.")
    except (OSError, RuntimeError, ValueError) as e:
        print(f"\nError listing patterns: {e}")


async def _cmd_categories(args: argparse.Namespace) -> None:
    """List template categories."""
    as_json = getattr(args, "json", False)

    try:
        from aragora.workflow.types import WorkflowCategory

        categories = [c.value for c in WorkflowCategory]

        if as_json:
            print(json.dumps({"categories": categories}, indent=2))
            return

        print("\n" + "=" * 60)
        print("WORKFLOW CATEGORIES")
        print("=" * 60)

        print(f"\n  Available categories ({len(categories)}):\n")
        for cat in sorted(categories):
            print(f"    - {cat}")

        print("\n  Filter templates: aragora workflow templates --category <category>")

    except (OSError, RuntimeError, ValueError) as e:
        print(f"\nError listing categories: {e}")


def add_workflow_parser(subparsers: Any) -> None:
    """Add workflow subparser to CLI."""
    wp = subparsers.add_parser(
        "workflow",
        help="Workflow engine commands",
        description="Run and manage automated workflows",
    )
    wp.set_defaults(func=cmd_workflow)

    wp_sub = wp.add_subparsers(dest="workflow_command")

    # List
    list_p = wp_sub.add_parser("list", help="List workflows")
    list_p.add_argument("--category", help="Filter by category")
    list_p.add_argument("--limit", type=int, default=20, help="Limit results")
    list_p.add_argument("--json", action="store_true", help="Output as JSON")

    # Run
    run_p = wp_sub.add_parser("run", help="Execute a workflow")
    run_p.add_argument("workflow_id", help="Workflow or template ID to execute")
    run_p.add_argument("--inputs", help="JSON inputs for the workflow")
    run_p.add_argument("--async", dest="run_async", action="store_true", help="Run in background")
    run_p.add_argument("--json", action="store_true", help="Output as JSON")

    # Status
    status_p = wp_sub.add_parser("status", help="Get execution status")
    status_p.add_argument("execution_id", help="Execution ID to check")
    status_p.add_argument("--json", action="store_true", help="Output as JSON")

    # Templates
    templates_p = wp_sub.add_parser("templates", help="List workflow templates")
    templates_p.add_argument("--category", help="Filter by category")
    templates_p.add_argument("--limit", type=int, default=50, help="Limit results")
    templates_p.add_argument("--json", action="store_true", help="Output as JSON")

    # Patterns
    patterns_p = wp_sub.add_parser("patterns", help="List workflow patterns")
    patterns_p.add_argument("--json", action="store_true", help="Output as JSON")

    # Categories
    categories_p = wp_sub.add_parser("categories", help="List template categories")
    categories_p.add_argument("--json", action="store_true", help="Output as JSON")
