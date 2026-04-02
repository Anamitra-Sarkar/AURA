from __future__ import annotations

import io
import json

from aura.core.logging import configure_logging, get_logger


def test_json_logging():
    stream = io.StringIO()
    configure_logging(stream=stream)
    logger = get_logger("aura.test", component="tests")
    logger.info("hello")
    payload = json.loads(stream.getvalue().strip())
    assert payload["message"] == "hello"
    assert payload["component"] == "tests"
