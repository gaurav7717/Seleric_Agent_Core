"""Action broker: propose -> RBAC -> schema validation -> business rules ->
dry-run preview -> confirmation token; commit -> token verify (single-use,
TTL) -> idempotency -> kill switch -> dispatch -> audit.

Safety is enforced here at the protocol layer, independent of whatever
consent UX the MCP host provides.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import structlog

from ..catalogue_service.loader import ActionContractDef
from ..catalogue_service.service import CatalogueService
from ..config import Settings
from ..observability.audit import AuditLog, new_audit_ref
from ..semantic_layer.cube_client import CubeClient
from .contracts import PAYLOAD_SCHEMAS, ActionPreview, CommitResult, RuleResult
from .executors.base import ActionExecutor
from .stores import ActionStore, IdempotencyStore
from .tokens import mint_token, payload_hash, verify_token

logger = structlog.get_logger()


class ActionBroker:
    def __init__(
        self,
        settings: Settings,
        catalogue: CatalogueService,
        cube: CubeClient,
        executors: dict[str, ActionExecutor],
        action_store: ActionStore,
        idempotency: IdempotencyStore,
        audit: AuditLog,
    ):
        self.settings = settings
        self.catalogue = catalogue
        self.cube = cube
        self.executors = executors
        self.actions = action_store
        self.idempotency = idempotency
        self.audit = audit

    # ---------- discovery ----------

    def list_available(self, domain: str | None, caller_scopes: frozenset[str]) -> list[dict]:
        out = []
        for a in self.catalogue.cat.actions.values():
            if a.status != "approved":
                continue
            if domain and a.domain != domain:
                continue
            authorized = set(a.scopes_required) <= caller_scopes
            out.append(
                {
                    "action_id": a.id,
                    "display_name": a.display_name,
                    "domain": a.domain,
                    "description": a.description.strip(),
                    "risk_level": a.risk_level,
                    "payload_schema": PAYLOAD_SCHEMAS[a.payload_schema].model_json_schema(),
                    "scopes_required": a.scopes_required,
                    "authorized": authorized,
                }
            )
        return out

    # ---------- propose ----------

    async def propose(
        self, action_id: str, payload: dict, caller_scopes: frozenset[str], actor: str
    ) -> ActionPreview:
        contract = self.catalogue.cat.actions.get(action_id)
        if contract is None or contract.status != "approved":
            raise ValueError(
                f"Unknown action '{action_id}'. Use actions_list_available for valid actions."
            )
        missing = set(contract.scopes_required) - caller_scopes
        if missing:
            raise PermissionError(
                f"Caller lacks required scopes for '{action_id}': {sorted(missing)}"
            )

        schema = PAYLOAD_SCHEMAS[contract.payload_schema]
        validated = schema.model_validate(payload).model_dump()

        action_request_id = "act_" + uuid.uuid4().hex[:12]
        rules, current_state = await self._run_business_rules(contract, validated)
        eligible = all(r.passed is not False for r in rules if _is_blocking(contract, r.rule))

        token = None
        expires_at = None
        if eligible:
            expires_epoch = int(time.time()) + contract.confirmation_ttl_seconds
            token = mint_token(
                self.settings.approval_secret,
                action_request_id,
                payload_hash(validated),
                expires_epoch,
            )
            expires_at = datetime.fromtimestamp(expires_epoch, UTC)

        preview = ActionPreview(
            action_request_id=action_request_id,
            action_id=action_id,
            payload=validated,
            current_state=current_state,
            predicted_change=self._predicted_change(contract, current_state),
            business_rule_results=rules,
            eligible=eligible,
            confirmation_token=token,
            token_expires_at=expires_at,
            write_enabled=self.settings.write_enabled,
            note=(
                None
                if self.settings.write_enabled
                else "WRITE_ENABLED is false — commit will be blocked by the kill switch."
            ),
        )

        from .tokens import token_hash as th

        self.actions.create(
            action_request_id=action_request_id,
            action_id=action_id,
            payload=validated,
            p_hash=payload_hash(validated),
            preview=preview.model_dump(mode="json"),
            token_h=th(token) if token else None,
            token_expires_at=expires_at.isoformat() if expires_at else None,
        )
        self.audit.write(
            "action_proposed",
            actor=actor,
            payload={
                "action_request_id": action_request_id,
                "action_id": action_id,
                "payload": validated,
                "eligible": eligible,
                "rules": [r.model_dump() for r in rules],
            },
        )
        return preview

    async def _run_business_rules(
        self, contract: ActionContractDef, payload: dict
    ) -> tuple[list[RuleResult], dict | None]:
        rules: list[RuleResult] = []
        current_state: dict | None = None
        if contract.id == "pause_meta_ad":
            rules.append(await self._rule_ad_exists(payload))
            status_rule, current_state = await self._rule_not_already_paused(payload)
            rules.append(status_rule)
        if contract.business_rules and not rules:
            # Fail closed, loudly — not silently. `eligible = all(r.passed is
            # not False for r in rules if _is_blocking(...))` evaluates
            # all([]) == True, so an action whose catalogue entry declares
            # business_rules but has no branch here would otherwise become
            # immediately eligible with zero of its approved safety checks
            # actually run. Business-rule enforcement in this broker is
            # per-action-id Python, not generic/data-driven from the YAML —
            # this is the explicit trip-wire for the next action added
            # without updating this function to match.
            raise NotImplementedError(
                f"Action '{contract.id}' declares business_rules "
                f"({[r.id for r in contract.business_rules]}) in its catalogue "
                "contract, but ActionBroker._run_business_rules has no "
                "implementation branch for this action id — none of its "
                "declared rules would be enforced. Add one before approving "
                "this action for use."
            )
        return rules, current_state

    async def _rule_ad_exists(self, payload: dict) -> RuleResult:
        from ..app.query_planner import IST

        today = datetime.now(IST).date()
        query = {
            "measures": ["meta_ad_performance.spend", "meta_ad_performance.impressions"],
            "dimensions": ["meta_ad_performance.ad_id", "meta_ad_performance.ad_name"],
            "filters": [
                {"member": "meta_ad_performance.ad_id", "operator": "equals",
                 "values": [payload["ad_id"]]},
                {"member": "meta_ad_performance.brand_id", "operator": "equals",
                 "values": [payload["brand_id"]]},
            ],
            "timeDimensions": [
                {"dimension": "meta_ad_performance.report_date",
                 "dateRange": [(today - timedelta(days=30)).isoformat(), today.isoformat()]}
            ],
            "limit": 10,
        }
        try:
            res = await self.cube.load(query)
        except Exception as exc:
            return RuleResult(rule="ad_exists", passed=None, detail=f"Cube unavailable: {exc}")
        if res.data:
            row = res.data[0]
            spend = row.get("meta_ad_performance.spend")
            name = row.get("meta_ad_performance.ad_name")
            return RuleResult(
                rule="ad_exists",
                passed=True,
                detail=f"Ad '{name}' found; last-30d spend={spend}",
            )
        return RuleResult(
            rule="ad_exists",
            passed=False,
            detail=(
                f"Ad {payload['ad_id']} not found in meta_ad_performance for brand "
                f"{payload['brand_id']} in the last 30 days."
            ),
        )

    async def _rule_not_already_paused(self, payload: dict) -> tuple[RuleResult, dict | None]:
        """Best-effort: latest status event from meta_ad_status_changes."""
        query = {
            "dimensions": [
                "meta_ad_status_changes.status",
                "meta_ad_status_changes.changed_at",
                "meta_ad_status_changes.entity_name",
            ],
            "filters": [
                {"member": "meta_ad_status_changes.ad_id", "operator": "equals",
                 "values": [payload["ad_id"]]},
                {"member": "meta_ad_status_changes.entity_type", "operator": "equals",
                 "values": ["ad"]},
            ],
            "order": {"meta_ad_status_changes.changed_at": "desc"},
            "limit": 1,
        }
        try:
            res = await self.cube.load(query)
        except Exception as exc:
            return (
                RuleResult(
                    rule="not_already_paused",
                    passed=None,
                    detail=f"Status unverifiable (Cube error: {exc})",
                ),
                None,
            )
        if not res.data:
            return (
                RuleResult(
                    rule="not_already_paused",
                    passed=None,
                    detail="No status history found — current status unverifiable.",
                ),
                None,
            )
        row = res.data[0]
        status = (row.get("meta_ad_status_changes.status") or "").upper()
        state = {
            "latest_known_status": status,
            "status_changed_at": row.get("meta_ad_status_changes.changed_at"),
            "entity_name": row.get("meta_ad_status_changes.entity_name"),
            "source": "meta_ad_status_changes (may lag Meta by up to a day)",
        }
        if status == "PAUSED":
            return (
                RuleResult(
                    rule="not_already_paused",
                    passed=False,
                    detail=f"Ad already PAUSED as of {state['status_changed_at']}.",
                ),
                state,
            )
        return (
            RuleResult(rule="not_already_paused", passed=True,
                       detail=f"Latest known status: {status or 'unknown'}"),
            state,
        )

    def _predicted_change(self, contract: ActionContractDef, current_state: dict | None) -> str:
        if contract.id == "pause_meta_ad":
            cur = (current_state or {}).get("latest_known_status", "UNKNOWN")
            return f"ad status {cur} -> PAUSED"
        return contract.description.strip()

    # ---------- commit ----------

    async def commit(self, confirmation_token: str, actor: str) -> CommitResult:
        parsed_id = confirmation_token.split(".")[0] if confirmation_token else ""
        record = self.actions.get(parsed_id)
        if record is None:
            return CommitResult(
                action_request_id=parsed_id or "unknown",
                status="REJECTED",
                executor_response=None,
                audit_ref=None,
                executed_at=None,
                detail="No proposed action matches this token.",
            )



        payload = json.loads(record["payload_json"])
        sig_ok, _, expires_epoch = verify_token(
            self.settings.approval_secret, confirmation_token, record["payload_hash"]
        )
        if not sig_ok:
            self.audit.write("action_commit_rejected", actor=actor,
                             payload={"action_request_id": parsed_id, "reason": "bad_token"})
            return CommitResult(
                action_request_id=parsed_id, status="REJECTED", executor_response=None,
                audit_ref=None, executed_at=None, detail="Invalid confirmation token.",
            )
        if expires_epoch is None or time.time() > expires_epoch:
            self.actions.set_status(parsed_id, "EXPIRED", failure_reason="token expired")
            self.audit.write("action_commit_expired", actor=actor,
                             payload={"action_request_id": parsed_id})
            return CommitResult(
                action_request_id=parsed_id, status="EXPIRED", executor_response=None,
                audit_ref=None, executed_at=None,
                detail="Confirmation token expired — re-propose the action.",
            )
        # Single-use: consume BEFORE dispatch so a crash cannot allow a replay.
        if not self.actions.consume_token(parsed_id):
            return CommitResult(
                action_request_id=parsed_id, status="REJECTED", executor_response=None,
                audit_ref=None, executed_at=None,
                detail="Confirmation token already used.",
            )

        contract = self.catalogue.cat.actions[record["action_id"]]

        # Idempotency across proposals: same action + same payload inside 24h.
        idem_key = f"{record['action_id']}:{record['payload_hash']}"
        prior = self.idempotency.check_and_register(idem_key, parsed_id)
        if prior is not None and prior != parsed_id:
            prior_rec = self.actions.get(prior)
            return CommitResult(
                action_request_id=parsed_id, status="DUPLICATE",
                executor_response=json.loads(prior_rec["executor_response_json"])
                if prior_rec and prior_rec["executor_response_json"] else None,
                audit_ref=prior_rec["audit_ref"] if prior_rec else None,
                executed_at=None,
                detail=f"Identical action already executed as {prior} within 24h.",
            )

        # Global kill switch — enforced at commit time, not propose time.
        if not self.settings.write_enabled:
            self.idempotency.release(idem_key)
            audit_ref = self.audit.write(
                "action_blocked_write_disabled", actor=actor,
                payload={"action_request_id": parsed_id, "action_id": record["action_id"]},
            )
            self.actions.set_status(parsed_id, "FAILED",
                                    failure_reason="WRITE_ENABLED is false", audit_ref=audit_ref)
            return CommitResult(
                action_request_id=parsed_id, status="FAILED", executor_response=None,
                audit_ref=audit_ref, executed_at=None,
                detail="Blocked: WRITE_ENABLED kill switch is off.",
            )

        executor = self.executors[contract.executor]
        before_state = (record.get("preview_json") and
                        json.loads(record["preview_json"]).get("current_state"))
        try:
            response = await executor.execute(contract.executor_action_type, payload)
        except Exception as exc:
            self.idempotency.release(idem_key)
            audit_ref = self.audit.write(
                "action_failed", actor=actor,
                payload={"action_request_id": parsed_id, "error": str(exc),
                         "before_state": before_state},
            )
            self.actions.set_status(parsed_id, "FAILED", failure_reason=str(exc),
                                    audit_ref=audit_ref)
            return CommitResult(
                action_request_id=parsed_id, status="FAILED", executor_response=None,
                audit_ref=audit_ref, executed_at=None, detail=f"Executor error: {exc}",
            )

        executed_at = datetime.now(UTC)
        audit_ref = new_audit_ref()
        self.audit.write(
            "action_executed", actor=actor, audit_ref=audit_ref,
            payload={
                "action_request_id": parsed_id,
                "action_id": record["action_id"],
                "payload": payload,
                "before_state": before_state,
                "executor_response": response,
            },
        )
        self.actions.set_status(
            parsed_id, "EXECUTED", executor_response=response,
            audit_ref=audit_ref, executed_at=executed_at.isoformat(),
        )
        logger.info("action_executed", action_request_id=parsed_id, audit_ref=audit_ref)
        return CommitResult(
            action_request_id=parsed_id, status="EXECUTED",
            executor_response=response, audit_ref=audit_ref, executed_at=executed_at,
        )

    # ---------- status ----------

    def status(self, action_request_id: str) -> dict | None:
        record = self.actions.get(action_request_id)
        if record is None:
            return None


        return {
            "action_request_id": record["action_request_id"],
            "action_id": record["action_id"],
            "status": record["status"],
            "payload": json.loads(record["payload_json"]),
            "created_at": record["created_at"],
            "executed_at": record["executed_at"],
            "failure_reason": record["failure_reason"],
            "audit_ref": record["audit_ref"],
            "audit_trail": self.audit.for_ref(record["audit_ref"]) if record["audit_ref"] else [],
        }


def _is_blocking(contract: ActionContractDef, rule_id: str) -> bool:
    for r in contract.business_rules:
        if r.id == rule_id:
            return r.blocking
    return True
