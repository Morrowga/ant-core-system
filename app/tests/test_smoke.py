"""Smoke tests: app imports, key business-rule units behave.

Run: pytest app/tests -q
"""



def test_app_imports():
    from app.main import app  # noqa: F401
    paths = set(app.openapi()["paths"].keys())
    for path in ("/auth/register", "/attendance/check-in", "/reports", "/overtime/end",
                 "/health/team-wellbeing-trend", "/dashboard/ask", "/billing/plans",
                 "/feedback", "/knowledge/posts", "/certificates/me",
                 "/company/settings/{section}", "/work-threads", "/presence/heartbeat"):
        assert path in paths, f"missing route {path}"


def test_openai_client_signatures_enforce_rule_3():
    from app.integrations import openai_client
    assert hasattr(openai_client, "narrate")
    assert hasattr(openai_client, "classify_question")
    assert hasattr(openai_client, "embed")
    assert not hasattr(openai_client, "compute_and_narrate")
    # local stubs work without an API key
    assert isinstance(openai_client.narrate({"metric": "headcount", "value": 7}), str)
    vec = openai_client.embed(["hello world"])[0]
    assert len(vec) == 1536


def test_pace_label_stub_is_deterministic():
    from app.integrations.openai_client import label_pace
    out = label_pace({"todays_hours": 12, "avg_daily_hours_14d": 6, "summary_text": "x"})
    assert out["pace_label"] == "heavy"


def test_password_hash_roundtrip():
    from app.core.security import hash_password, verify_password
    h = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip_carries_tenant():
    from app.core.security import create_access_token, decode_token
    token = create_access_token(user_id=1, company_id=42, role="manager")
    payload = decode_token(token)
    assert payload["company_id"] == 42 and payload["role"] == "manager"


def test_classifier_stub_matches_only_real_entities():
    from app.integrations.openai_client import classify_question
    types = ["team_summary", "individual_performance", "project_progress",
             "goal_progress", "company_pulse"]
    entities = {"teams": ["Platform"], "employees": ["Alice Nguyen"], "projects": [], "goals": []}
    out = classify_question("How is Alice Nguyen doing?", types, entities=entities)
    assert out == {"query_type": "individual_performance",
                   "parameters": {"employee_name": "Alice Nguyen"}}
    # a name that doesn't exist in this company must NOT classify
    out = classify_question("How is Carol Fake doing?", types, entities=entities)
    assert out["query_type"] is None


def test_non_mutable_notification_categories_are_hardcoded():
    from app.core.services.notifications import NON_MUTABLE_CATEGORIES
    for critical in ("attendance", "overtime", "payroll"):
        assert critical in NON_MUTABLE_CATEGORIES

def test_jwt_roundtrip_carries_tenant():
    from app.core.security import create_access_token, decode_token
    token = create_access_token(user_id=1, company_id=42, organization_id=7, role="manager")
    payload = decode_token(token)
    assert payload["company_id"] == 42 and payload["organization_id"] == 7 and payload["role"] == "manager"