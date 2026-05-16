from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness.control import Plan, PlanStep, RunStateRecord, StepContract
from harness.events import (
    ApprovalRequired, CommandCompleted, CommandProgress, CommandStarted, HarnessEvent, PlanReady,
)
from worker.models import PermissionEnvelope
from worker.policy import WorkerPolicyValidator


PLAN_ALLOWED_PACKAGES = ["pathlib", "csv", "json", "math", "statistics", "time", "pandas", "numpy"]


def normalize_plan_step_code(idx: int, raw: dict[str, Any]) -> str:
    code_value = raw.get("code")
    code_lines = raw.get("code_lines")
    if code_lines is not None:
        if not isinstance(code_lines, list) or not code_lines:
            raise ValueError(f"step #{idx}: 'code_lines' must be a non-empty list of strings")
        if not all(isinstance(line, str) for line in code_lines):
            raise ValueError(f"step #{idx}: 'code_lines' must contain only strings")
        joined = "\n".join(code_lines)
        if code_value not in (None, "") and str(code_value) != joined:
            raise ValueError(f"step #{idx}: conflicting 'code' and 'code_lines'")
        return joined
    return str(code_value or "")


class AnalysisService:
    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def build_plan_from_arguments(
        self,
        state: RunStateRecord,
        *,
        goal: str,
        steps: list[dict[str, Any]],
    ) -> tuple[Plan, list[StepContract]]:
        """Build a Plan + per-step StepContracts from validated tool_call arguments.

        The step `code` text originates from the LLM (Layer 1). This method only
        validates and packages — it does not execute. Worker dispatch happens
        later via `resume_approved_step` after explicit user approval.
        """
        if not isinstance(steps, list) or not steps:
            raise ValueError("analysis_plan requires non-empty 'steps' list")
        plan_id = f"plan_{state.run_id}_{uuid4().hex[:6]}"
        plan_steps: list[PlanStep] = []
        contracts: list[StepContract] = []
        for idx, raw in enumerate(steps, start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"step #{idx}: expected object, got {type(raw).__name__}")
            purpose = str(raw.get("purpose") or "").strip()
            code = normalize_plan_step_code(idx, raw)
            declared_inputs = [str(p) for p in (raw.get("declared_inputs") or [])]
            expected_outputs = [str(p) for p in (raw.get("expected_outputs") or ["result.txt"])]
            if not purpose:
                raise ValueError(f"step #{idx}: 'purpose' is required")
            if not code or len(code) > 16384:
                raise ValueError(f"step #{idx}: 'code' missing or exceeds 16KB")
            for path in declared_inputs:
                if path.startswith("/") or ".." in path.split("/"):
                    raise ValueError(f"step #{idx}: input '{path}' must be workspace-relative")
            permission_envelope = {
                "allowed_read_paths": list(declared_inputs),
                "registered_artifact_paths": [],
                "allowed_write_roots": ["artifacts/tmp"],
                "allowed_packages": list(PLAN_ALLOWED_PACKAGES),
                "allow_network": False,
                "allow_shell": False,
            }
            try:
                WorkerPolicyValidator(
                    Path("."),
                    PermissionEnvelope(**permission_envelope),
                ).validate_code_imports(code)
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"step #{idx}: {exc}") from exc

            for output in expected_outputs:
                output_name = Path(output).name
                if output_name and output_name not in code:
                    raise ValueError(
                        f"step #{idx}: code does not reference expected output {output!r}. "
                        f"Every step must write each of its expected_outputs "
                        f"(e.g. Path({output_name!r}).write_text(...))."
                    )

            step_id = f"step_{idx}"
            plan_steps.append(PlanStep(
                id=step_id,
                workspace_id=state.workspace_id,
                plan_id=plan_id,
                step_order=idx,
                purpose=purpose,
                kind="code",
                declared_inputs=declared_inputs,
                expected_outputs=expected_outputs,
            ))
            contracts.append(StepContract(
                id=f"contract_{state.run_id}_{step_id}",
                workspace_id=state.workspace_id,
                run_id=state.run_id,
                plan_id=plan_id,
                step_id=step_id,
                code=code,
                declared_inputs=declared_inputs,
                workspace_paths={"workspace": "."},
                permission_envelope=permission_envelope,
                expected_output_contract={"files": list(expected_outputs)},
                run_metadata={"source": "analysis_plan_tool_call", "goal": goal},
            ))
        plan = Plan(
            id=plan_id,
            workspace_id=state.workspace_id,
            run_id=state.run_id,
            goal=goal,
            steps=plan_steps,
            requires_code_execution=True,
        )
        return plan, contracts

    async def analysis_plan_events(
        self,
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        args: dict[str, Any],
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command=event_command, arguments={"goal": args.get("goal")},
        )
        try:
            state = RunStateRecord(
                workspace_id=workspace_id or "",
                active_agent_mode="analyst",
                run_id=run_id or f"run_{uuid4().hex[:12]}",
            )
            goal = str(args.get("goal") or "").strip()
            steps = args.get("steps") or []
            if not goal:
                raise ValueError("analysis_plan requires 'goal'")
            plan, contracts = self.build_plan_from_arguments(state, goal=goal, steps=steps)
        except Exception as exc:  # noqa: BLE001
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command=event_command,
                result={"error": str(exc)},
            )
            return

        async for ev in self.finalize_plan(
            state, plan, contracts,
            workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            event_command=event_command,
        ):
            yield ev

    async def finalize_plan(
        self,
        state: RunStateRecord,
        plan,
        contracts: list[StepContract],
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        """Shared tail: stash a built plan and emit PlanReady + single
        ApprovalRequired + CommandCompleted. Used by the command path
        (`analysis_plan_events`) and the model two-step path
        (`assemble_plan_events`)."""
        for contract in contracts:
            self.owner._pending_contracts[(state.run_id, contract.step_id)] = contract
        self.owner._pending_plans[plan.id] = plan
        self.owner._append_pending_plan(plan.id, {
            "action": "created",
            "plan_data": plan.model_dump(mode="json"),
            "goal": plan.goal,
            "step_count": len(plan.steps),
        })

        yield PlanReady(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            plan_id=plan.id, plan=plan.model_dump(mode="json"),
        )
        first_step = plan.steps[0]
        yield ApprovalRequired(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            plan_id=plan.id, step_id=first_step.id,
            step=first_step.model_dump(mode="json"),
            prompt="Approval required before running code.",
        )
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command=event_command,
            result={
                "plan_id": plan.id,
                "goal": plan.goal,
                "step_count": len(plan.steps),
                "awaiting_approval": first_step.id,
            },
        )

    async def assemble_plan_events(
        self,
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        args: dict[str, Any],
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        """Model two-step path: gen-1 emitted a code-free plan; synthesize
        each step's code via gen-2 (fenced), validate, inject, then build +
        finalize. One bounded gen-2 retry per step. Command path is unaffected
        (it supplies code directly via `analysis_plan_events`)."""
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command=event_command, arguments={"goal": args.get("goal")},
        )
        try:
            state = RunStateRecord(
                workspace_id=workspace_id or "",
                active_agent_mode="analyst",
                run_id=run_id or f"run_{uuid4().hex[:12]}",
            )
            goal = str(args.get("goal") or "").strip()
            steps = args.get("steps") or []
            if not goal:
                raise ValueError("analysis_plan requires 'goal'")
            if not isinstance(steps, list) or not steps:
                raise ValueError("analysis_plan requires a non-empty 'steps' list")
            workspace_dir = self.owner.workspace_manager.workspaces_dir / (workspace_id or "")
            total = len(steps)
            enriched: list[dict[str, Any]] = []
            for idx, raw in enumerate(steps, start=1):
                if not isinstance(raw, dict):
                    raise ValueError(f"step #{idx}: expected object, got {type(raw).__name__}")
                purpose = str(raw.get("purpose") or "").strip()
                if not purpose:
                    raise ValueError(f"step #{idx}: 'purpose' is required")
                yield CommandProgress(
                    ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id,
                    run_id=run_id, command=event_command, phase="generating_code",
                    phase_index=idx, phase_total=total, message=purpose,
                )
                code_lines = await self.owner._generate_step_code(
                    state, step=raw, workspace_dir=workspace_dir,
                )
                candidate = {**raw, "code_lines": code_lines}
                err = self.validate_generated_step(state, goal, candidate)
                if err:
                    code_lines = await self.owner._generate_step_code(
                        state, step=raw, workspace_dir=workspace_dir, correction=err,
                    )
                    candidate = {**raw, "code_lines": code_lines}
                    err = self.validate_generated_step(state, goal, candidate)
                    if err:
                        raise ValueError(
                            f"step #{idx}: code generation failed after one retry: {err}"
                        )
                enriched.append(candidate)
            plan, contracts = self.build_plan_from_arguments(
                state, goal=goal, steps=enriched,
            )
        except Exception as exc:  # noqa: BLE001
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command=event_command,
                result={"error": str(exc)},
            )
            return

        async for ev in self.finalize_plan(
            state, plan, contracts,
            workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            event_command=event_command,
        ):
            yield ev

    def validate_generated_step(
        self, state: RunStateRecord, goal: str, step: dict[str, Any],
    ) -> str | None:
        """Run the existing per-step plan validation against one gen-2 step.
        Returns the error string if invalid, else None."""
        try:
            self.build_plan_from_arguments(state, goal=goal, steps=[step])
            return None
        except ValueError as exc:
            return str(exc)

    async def analysis_request_execution_events(
        self,
        *,
        workspace_id: str | None,
        chat_id: str | None,
        run_id: str | None,
        args: dict[str, Any],
        event_command: str,
    ) -> AsyncIterator[HarnessEvent]:
        plan_id = str(args.get("plan_id") or "")
        step_id = str(args.get("step_id") or "")
        yield CommandStarted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command=event_command, arguments={"plan_id": plan_id, "step_id": step_id},
        )
        contract = self.owner._pending_contracts.get((run_id or "", step_id))
        if contract is None:
            yield CommandCompleted(
                ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
                command=event_command,
                result={"error": f"no pending contract for {plan_id}/{step_id}"},
            )
            return
        yield ApprovalRequired(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            plan_id=plan_id, step_id=step_id,
            step={"id": step_id},
            prompt="Approval required before running code.",
        )
        yield CommandCompleted(
            ts=datetime.now(UTC), workspace_id=workspace_id, chat_id=chat_id, run_id=run_id,
            command=event_command,
            result={"plan_id": plan_id, "step_id": step_id, "awaiting_approval": True},
        )
