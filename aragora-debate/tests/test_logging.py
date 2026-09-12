"""The logging entry point is explicit and secrets never reach its formatters."""

import ast
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from aragora_debate._logging import JsonFormatter, TextFormatter, redact


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


def test_import_does_not_reconfigure_root_logging():
    result = _probe("""
import logging
handler = logging.NullHandler()
root = logging.getLogger()
root.addHandler(handler)
root.setLevel(logging.ERROR)
import aragora_debate
import aragora_debate._logging
assert root.handlers == [handler]
assert root.level == logging.ERROR
""")
    assert not result.stdout and not result.stderr


def test_package_has_no_telemetry_sdk_imports():
    import aragora_debate

    for path in Path(aragora_debate.__file__).parent.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(
                name.split(".")[0] in {"posthog", "sentry_sdk", "opentelemetry"} for name in names
            ), path


def test_json_logging_line_shape_and_explicit_configuration():
    result = _probe(
        """
from aragora_debate._logging import configure_logging
import logging
configure_logging()
configure_logging()
logging.getLogger("val").warning("hello\\nworld")
""",
        ARAGORA_LOG_FORMAT="json",
    )
    assert not result.stdout
    (line,) = result.stderr.splitlines()
    data = json.loads(line)
    assert data["level"] == "WARNING"
    assert data["logger"] == "val"
    assert data["msg"] == "hello\nworld"
    from datetime import datetime

    assert datetime.fromisoformat(data["ts"]).tzinfo is not None


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "API-KEY",
        "apikey",
        "apiKey",
        "access_token",
        "secret",
        "password",
        "Authorization",
    ],
)
def test_redact_nested_keys_and_strings_without_mutating_input(key):
    value = {
        "outer": [{key: "SECRET-ALPHA-123", "note": "token=SECRET-BRAVO-456"}],
        "safe": (42, True, None, "hello"),
    }
    redacted = redact(value)
    assert "SECRET-" not in json.dumps(redacted)
    assert value["outer"][0][key] == "SECRET-ALPHA-123"
    assert redacted["safe"] == value["safe"]
    assert len(redacted["outer"]) == 1


@pytest.mark.parametrize(
    "message",
    [
        "connecting with api_key=SECRET-ECHO-111",
        'password="SECRET-ALPHA-123 with spaces" token=SECRET-BRAVO-456',
        "api-key='SECRET-ALPHA-123 with spaces',secret=SECRET-BRAVO-456",
        "Authorization=Bearer SECRET-CHARLIE-789",
    ],
)
def test_redact_message_assignments(message):
    assert "SECRET-" not in redact(message)


@pytest.mark.parametrize("formatter", [JsonFormatter(), TextFormatter()])
def test_formatters_redact_interpolated_messages_nested_payloads_and_exceptions(formatter):
    record = logging.LogRecord(
        "test", logging.WARNING, "", 0, "api_key=%s", ("SECRET-ALPHA-123",), None
    )
    assert "SECRET-" not in formatter.format(record)
    record.msg = {"nested": {"Authorization": "Bearer SECRET-CHARLIE-789"}}
    record.args = ()
    assert "SECRET-" not in formatter.format(record)
    try:
        raise ValueError("password=SECRET-DELTA-000")
    except ValueError:
        record.exc_info = sys.exc_info()
    assert "SECRET-" not in formatter.format(record)
    assert record.msg["nested"]["Authorization"] == "Bearer SECRET-CHARLIE-789"


@pytest.mark.parametrize("format_name", ["text", "json"])
def test_configured_logger_masks_secret_message(format_name):
    result = _probe(
        """
from aragora_debate._logging import configure_logging
import logging
configure_logging()
logging.getLogger("val").warning("connecting with api_key=SECRET-ECHO-111")
""",
        ARAGORA_LOG_FORMAT=format_name,
    )
    assert "SECRET-ECHO-111" not in result.stderr
    assert "connecting with" in result.stderr


def test_json_formatter_redacts_extra_fields_stack_and_preserves_record():
    record = logging.LogRecord("test", logging.WARNING, "", 0, "safe", (), None)
    record.payload = {"outer": [{"api_key": "SECRET-ALPHA-123", "count": 2}]}
    record.stack_info = "token=SECRET-BRAVO-456"
    line = JsonFormatter().format(record)
    data = json.loads(line)
    assert data["payload"]["outer"][0]["count"] == 2
    assert "SECRET-" not in line
    assert record.payload["outer"][0]["api_key"] == "SECRET-ALPHA-123"


@pytest.mark.parametrize("formatter", [JsonFormatter(), TextFormatter()])
@pytest.mark.parametrize("field", ["06d", "+#x", ".2f", "r", "s"])
def test_formatters_support_sensitive_numeric_mapping_fields(formatter, field):
    record = logging.LogRecord(
        "test",
        logging.WARNING,
        "",
        0,
        f"credential %(token){field}; count %(count)d; literal %%(token)d",
        ({"token": 123456, "count": 2},),
        None,
    )
    line = formatter.format(record)
    assert "123456" not in line
    assert "credential ***; count 2; literal %(token)d" in line
    assert record.args["token"] == 123456


@pytest.mark.parametrize(
    "settings", [{}, {"ARAGORA_LOG_FORMAT": "invalid", "ARAGORA_LOG_LEVEL": "invalid"}]
)
def test_default_logging_is_text_at_warning(settings):
    result = _probe(
        """
from aragora_debate._logging import configure_logging
import logging
configure_logging()
logging.getLogger("val").info("quiet")
logging.getLogger("val").warning("visible")
""",
        **settings,
    )
    (line,) = result.stderr.splitlines()
    assert "quiet" not in line and "visible" in line
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)


def test_logging_level_environment_setting():
    result = _probe(
        """
from aragora_debate._logging import configure_logging
import logging
configure_logging()
logging.getLogger("val").debug("visible")
""",
        ARAGORA_LOG_FORMAT="json",
        ARAGORA_LOG_LEVEL="debug",
    )
    assert json.loads(result.stderr)["level"] == "DEBUG"
