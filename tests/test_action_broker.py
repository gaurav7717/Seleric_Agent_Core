import dataclasses
import time

import pytest

from seleric_mcp.actions.broker import ActionBroker
from seleric_mcp.actions.tokens import mint_token, payload_hash

PAYLOAD = {
    "ad_id": "123456789012",
    "brand_id": "20",
    "reason": "ROAS below breakeven for 7 consecutive days",
}

AD_ROWS = [
    {
        "meta_ad_performance.ad_id": "123456789012",
        "meta_ad_performance.ad_name": "UGC Hook v3",
        "meta_ad_performance.spend": "5000",
        "meta_ad_performance.impressions": "100000",
    }
]
STATUS_ROWS = [
    {
        "meta_ad_status_changes.status": "ACTIVE",
        "meta_ad_status_changes.changed_at": "2026-07-01T10:00:00",
        "meta_ad_status_changes.entity_name": "UGC Hook v3",
    }
]


# The platform ships ZERO actions since the 2026-07-14 slim-down (catalogue/
# actions/ is empty), but the broker is live shipped code — keep its mechanism
# coverage with a synthetic contract that mirrors the retired pause_meta_ad
# (recovered from git history) exactly.
_TEST_ACTION = {
    "id": "pause_meta_ad",
    "display_name": "Pause Meta Ad",
    "domain": "meta_ads",
    "status": "approved",
    "description": "Test-only synthetic contract mirroring the retired pause_meta_ad.",
    "executor": "pipeboard",
    "executor_action_type": "pause_ad",
    "payload_schema": "PauseMetaAdPayload",
    "scopes_required": ["meta_ads:write:status"],
    "risk_level": "medium",
    "confirmation_ttl_seconds": 300,
    "business_rules": [
        {"id": "ad_exists", "description": "Ad must appear in meta_ad_performance.", "blocking": True},
        {"id": "not_already_paused", "description": "Latest status should not be PAUSED.", "blocking": False},
        {"id": "write_enabled", "description": "WRITE_ENABLED kill switch.", "blocking": True},
    ],
    "preview": {"sources": []},
    "data_owner": "Growth",
}


@pytest.fixture()
def broker(settings, catalogue, fake_cube, fake_executor, action_store, idempotency, audit):
    from seleric_mcp.catalogue_service.loader import ActionContractDef

    catalogue.cat.actions["pause_meta_ad"] = ActionContractDef.model_validate(_TEST_ACTION)
    fake_cube.by_prefix["meta_ad_performance"] = AD_ROWS
    fake_cube.by_prefix["meta_ad_status_changes"] = STATUS_ROWS
    return ActionBroker(
        settings=settings,
        catalogue=catalogue,
        cube=fake_cube,
        executors={"pipeboard": fake_executor},
        action_store=action_store,
        idempotency=idempotency,
        audit=audit,
    )


@pytest.fixture()
def broker_writes_on(broker):
    broker.settings = dataclasses.replace(broker.settings, write_enabled=True)
    return broker


def test_list_available_reports_authorization(broker):
    actions = broker.list_available(None, frozenset({"metrics:read"}))
    assert actions[0]["action_id"] == "pause_meta_ad"
    assert actions[0]["authorized"] is False
    actions = broker.list_available(None, frozenset({"meta_ads:write:status"}))
    assert actions[0]["authorized"] is True


async def test_propose_requires_scope(broker):
    with pytest.raises(PermissionError):
        await broker.propose("pause_meta_ad", PAYLOAD, frozenset({"metrics:read"}), "tester")


async def test_propose_validates_payload(broker, settings):
    with pytest.raises(Exception):
        await broker.propose(
            "pause_meta_ad",
            {"ad_id": "not-numeric", "brand_id": "20", "reason": "long enough reason here"},
            settings.caller_scopes,
            "tester",
        )


async def test_propose_happy_path(broker, settings):
    preview = await broker.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester")
    assert preview.eligible is True
    assert preview.confirmation_token
    assert preview.current_state["latest_known_status"] == "ACTIVE"
    assert preview.predicted_change == "ad status ACTIVE -> PAUSED"
    rules = {r.rule: r for r in preview.business_rule_results}
    assert rules["ad_exists"].passed is True
    assert rules["not_already_paused"].passed is True
    assert preview.write_enabled is False
    assert preview.note  # warns about kill switch


async def test_propose_blocks_missing_ad(broker, settings, fake_cube):
    fake_cube.by_prefix["meta_ad_performance"] = []
    preview = await broker.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester")
    assert preview.eligible is False
    assert preview.confirmation_token is None


async def test_propose_already_paused_blocks(broker, settings, fake_cube):
    fake_cube.by_prefix["meta_ad_status_changes"] = [
        {**STATUS_ROWS[0], "meta_ad_status_changes.status": "PAUSED"}
    ]
    preview = await broker.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester")
    # not_already_paused is non-blocking in the contract, so still eligible…
    rules = {r.rule: r for r in preview.business_rule_results}
    assert rules["not_already_paused"].passed is False
    assert preview.eligible is True  # non-blocking rule


