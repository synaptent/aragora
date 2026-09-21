"""
MCP Pipeline Tools.

Provides tools for the idea-to-execution pipeline:
- run_pipeline: Run the full pipeline from ideas or text
- extract_goals: Extract goals from raw ideas
- get_pipeline_status: Get pipeline execution status
- advance_pipeline_stage: Advance pipeline to next stage
"""

from __future__ import annotations

import json as json_module
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_pipeline_tool(
    input_text: str = "",
    ideas: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the idea-to-execution pipeline from raw ideas or text.

    Args:
        input_text: Free-form text to run through the full async pipeline
        ideas: JSON array of idea strings for the sync from_ideas() path
        dry_run: If True, skip orchestration stage

    Returns:
        Dict with pipeline_id, stage_status, and summary
    """
    try:
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
        )

        pipeline = IdeaToExecutionPipeline()

        # Prefer ideas list (sync path) if provided
        if ideas:
            try:
                ideas_list = json_module.loads(ideas) if isinstance(ideas, str) else ideas
                if not isinstance(ideas_list, list):
                    return {"error": "ideas must be a JSON array of strings"}
            except json_module.JSONDecodeError:
                return {"error": "Invalid JSON in ideas parameter"}

            if not ideas_list:
                return {"error": "ideas list is empty"}

            result = pipeline.from_ideas(ideas_list, auto_advance=True)
            # Persist to KnowledgeMound
            try:
                from aragora.pipeline.km_bridge import PipelineKMBridge

                PipelineKMBridge().store_pipeline_result(result)
            except (ImportError, AttributeError, RuntimeError, ValueError) as exc:
                logger.debug("KM persistence skipped: %s", exc)
            result_dict = result.to_dict()
            return {
                "pipeline_id": result.pipeline_id,
                "stage_status": result.stage_status,
                "goals_count": len(result.goal_graph.goals) if result.goal_graph else 0,
                "summary": result_dict,
            }

        # Fall back to input_text (async path)
        if not input_text:
            return {"error": "Either input_text or ideas must be provided"}

        config = PipelineConfig(dry_run=dry_run)
        result = await pipeline.run(input_text, config)
        result_dict = result.to_dict()

        # Persist result
        try:
            from aragora.storage.pipeline_store import get_pipeline_store

            get_pipeline_store().save(result.pipeline_id, result_dict)
        except (ImportError, OSError):
            pass

        # Persist to KnowledgeMound
        try:
            from aragora.pipeline.km_bridge import PipelineKMBridge

            PipelineKMBridge().store_pipeline_result(result)
        except (ImportError, AttributeError, RuntimeError, ValueError) as exc:
            logger.debug("KM persistence skipped: %s", exc)

        return {
            "pipeline_id": result.pipeline_id,
            "stage_status": result.stage_status,
            "duration": result.duration,
            "summary": result_dict,
        }

    except ImportError:
        logger.warning("Pipeline module not available")
        return {"error": "Pipeline module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        logger.warning("Pipeline execution failed: %s", e)
        return {"error": "Pipeline execution failed"}


async def extract_goals_tool(
    ideas_json: str = "",
    confidence_threshold: float = 0.6,
) -> dict[str, Any]:
    """Extract goals from raw ideas.

    Args:
        ideas_json: JSON array of idea strings
        confidence_threshold: Minimum confidence for goals (0.0-1.0)

    Returns:
        Dict with extracted goal graph
    """
    try:
        from aragora.goals.extractor import GoalExtractor

        if not ideas_json:
            return {"error": "ideas_json is required"}

        try:
            ideas_list = (
                json_module.loads(ideas_json) if isinstance(ideas_json, str) else ideas_json
            )
            if not isinstance(ideas_list, list):
                return {"error": "ideas_json must be a JSON array of strings"}
        except json_module.JSONDecodeError:
            return {"error": "Invalid JSON in ideas_json parameter"}

        extractor = GoalExtractor()
        goal_graph = extractor.extract_from_raw_ideas(ideas_list)

        # Filter by confidence
        if confidence_threshold > 0:
            goal_graph.goals = [g for g in goal_graph.goals if g.confidence >= confidence_threshold]

        return {
            "goal_graph": goal_graph.to_dict(),
            "goals_count": len(goal_graph.goals),
            "confidence_threshold": confidence_threshold,
        }

    except ImportError:
        logger.warning("Goal extractor module not available")
        return {"error": "Goal extractor module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        logger.warning("Goal extraction failed: %s", e)
        return {"error": "Goal extraction failed"}


async def get_pipeline_status_tool(
    pipeline_id: str = "",
) -> dict[str, Any]:
    """Get pipeline execution status.

    Args:
        pipeline_id: The pipeline ID to look up

    Returns:
        Dict with pipeline status and stage details
    """
    if not pipeline_id:
        return {"error": "pipeline_id is required"}

    try:
        from aragora.storage.pipeline_store import get_pipeline_store

        store = get_pipeline_store()
        result = store.get(pipeline_id)

        if not result:
            return {"error": f"Pipeline {pipeline_id} not found"}

        return {
            "pipeline_id": pipeline_id,
            "stage_status": result.get("stage_status", {}),
            "stage_results": result.get("stage_results"),
            "duration": result.get("duration"),
            "has_receipt": bool(result.get("receipt")),
        }

    except ImportError:
        logger.warning("Pipeline store not available")
        return {"error": "Pipeline store module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        logger.warning("Pipeline status check failed: %s", e)
        return {"error": "Pipeline status check failed"}


async def advance_pipeline_stage_tool(
    pipeline_id: str = "",
    target_stage: str = "",
) -> dict[str, Any]:
    """Advance pipeline to next stage.

    Args:
        pipeline_id: The pipeline ID to advance
        target_stage: Target stage (goals, actions, orchestration)

    Returns:
        Dict with updated pipeline status
    """
    if not pipeline_id:
        return {"error": "pipeline_id is required"}
    if not target_stage:
        return {"error": "target_stage is required"}

    try:
        from aragora.canvas.stages import PipelineStage
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline
        from aragora.server.handlers.canvas.canvas_pipeline import _pipeline_objects

        result_obj = _pipeline_objects.get(pipeline_id)
        if not result_obj:
            return {"error": f"Pipeline {pipeline_id} not found (must be a live pipeline)"}

        try:
            stage = PipelineStage(target_stage)
        except ValueError:
            valid = [s.value for s in PipelineStage]
            return {"error": f"Invalid stage: {target_stage}. Valid: {valid}"}

        pipeline = IdeaToExecutionPipeline()
        result_obj = pipeline.advance_stage(result_obj, stage)
        _pipeline_objects[pipeline_id] = result_obj

        # Persist updated result
        try:
            from aragora.storage.pipeline_store import get_pipeline_store

            get_pipeline_store().save(pipeline_id, result_obj.to_dict())
        except (ImportError, OSError):
            pass

        return {
            "pipeline_id": pipeline_id,
            "advanced_to": target_stage,
            "stage_status": result_obj.stage_status,
        }

    except ImportError:
        logger.warning("Pipeline module not available")
        return {"error": "Pipeline module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        logger.warning("Pipeline advance failed: %s", e)
        return {"error": "Pipeline advance failed"}


__all__ = [
    "run_pipeline_tool",
    "extract_goals_tool",
    "get_pipeline_status_tool",
    "advance_pipeline_stage_tool",
]
