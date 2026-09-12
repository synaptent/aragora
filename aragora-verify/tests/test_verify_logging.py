"""Logging is local, explicitly configured, and redacts placeholder secrets."""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime

import pytest

from aragora_verify._logging import JsonFormatter, TextFormatter, redact


def _probe(code, **settings):
    env = os.environ.copy()
    for key in ("ARAGORA_LOG_FORMAT", "ARAGORA_LOG_LEVEL"):
        env.pop(key, None)
    env.update(settings)
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )


def test_import_preserves_logging_and_has_no_telemetry():
    result = _probe("""
import logging
import sys
handler = logging.NullHandler()
root = logging.getLogger()
root.addHandler(handler)
root.setLevel(logging.ERROR)
import aragora_verify
import aragora_verify._logging
assert root.handlers == [handler]
assert root.level == logging.ERROR
assert not {"posthog", "sentry_sdk", "opentelemetry"} & sys.modules.keys()
assert "aragora_debate" not in sys.modules
""")
    assert not result.stdout and not result.stderr


def test_json_lines_are_timestamped_and_configuration_is_idempotent():
    result = _probe(
        """
from aragora_verify._logging import configure_logging
import logging
configure_logging()
configure_logging()
logging.getLogger("val").warning("hello\\nworld", extra={"token": "SECRET-ALPHA-123"})
""",
        ARAGORA_LOG_FORMAT="json",
    )
    assert not result.stdout
    (line,) = result.stderr.splitlines()
    data = json.loads(line)
    assert data["level"] == "WARNING"
    assert data["logger"] == "val"
    assert data["msg"] == "hello\nworld"
    assert datetime.fromisoformat(data["ts"]).tzinfo is not None
    assert "SECRET-" not in line


@pytest.mark.parametrize(
    "key", ["api_key", "api-key", "apiKey", "access_token", "secret", "password", "Authorization"]
)
def test_redact_copies_nested_values_and_message_assignments(key):
    payload = {
        "outer": [{key: "SECRET-ALPHA-123", "note": f"{key}=SECRET-BRAVO-456"}],
        "safe": (42, True, None, "hello"),
    }
    redacted = redact(payload)
    assert "SECRET-" not in json.dumps(redacted)
    assert payload["outer"][0][key] == "SECRET-ALPHA-123"
    assert redacted["safe"] == payload["safe"]
    assert redacted["outer"][0][key] == "***"


@pytest.mark.parametrize("formatter", [JsonFormatter(), TextFormatter()])
def test_formatters_redact_messages_and_exceptions_without_mutating_records(formatter):
    record = logging.LogRecord(
        "val", logging.WARNING, "", 0, "api_key=%s", ("SECRET-ALPHA-123",), None
    )
    assert "SECRET-" not in formatter.format(record)
    record.msg = {"nested": {"Authorization": "Bearer SECRET-BRAVO-456"}}
    record.args = ()
    try:
        raise ValueError('password="SECRET-CHARLIE-789 with spaces"')
    except ValueError:
        record.exc_info = sys.exc_info()
    assert "SECRET-" not in formatter.format(record)
    assert record.msg["nested"]["Authorization"] == "Bearer SECRET-BRAVO-456"


@pytest.mark.parametrize("formatter", [JsonFormatter(), TextFormatter()])
def test_numeric_mapping_interpolation_remains_valid(formatter):
    record = logging.LogRecord(
        "val",
        logging.WARNING,
        "",
        0,
        "%(token)06d count=%(count)d",
        ({"token": 123456, "count": 2},),
        None,
    )
    line = formatter.format(record)
    assert "123456" not in line
    assert "*** count=2" in line
    assert record.args["token"] == 123456


@pytest.mark.parametrize("format_name", ["text", "json"])
def test_configured_logger_masks_message_assignments(format_name):
    result = _probe(
        """
from aragora_verify._logging import configure_logging
import logging
configure_logging()
logging.getLogger("val").warning("Authorization=Bearer SECRET-ALPHA-123")
""",
        ARAGORA_LOG_FORMAT=format_name,
    )
    assert "SECRET-" not in result.stderr
    assert "Authorization=***" in result.stderr


@pytest.mark.parametrize(
    "settings", [{}, {"ARAGORA_LOG_FORMAT": "invalid", "ARAGORA_LOG_LEVEL": "invalid"}]
)
def test_defaults_are_plain_text_at_warning(settings):
    result = _probe(
        """
from aragora_verify._logging import configure_logging
import logging
configure_logging()
logging.getLogger("val").info("quiet")
logging.getLogger("val").warning("visible")
""",
        **settings,
    )
    (line,) = result.stderr.splitlines()
    assert line == "WARNING val: visible"
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)


def test_level_environment_setting():
    result = _probe(
        """
from aragora_verify._logging import configure_logging
import logging
configure_logging()
logging.getLogger("val").debug("visible")
""",
        ARAGORA_LOG_FORMAT="json",
        ARAGORA_LOG_LEVEL="debug",
    )
    assert json.loads(result.stderr)["level"] == "DEBUG"
