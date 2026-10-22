"""Downloads must authenticate their HTTPS peer, including failure paths."""
import importlib.util
from pathlib import Path
import ssl
import urllib.error

import pytest


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    spec = importlib.util.spec_from_file_location("backend", Path(__file__).parents[1] / "backend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("operation", ["catalog", "download"])
def test_certificate_failure_is_not_bypassed(backend, monkeypatch, operation):
    calls = []
    def refuse(request, *, timeout, context):
        calls.append(request.full_url)
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        raise urllib.error.URLError(ssl.SSLCertVerificationError("untrusted certificate"))
    monkeypatch.setattr(backend.urllib.request, "urlopen", refuse)
    with pytest.raises(urllib.error.URLError):
        if operation == "catalog":
            backend._http_get("https://example.invalid/catalog")
        else:
            backend.download_zip(1, "https://example.invalid/map.zip")
    assert len(calls) == 1
    assert not (backend.DOWNLOAD_DIR / "1.zip").exists()
