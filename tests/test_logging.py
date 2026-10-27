from __future__ import annotations

import logging

from sift import runtime
from sift.config import Settings


def test_secrets_are_redacted_from_tracebacks_too(settings: Settings) -> None:
    secret = "sk-ant-api03-very-secret"
    s = settings.model_copy(update={"anthropic_api_key": __import__("pydantic").SecretStr(secret)})
    runtime.setup_logging(s, console=False)
    log = logging.getLogger("sift.test")
    try:
        raise RuntimeError(f"request failed with key {secret}")
    except RuntimeError:
        log.exception("call failed for %s", secret)
    for h in logging.getLogger().handlers:
        h.flush()
    text = (s.logs_dir / "sift.log").read_text()
    assert "[redacted]" in text and secret not in text
