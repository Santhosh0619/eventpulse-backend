"""OpenAPI completeness checks: every operation is documented and tagged."""

from app.main import app


def test_openapi_schema_generates() -> None:
    """The OpenAPI schema builds without error and exposes paths."""
    schema = app.openapi()
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"]
    assert len(schema["paths"]) > 0


def test_every_operation_has_summary_and_tags() -> None:
    """Every API operation carries a human-readable summary and at least one tag."""
    schema = app.openapi()
    missing: list[str] = []
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not operation.get("summary"):
                missing.append(f"{method.upper()} {path}: no summary")
            if not operation.get("tags"):
                missing.append(f"{method.upper()} {path}: no tags")
    assert not missing, "Undocumented operations:\n" + "\n".join(missing)


def test_all_documented_endpoints_present() -> None:
    """A representative set of endpoints across phases is present in the schema."""
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/auth/login",
        "/api/v1/events",
        "/api/v1/orders",
        "/api/v1/payments/create-intent",
        "/api/v1/analytics/platform",
        "/api/v1/recommendations/events",
        "/api/v1/admin/audit-logs",
        "/api/v1/health/ready",
    }
    assert expected <= paths