async def test_propose_unverifiable_status_does_not_block(broker, settings, fake_cube):
    fake_cube.by_prefix["meta_ad_status_changes"] = []
    preview = await broker.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester")
    rules = {r.rule: r for r in preview.business_rule_results}
    assert rules["not_already_paused"].passed is None
    assert preview.eligible is True


async def test_commit_blocked_by_kill_switch(broker, settings):
    preview = await broker.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester")
    result = await broker.commit(preview.confirmation_token, "tester")
    assert result.status == "FAILED"
    assert "kill switch" in result.detail.lower() or "WRITE_ENABLED" in result.detail


async def test_commit_executes_when_writes_on(broker_writes_on, settings, fake_executor):
    preview = await broker_writes_on.propose(
        "pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester"
    )
    result = await broker_writes_on.commit(preview.confirmation_token, "tester")
    assert result.status == "EXECUTED"
    assert result.audit_ref.startswith("AR-")
    assert fake_executor.executed == [("pause_ad", PAYLOAD)]
    status = broker_writes_on.status(preview.action_request_id)
    assert status["status"] == "EXECUTED"
    assert status["audit_trail"]


async def test_token_single_use(broker_writes_on, settings, fake_executor):
    preview = await broker_writes_on.propose(
        "pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester"
    )
    first = await broker_writes_on.commit(preview.confirmation_token, "tester")
    assert first.status == "EXECUTED"
    second = await broker_writes_on.commit(preview.confirmation_token, "tester")
    assert second.status == "REJECTED"
    assert "already used" in second.detail
    assert len(fake_executor.executed) == 1


async def test_tampered_token_rejected(broker_writes_on, settings, fake_executor):
    preview = await broker_writes_on.propose(
        "pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester"
    )
    parts = preview.confirmation_token.split(".")
    tampered = f"{parts[0]}.{int(parts[1]) + 9999}.{parts[2]}"
    result = await broker_writes_on.commit(tampered, "tester")
    assert result.status == "REJECTED"
    assert not fake_executor.executed


async def test_expired_token(broker_writes_on, settings, fake_executor):
    preview = await broker_writes_on.propose(
        "pause_meta_ad", PAYLOAD, settings.caller_scopes, "tester"
    )
    # Re-mint a token with the correct secret but an expiry in the past.
    expired = mint_token(
        settings.approval_secret,
        preview.action_request_id,
        payload_hash(preview.payload),
        int(time.time()) - 10,
    )
    result = await broker_writes_on.commit(expired, "tester")
    assert result.status == "EXPIRED"
    assert not fake_executor.executed


async def test_idempotency_duplicate(broker_writes_on, settings, fake_executor):
    p1 = await broker_writes_on.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "t")
    r1 = await broker_writes_on.commit(p1.confirmation_token, "t")
    assert r1.status == "EXECUTED"
    # Same payload proposed again -> new token, but commit dedupes inside 24h.
    p2 = await broker_writes_on.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "t")
    r2 = await broker_writes_on.commit(p2.confirmation_token, "t")
    assert r2.status == "DUPLICATE"
    assert len(fake_executor.executed) == 1


async def test_executor_failure_releases_idempotency(broker_writes_on, settings, fake_executor):
    fake_executor.fail = True
    p1 = await broker_writes_on.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "t")
    r1 = await broker_writes_on.commit(p1.confirmation_token, "t")
    assert r1.status == "FAILED"
    # Retry with a fresh proposal succeeds (key released, token was single-use).
    fake_executor.fail = False
    p2 = await broker_writes_on.propose("pause_meta_ad", PAYLOAD, settings.caller_scopes, "t")
    r2 = await broker_writes_on.commit(p2.confirmation_token, "t")
    assert r2.status == "EXECUTED"


async def test_unknown_action(broker, settings):
    with pytest.raises(ValueError, match="Unknown action"):
        await broker.propose("delete_everything", {}, settings.caller_scopes, "t")


async def test_business_rules_fail_closed_for_unimplemented_action(broker):
    """_run_business_rules is per-action-id Python, not generic/data-driven
    from the catalogue YAML. A contract that declares business_rules but has
    no matching branch here must raise, not silently produce eligible=True
    via all([]) == True on an empty rules list — that would approve a write
    action with zero of its approved safety checks actually run. Uses a
    synthetic contract (not a real catalogue entry) since only one action
    exists today and it IS correctly wired."""
    from seleric_mcp.catalogue_service.loader import ActionContractDef, BusinessRule

    fake_contract = ActionContractDef(
        id="hypothetical_future_action",
        display_name="Hypothetical",
        domain="test",
        description="A contract with a declared rule nobody implemented yet.",
        executor="pipeboard",
        executor_action_type="noop",
        payload_schema="PauseMetaAdPayload",
        scopes_required=[],
        risk_level="low",
        business_rules=[BusinessRule(id="some_check", description="...", blocking=True)],
        data_owner="Test",
    )
    with pytest.raises(NotImplementedError, match="hypothetical_future_action"):
        await broker._run_business_rules(fake_contract, {})
