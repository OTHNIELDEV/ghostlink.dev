from sqlalchemy import create_engine, inspect, text

from app.db.engine import (
    _ensure_approval_columns,
    _ensure_bandit_columns,
    _ensure_optimization_columns,
)


def test_ensure_approval_columns_adds_missing_columns():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE approvalrequest (
                    id INTEGER PRIMARY KEY,
                    org_id INTEGER NOT NULL,
                    request_type VARCHAR NOT NULL,
                    request_payload VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    requested_by_user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )

        # Must be safe to run repeatedly during startup.
        _ensure_approval_columns(conn)
        _ensure_approval_columns(conn)

        columns = {col["name"] for col in inspect(conn).get_columns("approvalrequest")}

    assert "reviewed_by_user_id" in columns
    assert "requester_note" in columns
    assert "review_note" in columns
    assert "execution_result" in columns
    assert "reviewed_at" in columns
    assert "updated_at" in columns


def test_ensure_optimization_columns_adds_missing_columns():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE optimizationaction (
                    id INTEGER PRIMARY KEY,
                    site_id INTEGER NOT NULL,
                    org_id INTEGER NOT NULL,
                    title VARCHAR NOT NULL,
                    proposed_instruction VARCHAR NOT NULL
                )
                """
            )
        )

        _ensure_optimization_columns(conn)
        _ensure_optimization_columns(conn)

        columns = {col["name"] for col in inspect(conn).get_columns("optimizationaction")}

    assert "source_recommendation" in columns
    assert "rationale" in columns
    assert "status" in columns
    assert "loop_version" in columns
    assert "decided_by_user_id" in columns
    assert "applied_by_user_id" in columns
    assert "decided_at" in columns
    assert "applied_at" in columns
    assert "error_msg" in columns
    assert "created_at" in columns
    assert "updated_at" in columns


def test_ensure_bandit_columns_adds_missing_columns():
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE optimizationbanditarm (
                    id INTEGER PRIMARY KEY,
                    org_id INTEGER NOT NULL,
                    site_id INTEGER NOT NULL,
                    action_id INTEGER NOT NULL,
                    arm_key VARCHAR NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE optimizationbanditdecision (
                    id INTEGER PRIMARY KEY,
                    org_id INTEGER NOT NULL,
                    site_id INTEGER NOT NULL,
                    created_by_user_id INTEGER NOT NULL
                )
                """
            )
        )

        _ensure_bandit_columns(conn)
        _ensure_bandit_columns(conn)

        arm_columns = {col["name"] for col in inspect(conn).get_columns("optimizationbanditarm")}
        decision_columns = {col["name"] for col in inspect(conn).get_columns("optimizationbanditdecision")}

    assert "alpha" in arm_columns
    assert "beta" in arm_columns
    assert "pulls" in arm_columns
    assert "average_reward" in arm_columns
    assert "metadata_json" in arm_columns
    assert "updated_at" in arm_columns

    assert "selected_action_id" in decision_columns
    assert "selected_arm_key" in decision_columns
    assert "strategy" in decision_columns
    assert "scored_candidates_json" in decision_columns
    assert "context_json" in decision_columns
    assert "created_at" in decision_columns
