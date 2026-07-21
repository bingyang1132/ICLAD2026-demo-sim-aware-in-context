"""
Executor: translates goals into a concrete parameter diff; retries when the
oracle reports excessive legalization / routing risk.

NOTE: output_schema is intentionally None. Gemini's constrained JSON decoding
with {"type": "object"} produces {} (minimal valid JSON) regardless of prompt
instructions. json_mode=True uses response_mime_type without response_schema,
letting the model follow prompt examples instead of schema constraints.
"""
from __future__ import annotations
import copy
import logging
from typing import Any
from icpi.agents.base import BaseAgent
from icpi.state import LayoutState
from icpi.journal import DesignJournal
from icpi.action_space import apply_diff, validate
from icpi.config import LEGALIZATION_RETRY_THRESHOLD

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    prompt_file = "executor.md"
    output_schema = None   # see module docstring
    agent_name = "executor"

    def _call(self, user_prompt: str) -> Any:
        from llm_api.router import chat
        from icpi.usage import TRACKER
        with TRACKER.agent_context(self.agent_name):
            return chat(
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                output_schema=None,
                json_mode=True,
                model=self.model,
            )

    def run(
        self,
        state: LayoutState,
        journal: DesignJournal,
        netlist: dict,
        family: str,
        goals: list[str],
        oracle,
    ) -> tuple[dict, dict, dict, bool]:
        """
        Returns (new_params, oracle_result, diff_applied, legalization_failed).

        legalization_failed is True if the final params produced
        legalization_risk > threshold; the caller may treat this as failure.
        """
        device_names = [d["name"] for d in netlist.get("devices", [])]
        net_names = [n["name"] for n in netlist.get("nets", [])]

        base_prompt = (
            f"CURRENT LAYOUT STATE:\n{state.compact_summary()}\n\n"
            f"CHOSEN FAMILY: {family}\n"
            f"SUPERVISOR GOALS:\n" + "\n".join(f"- {g}" for g in goals) + "\n\n"
            f"JOURNAL (family={family}):\n{journal.to_context_str(family=family, top_k=4)}\n\n"
            f"NETLIST DEVICES: {device_names}\n"
            f"NETLIST NETS:    {net_names}\n\n"
            "Produce a diff for the chosen parameter family."
        )

        # ── First attempt ─────────────────────────────────────────────────────
        result = self._call(base_prompt)
        logger.debug("Executor attempt-1 result: %s", result)
        diff = result.get("diff", {})

        # Guard: empty diff → one explicit retry
        if self._is_empty_diff(family, diff):
            logger.warning("Executor returned empty diff; retrying with explicit nudge")
            result = self._call(
                base_prompt
                + "\n\nCRITICAL: Your previous response returned an empty diff {}."
                  " You MUST provide at least one concrete change."
                  " For symmetry: declare at least one pair or matched_net."
                  " For other families: set at least one net/device key to a non-default value."
            )
            logger.debug("Executor retry result: %s", result)
            diff = result.get("diff", {})

        new_params, violations = self._safe_apply(state.params, family, diff)
        if violations:
            logger.warning("Round produced %d bound violations; retrying", len(violations))
            retry_prompt = (
                base_prompt
                + "\n\nPREVIOUS DIFF HAD BOUND VIOLATIONS:\n"
                + "\n".join(violations)
                + "\nPlease produce a safer diff that stays within bounds."
            )
            result = self._call(retry_prompt)
            diff = result.get("diff", {})
            new_params, violations = self._safe_apply(state.params, family, diff)
            if violations:
                logger.warning("Retry still invalid — rolling back to previous params")
                return copy.deepcopy(state.params), {}, {}, True

        oracle_result = oracle.evaluate(new_params)
        leg_risk = oracle_result["pex"]["legalization_risk"]

        if leg_risk > LEGALIZATION_RETRY_THRESHOLD:
            logger.warning("legalization_risk=%.2f > %.2f → retry conservative",
                           leg_risk, LEGALIZATION_RETRY_THRESHOLD)
            retry_prompt = (
                base_prompt +
                f"\n\nPREVIOUS DIFF caused high legalization_risk={leg_risk:.2f}.\n"
                "Diagnosis: " + "; ".join(oracle_result.get("diagnosis", [])) +
                "\nPlease propose a much more conservative diff "
                "(smaller magnitudes, fewer keys)."
            )
            result = self._call(retry_prompt)
            diff_retry = result.get("diff", {})
            new_params_retry, violations_retry = self._safe_apply(
                state.params, family, diff_retry
            )
            if violations_retry:
                logger.warning("Retry violated bounds; keeping high-risk result")
            else:
                oracle_retry = oracle.evaluate(new_params_retry)
                if oracle_retry["pex"]["legalization_risk"] < leg_risk:
                    new_params = new_params_retry
                    oracle_result = oracle_retry
                    diff = diff_retry
                    leg_risk = oracle_retry["pex"]["legalization_risk"]

        leg_failed = leg_risk > LEGALIZATION_RETRY_THRESHOLD
        return new_params, oracle_result, diff, leg_failed

    @staticmethod
    def _is_empty_diff(family: str, diff) -> bool:
        if not diff:
            return True
        if family == "symmetry":
            return (
                not diff.get("pairs")
                and not diff.get("self_symmetric")
                and not diff.get("matched_nets")
            )
        return False

    @staticmethod
    def _safe_apply(params: dict, family: str, diff) -> tuple[dict, list[str]]:
        try:
            new_params = apply_diff(params, family, diff)
        except (ValueError, TypeError) as e:
            return copy.deepcopy(params), [f"apply_diff error: {e}"]
        return new_params, validate(new_params)
