from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from eventpulse import api_server


def _with_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    monkeypatch.setattr(api_server, "settings", replace(api_server.settings, **overrides))


def _noop_init_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_server, "init_db", lambda: None)


def _request(path: str, *, method: str = "POST", headers: dict[str, str] | None = None) -> Request:
    header_list = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "scheme": "https",
        "query_string": b"",
        "headers": header_list,
        "server": ("testserver", 443),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_parse_gcs_uri_accepts_nested_object_path() -> None:
    bucket, object_name = api_server._parse_gcs_uri("gs://media-bucket/media/device-1/2026/02/20/snapshot.jpg")

    assert bucket == "media-bucket"
    assert object_name == "media/device-1/2026/02/20/snapshot.jpg"


def test_api_healthz_alias_matches_healthz() -> None:
    assert api_server.api_healthz() == api_server.healthz()


@pytest.mark.parametrize(
    "gcs_uri",
    [
        "",
        "http://bucket/object.jpg",
        "gs://bucket",
        "gs:///object.jpg",
        "gs://bucket/",
    ],
)
def test_parse_gcs_uri_rejects_invalid_shapes(gcs_uri: str) -> None:
    with pytest.raises(ValueError):
        api_server._parse_gcs_uri(gcs_uri)


def test_edge_media_finalize_rejects_unexpected_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_settings(
        monkeypatch,
        enable_edge_media=True,
        storage_backend="gcs",
        raw_gcs_bucket="raw-bucket",
        edge_media_gcs_bucket="media-bucket",
        edge_media_gcs_prefix="media",
        edge_media_allowed_exts=[".jpg"],
    )
    _noop_init_db(monkeypatch)
    monkeypatch.setattr(api_server, "_require_edge_device_auth", lambda request: "device-1")

    with pytest.raises(HTTPException) as ex:
        api_server.edge_media_finalize(
            _request("/api/edge/media/finalize"),
            {"gcs_uri": "gs://wrong-bucket/media/device-1/2026/02/20/snapshot.jpg"},
        )

    assert ex.value.status_code == 400
    assert ex.value.detail == "unexpected bucket"


def test_edge_media_finalize_enforces_device_prefix_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_settings(
        monkeypatch,
        enable_edge_media=True,
        storage_backend="gcs",
        raw_gcs_bucket="raw-bucket",
        edge_media_gcs_bucket="media-bucket",
        edge_media_gcs_prefix="media",
        edge_media_allowed_exts=[".jpg"],
    )
    _noop_init_db(monkeypatch)
    monkeypatch.setattr(api_server, "_require_edge_device_auth", lambda request: "device-1")

    with pytest.raises(HTTPException) as ex:
        api_server.edge_media_finalize(
            _request("/api/edge/media/finalize"),
            {"gcs_uri": "gs://media-bucket/media/device-2/2026/02/20/snapshot.jpg"},
        )

    assert ex.value.status_code == 403
    assert ex.value.detail == "object_name not owned by device"


def test_edge_media_finalize_returns_plain_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_settings(
        monkeypatch,
        enable_edge_media=True,
        storage_backend="gcs",
        raw_gcs_bucket="raw-bucket",
        edge_media_gcs_bucket="media-bucket",
        edge_media_gcs_prefix="media",
        edge_media_allowed_exts=[".jpg"],
    )
    _noop_init_db(monkeypatch)
    monkeypatch.setattr(api_server, "_require_edge_device_auth", lambda request: "device-1")
    monkeypatch.setattr(
        api_server,
        "create_device_media",
        lambda **kwargs: {
            "id": uuid.uuid4(),
            "device_id": kwargs["device_id"],
            "gcs_uri": kwargs["gcs_uri"],
        },
    )
    monkeypatch.setattr(api_server, "insert_audit_event", lambda **kwargs: None)

    result = api_server.edge_media_finalize(
        _request("/api/edge/media/finalize"),
        {"gcs_uri": "gs://media-bucket/media/device-1/2026/02/20/snapshot.jpg"},
    )

    assert isinstance(result, dict)
    assert result["ok"] is True
    assert "item" in result


def test_internal_media_requires_task_token_when_task_auth_mode_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_settings(monkeypatch, task_auth_mode="token", task_token="task-secret")
    _noop_init_db(monkeypatch)
    monkeypatch.setattr(api_server, "list_device_media", lambda limit=200, device_id=None: [])

    with pytest.raises(HTTPException) as ex:
        api_server.internal_list_media(_request("/internal/admin/media", method="GET"))
    assert ex.value.status_code == 403

    allowed = api_server.internal_list_media(
        _request("/internal/admin/media", method="GET", headers={"x-task-token": "task-secret"})
    )
    assert allowed["ok"] is True


def test_internal_media_allows_iam_mode_without_task_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_settings(monkeypatch, task_auth_mode="iam", task_token="")
    _noop_init_db(monkeypatch)
    monkeypatch.setattr(api_server, "list_device_media", lambda limit=200, device_id=None: [])

    response = api_server.internal_list_media(_request("/internal/admin/media", method="GET"))
    assert response["ok"] is True


def test_internal_media_signed_get_rejects_unexpected_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_settings(
        monkeypatch,
        task_auth_mode="token",
        task_token="task-secret",
        raw_gcs_bucket="raw-bucket",
        edge_media_gcs_bucket="media-bucket",
        edge_media_gcs_prefix="media",
    )
    _noop_init_db(monkeypatch)

    with pytest.raises(HTTPException) as ex:
        api_server.internal_media_read_signed_url(
            _request(
                "/internal/admin/media/gcs_read_signed_url",
                headers={"x-task-token": "task-secret"},
            ),
            {"gcs_uri": "gs://wrong-bucket/media/device-1/2026/02/20/snapshot.jpg"},
        )

    assert ex.value.status_code == 400
    assert ex.value.detail == "unexpected bucket"


def test_internal_media_routes_are_hidden_from_openapi_schema() -> None:
    hidden = {route.path for route in api_server.app.routes if getattr(route, "include_in_schema", True) is False}

    assert "/internal/admin/media" in hidden
    assert "/internal/admin/media/{media_id}" in hidden
    assert "/internal/admin/media/gcs_read_signed_url" in hidden
