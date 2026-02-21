from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from eventpulse.api_server import SPAStaticFiles


def _scope(path: str) -> dict[str, object]:
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }


def test_spa_static_files_fallback_for_client_route(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    static = SPAStaticFiles(directory=str(tmp_path), html=True)

    response = asyncio.run(static.get_response("devices", _scope("/devices")))

    assert response.status_code == 200


def test_spa_static_files_keeps_404_for_api_paths(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    static = SPAStaticFiles(directory=str(tmp_path), html=True)

    with pytest.raises(StarletteHTTPException) as ex:
        asyncio.run(static.get_response("api/healthz", _scope("/api/healthz")))

    assert ex.value.status_code == 404


def test_spa_static_files_keeps_404_for_missing_assets(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    static = SPAStaticFiles(directory=str(tmp_path), html=True)

    with pytest.raises(StarletteHTTPException) as ex:
        asyncio.run(static.get_response("assets/missing.js", _scope("/assets/missing.js")))

    assert ex.value.status_code == 404
