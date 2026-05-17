from __future__ import annotations

from typing import TYPE_CHECKING

from harness.core.command_registry import ArgSpec, HarnessCommandDescriptor, HarnessCommandRegistry

if TYPE_CHECKING:
    from harness.orchestrator import Orchestrator


def register_run_commands(orchestrator: "Orchestrator", registry: HarnessCommandRegistry) -> None:
    registry.register(
        HarnessCommandDescriptor(
            name="plan_analysis", slash_alias="/plan_analysis",
            short_description="Build a Python analysis plan and request user approval",
            arguments=[
                ArgSpec(name="goal", type="str", required=True,
                        description="one-line user goal", example="count customers"),
                ArgSpec(name="steps", type="json", required=True,
                        description="list of {purpose,code,declared_inputs,expected_outputs}",
                        example="[{\"purpose\":\"...\",\"code\":\"...\"}]"),
            ],
            available=True, affected_resource="plan",
            expected_event_types=["CommandStarted", "PlanReady", "ApprovalRequired", "CommandCompleted"],
            example_usage='/plan_analysis "count customers" [{...}]',
        ),
        orchestrator._handle_plan_analysis,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="request_execution", slash_alias="/request_execution",
            short_description="Re-emit ApprovalRequired for an existing pending step",
            arguments=[
                ArgSpec(name="plan_id", type="str", required=True, description="plan id", example="plan_..."),
                ArgSpec(name="step_id", type="step_id", required=True, description="step id", example="step_1"),
            ],
            available=True, affected_resource="step",
            expected_event_types=["CommandStarted", "ApprovalRequired", "CommandCompleted"],
            example_usage="/request_execution plan_x step_1",
        ),
        orchestrator._handle_request_execution,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="cancel_run", slash_alias="/cancel_run",
            short_description="Cancel the active run",
            arguments=[ArgSpec(
                name="reason", type="str", required=False,
                description="cancellation reason", example="user_request",
            )],
            available=True, affected_resource="run",
            expected_event_types=["CommandStarted", "TurnCancelled", "CommandCompleted"],
            example_usage='/cancel_run "stuck"',
        ),
        orchestrator._handle_cancel_run,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="mark_result_trusted", slash_alias="/mark_result_trusted",
            short_description="Mark a step result as user-trusted (revalidated)",
            arguments=[
                ArgSpec(name="step_id", type="step_id", required=True,
                        description="step whose result is trusted",
                        example="step_42"),
                ArgSpec(name="reason", type="str", required=False,
                        description="why trust was granted",
                        example="spot-checked output"),
            ],
            available=True, affected_resource="step",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/mark_result_trusted step_42 \"spot-checked output\"",
        ),
        orchestrator._handle_mark_result_trusted,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="mark_result_invalidated", slash_alias="/mark_result_invalidated",
            short_description="Mark a step result as needing review",
            arguments=[
                ArgSpec(name="step_id", type="step_id", required=True,
                        description="step whose result is invalidated",
                        example="step_42"),
                ArgSpec(name="reason", type="str", required=False,
                        description="why the result is invalidated",
                        example="input data changed upstream"),
            ],
            available=True, affected_resource="step",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/mark_result_invalidated step_42 \"input changed\"",
        ),
        orchestrator._handle_mark_result_invalidated,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="challenge_conclusion", slash_alias="/challenge_conclusion",
            short_description="Open a review proposal challenging a prior conclusion",
            arguments=[
                ArgSpec(name="target", type="str", required=True,
                        description="run_id, artifact path, or conclusion id under challenge",
                        example="run_42"),
                ArgSpec(name="reason", type="str", required=True,
                        description="why the conclusion is being challenged",
                        example="sample size too small"),
            ],
            available=True, affected_resource="run",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/challenge_conclusion run_42 \"sample size too small\"",
        ),
        orchestrator._handle_challenge_conclusion,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="stop_after_current_step", slash_alias="/stop_after_current_step",
            short_description="Request graceful run stop after current step finishes",
            arguments=[
                ArgSpec(name="run_id", type="run_id", required=False,
                        description="run to stop (defaults to active run)",
                        example="run_abc"),
                ArgSpec(name="reason", type="str", required=False,
                        description="why a graceful stop was requested",
                        example="user requested graceful stop"),
            ],
            available=True, affected_resource="run",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/stop_after_current_step",
        ),
        orchestrator._handle_stop_after_current_step,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="revise_goal", slash_alias="/revise_goal",
            short_description="Revise the goal text on a plan record",
            arguments=[
                ArgSpec(name="plan_id", type="str", required=True,
                        description="plan whose goal is being revised",
                        example="plan_1"),
                ArgSpec(name="new_goal", type="str", required=True,
                        description="replacement goal text",
                        example="refined goal text"),
            ],
            available=True, affected_resource="plan",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/revise_goal plan_1 \"refined goal text\"",
        ),
        orchestrator._handle_revise_goal,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="retry_step", slash_alias="/retry_step",
            short_description="Request retry of a failed step within retry budget",
            arguments=[
                ArgSpec(name="step_id", type="step_id", required=True,
                        description="step to retry", example="step_5"),
                ArgSpec(name="reason", type="str", required=False,
                        description="why retry was requested",
                        example="transient timeout"),
            ],
            available=True, affected_resource="step",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/retry_step step_5 \"transient timeout\"",
        ),
        orchestrator._handle_retry_step,
    )
    registry.register(
        HarnessCommandDescriptor(
            name="rerun_step", slash_alias="/rerun_step",
            short_description="Force re-execution of a step ignoring fingerprint cache",
            arguments=[
                ArgSpec(name="step_id", type="step_id", required=True,
                        description="step to rerun", example="step_7"),
                ArgSpec(name="reason", type="str", required=False,
                        description="why rerun was requested",
                        example="force fresh fingerprint"),
            ],
            available=True, affected_resource="step",
            expected_event_types=["CommandStarted", "CommandCompleted"],
            example_usage="/rerun_step step_7 \"force fresh fingerprint\"",
        ),
        orchestrator._handle_rerun_step,
    )
