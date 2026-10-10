"""Logging is local, explicitly configured, and redacts placeholder secrets."""

import ast
import io
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


class _Unprintable:
    """An argument whose conversion to text raises something other than TypeError."""

    def __str__(self):
        raise RuntimeError("SECRET-ZULU-7 in the exception text")

    def __format__(self, spec):
        raise RuntimeError("SECRET-ZULU-7 in the exception text")


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


@pytest.mark.parametrize(
    "value",
    [
        ["Authorization: Bearer SECRET-FOXTROT-222"],
        '{"api_key": "SECRET-GOLF-333"}',
        "Authorization: Bearer SECRET-HOTEL-444",
        str({"Authorization": "Bearer SECRET-JULIET-666"}),
        "authorization:Basic SECRET-KILO-777",
        "{'password': 'SECRET-MIKE-999 with spaces'}",
        "Authorization: Token SECRET-PAPA-222",
        "Authorization: AWS4-HMAC-SHA256 Credential=SECRET-ROMEO-444/s3, Signature=SECRET-SIERRA-5",
    ],
)
def test_redact_colon_and_quoted_key_forms(value):
    assert "SECRET-" not in json.dumps(redact(value), default=str)


def test_redact_masks_any_authorization_scheme_and_replaces_cycles():
    assert redact("Authorization: Token SECRET-PAPA-222 sent\nnext line") == (
        "Authorization: ***\nnext line"
    )
    payload = {"name": "x", "token": "SECRET-WHISKEY-3"}
    payload["self"] = payload
    assert redact(payload) == {"name": "x", "token": "***", "self": "<cycle>"}


_DIGEST = 'Digest username="Jane Doe", realm="test", response="SECRET-ZULU-8"'


@pytest.mark.parametrize("header", ["Authorization", "Proxy-Authorization"])
def test_redact_masks_digest_params_with_quoted_spaced_values(header):
    plain = f"{header}: {_DIGEST}"
    assert redact(plain) == f"{header}: ***"
    assert redact(f"{header}={_DIGEST}") == f"{header}=***"
    assert json.loads(redact(json.dumps({header: _DIGEST}))) == {header: "***"}
    assert redact(str({header: _DIGEST})) == str({header: "***"})
    assert json.loads(redact(json.dumps(plain))) == f"{header}: ***"
    assert json.loads(redact(json.dumps({"headers": plain}))) == {"headers": f"{header}: ***"}
    assert redact(str({"headers": plain})) == str({"headers": f"{header}: ***"})
    record = logging.LogRecord("val", logging.WARNING, "", 0, plain, (), None)
    assert json.loads(JsonFormatter().format(record))["msg"] == f"{header}: ***"
    assert TextFormatter().format(record) == f"{header}: ***"


@pytest.mark.parametrize(
    "value",
    [
        'Digest username="Doe, Jane", response="SECRET-ZULU-9"',
        'Digest username = "Jane", response = "SECRET-ZULU-9"',
        'username="Jane Doe", response="SECRET-ZULU-9"',
        'username = "Jane Doe", response = "SECRET-ZULU-9"',
        'OAuth realm="Example Realm", oauth_signature="SECRET-ZULU-9"',
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20250101/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;x-amz-date, Signature=SECRET-ZULU-9",
        'Digest username="Jane Doe",, , response="SECRET-ZULU-9"',
        'Custom key.id="Jane Doe", sig="SECRET-ZULU-9"',
        '1Scheme user="Jane Doe", response="SECRET-ZULU-9"',
        'Digest username="Jane Doe", nonce="n"x, response="SECRET-ZULU-9"',
    ],
    ids=[
        "quoted-comma",
        "spaces-around-equals",
        "no-scheme",
        "no-scheme-spaces-around-equals",
        "oauth-realm",
        "sigv4-signed-headers",
        "empty-list-elements",
        "token-chars-in-param-name",
        "digit-first-scheme",
        "junk-after-quoted-value",
    ],
)
def test_redact_masks_every_auth_param_up_to_the_end_of_the_line(value):
    masked = redact(f"Authorization: {value} next")
    assert masked == "Authorization: ***"
    assert redact(masked) == masked


def test_redact_masks_a_json_encoded_auth_param_holding_an_escaped_quote():
    line = 'Authorization: Digest username="Jane \\"JD\\" Doe", response="SECRET-ZULU-9"'
    assert redact(line) == "Authorization: ***"
    assert json.loads(redact(json.dumps(line))) == "Authorization: ***"
    assert json.loads(redact(json.dumps({"headers": line}))) == {"headers": "Authorization: ***"}


# Every synthetic credential part contains "SECRET-".
_AUTH_CREDENTIALS = {
    "token68": "SECRET-T68-dXNlcjpwYXNz+/9==",
    "quoted-first-param-with-spaces": (
        'username="Jane SECRET-QF-1 Doe", realm="test", response="SECRET-QF-2"'
    ),
    "ext-param-first": "username*=UTF-8''J%C3%A4ne%20SECRET-XF-1, realm=test, response=SECRET-XF-2",
    "ext-param-middle": 'realm="test", username*=UTF-8\'\'J%C3%A4ne%20Doe, response="SECRET-XM-1"',
    "ext-param-last": (
        'realm="test", response="SECRET-XL-1", username*=UTF-8\'en\'J%C3%A4ne%20SECRET-XL-2'
    ),
    "spaces-around-equals": 'realm = "test" , nonce= "SECRET-WS-1" , response ="SECRET-WS-2"',
    "empty-list-elements": ', realm="test",, , nonce="SECRET-EL-1" ,,response="SECRET-EL-2",',
    "escaped-quotes-and-commas": (
        r'realm="a \"b\", c", opaque=", SECRET-EQ-1 \"x\"", response="SECRET-EQ-2"'
    ),
    "unquoted-last-param": 'realm="test", qop=auth, response=SECRET-UQ-1',
}


def _fold(line):
    """The header with obs-fold continuation lines, as http.client and email keep it."""
    head, scheme_and_credential = line.split(": ", 1)
    scheme, _, credential = scheme_and_credential.partition(" ")
    return f"{head}: {scheme}\r\n " + credential.replace(", ", ",\n\t")


# Containers are built the way logging receives them: json.dumps() and repr() of a mapping.
_AUTH_CONTAINERS = {
    "plain-line": lambda line: line,
    "line-then-text": lambda line: f"{line} (retrying, attempt=2)",
    "folded-lines": _fold,
    "json-dumps": lambda line: json.dumps({"headers": line, "next": "ok"}),
    "repr": lambda line: repr({"headers": line, "next": "ok"}),
}
_PROPOSAL_FAILED = "Agent proposal failed: "


def _render_through(path, text):
    """Return the full output and the redacted text for one rendering path."""
    if path == "redact":
        masked = redact(text)
        return masked, masked
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JsonFormatter()
        if path == "json-formatter"
        else TextFormatter("%(levelname)s %(name)s: %(message)s")
    )
    logger = logging.getLogger("aragora_verify.tests.auth_matrix")
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        # The arena's failure path logs the provider exception through "%s".
        logger.warning(_PROPOSAL_FAILED + "%s", RuntimeError(text))
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert output.endswith("\n")
    if path == "json-formatter":
        message = json.loads(output)["msg"]
    else:
        message = output[:-1].removeprefix(f"WARNING {logger.name}: ")
    assert message.startswith(_PROPOSAL_FAILED)
    return output, message[len(_PROPOSAL_FAILED) :]


@pytest.mark.parametrize("path", ["redact", "text-formatter", "json-formatter"])
@pytest.mark.parametrize("container", list(_AUTH_CONTAINERS))
@pytest.mark.parametrize("credential", list(_AUTH_CREDENTIALS))
@pytest.mark.parametrize(
    "scheme", ["Basic", "Bearer", "Digest", "AWS4-HMAC-SHA256", "Negotiate", "Acme-Auth.v2"]
)
@pytest.mark.parametrize("header", ["Authorization", "Proxy-Authorization", "authorization"])
def test_authorization_shape_matrix_masks_the_whole_value(
    header, scheme, credential, container, path
):
    line = f"{header}: {scheme} {_AUTH_CREDENTIALS[credential]}"
    output, masked = _render_through(path, _AUTH_CONTAINERS[container](line))
    assert "SECRET-" not in output
    assert redact(masked) == masked
    if container == "json-dumps":
        assert json.loads(masked) == {"headers": f"{header}: ***", "next": "ok"}
    elif container == "repr":
        assert ast.literal_eval(masked) == {"headers": f"{header}: ***", "next": "ok"}
    else:
        assert masked == f"{header}: ***"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A quote that cannot close the string holding the header does not end the value.
        (
            'bad header: "Authorization: Digest realm="x", response="SECRET-Q1""',
            'bad header: "Authorization: ***',
        ),
        (
            "it's 'Authorization: Digest username*=UTF-8''J, response=SECRET-Q2' ok",
            "it's 'Authorization: ***",
        ),
        ('Authorization: "Digest x", response="SECRET-Q3"', "Authorization: ***"),
        ("Req(authorization='Bearer SECRET-Q4', n=1)", "Req(authorization=***"),
        ("{'Authorization': None, 'n': 1}", "{'Authorization': ***"),
        # Folded continuation lines belong to the value; a lone "\r" does not end it.
        (
            'Authorization: Digest username="Mufasa",\r\n       response="SECRET-Q8"\r\nHost: x',
            "Authorization: ***\r\nHost: x",
        ),
        ("Authorization: Bearer x\rSECRET-Q9 tail\nnext", "Authorization: ***\nnext"),
        # A JSON or repr string holding the header ends at its closing quote.
        ("Req(h='Authorization: Bearer SECRET-Q5', n=1)", "Req(h='Authorization: ***', n=1)"),
        (json.dumps(["Authorization: Bearer SECRET-Q6", "ok"]), '["Authorization: ***", "ok"]'),
        (repr(("Authorization: Bearer SECRET-Q10", "ok")), "('Authorization: ***', 'ok')"),
        (
            json.dumps({"Authorization": 'Digest response="SECRET-Q7"', "n": 1}),
            '{"Authorization": "***", "n": 1}',
        ),
        ('{"headers": "Authorization: ", "n": 1}', '{"headers": "Authorization: ", "n": 1}'),
    ],
)
def test_redact_ends_an_authorization_value_at_a_container_close_or_the_line_end(text, expected):
    assert redact(text) == expected
    assert redact(expected) == expected


def test_unformattable_arguments_never_reach_the_logging_error_handler():
    result = _probe(
        """
from aragora_verify._logging import configure_logging
import logging
configure_logging()
logging.getLogger("val").warning("api_key=%s retries=%d", "SECRET-XRAY-4", "many")
""",
        ARAGORA_LOG_FORMAT="json",
    )
    (line,) = result.stderr.splitlines()
    assert "unformattable log arguments: TypeError" in json.loads(line)["msg"]
    assert "SECRET-" not in result.stderr
    assert "Logging error" not in result.stderr


_STREAM_PROBE = """
import io
import logging
import sys
from aragora_verify._logging import JsonFormatter, configure_logging

class Unprintable:
    def __str__(self):
        raise RuntimeError("SECRET-ZULU-7 in the exception text")

    def __format__(self, spec):
        raise RuntimeError("SECRET-ZULU-7 in the exception text")

configure_logging()
(handler,) = logging.getLogger().handlers
assert isinstance(handler.formatter, JsonFormatter)
stream = io.StringIO()
handler.setStream(stream)
logging.getLogger("val").warning(CALL)
sys.stdout.write(stream.getvalue())
"""


@pytest.mark.parametrize(
    ("call", "error"),
    [
        ('"api_key=%s retries=%d", "SECRET-YANKEE-6", float("inf")', "OverflowError"),
        ('"api_key=%s detail=%s", "SECRET-YANKEE-6", Unprintable()', "RuntimeError"),
    ],
    ids=["overflow", "runtime-error"],
)
def test_json_stream_gets_one_redacted_line_whatever_interpolation_raises(call, error):
    result = _probe(_STREAM_PROBE.replace("CALL", call), ARAGORA_LOG_FORMAT="json")
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["msg"].startswith("api_key=*** ")
    assert f"[unformattable log arguments: {error}]" in data["msg"]
    assert data["format_error"] == error
    assert "SECRET-" not in result.stdout + result.stderr
    assert "Logging error" not in result.stderr
    assert not result.stderr


_WRITE_ERROR_PROBE = """
import io
import logging
from aragora_verify._logging import configure_logging

configure_logging()
(handler,) = logging.getLogger().handlers
handler.setStream(io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))
logging.getLogger("val").warning("api_key=%s note=%s", "SECRET-ZULU-6", "\\ud800")
"""


@pytest.mark.parametrize("format_name", ["json", "text"])
def test_a_failed_stream_write_reports_the_error_type_without_the_arguments(format_name):
    result = _probe(_WRITE_ERROR_PROBE, ARAGORA_LOG_FORMAT=format_name)
    assert "SECRET-" not in result.stdout + result.stderr
    assert result.stderr == "--- Logging error: UnicodeEncodeError writing a record from val ---\n"


@pytest.mark.parametrize("formatter", [JsonFormatter(), TextFormatter()], ids=["json", "text"])
@pytest.mark.parametrize(
    ("msg", "args", "error"),
    [
        ("api_key=%s retries=%d", ("SECRET-YANKEE-6", float("inf")), "OverflowError"),
        ("api_key=%s detail=%s", ("SECRET-YANKEE-6", _Unprintable()), "RuntimeError"),
    ],
    ids=["overflow", "runtime-error"],
)
def test_formatters_never_raise_whatever_interpolation_raises(formatter, msg, args, error):
    record = logging.LogRecord("val", logging.WARNING, "", 0, msg, args, None)
    line = formatter.format(record)
    assert isinstance(line, str)
    assert "SECRET-" not in line
    assert f"[unformattable log arguments: {error}]" in line
    if isinstance(formatter, JsonFormatter):
        assert json.loads(line)["format_error"] == error


def _record_failing_at(case):
    record = logging.LogRecord(
        "val", logging.WARNING, "", 0, "api_key=%(token)s", ({"token": "SECRET-YANKEE-6"},), None
    )
    if case == "extra-str":
        record.payload = _Unprintable()
    elif case == "message-object":
        record.msg = _Unprintable()
    elif case == "args-key":
        record.args = {_Unprintable(): 1, "token": "SECRET-YANKEE-6"}
    elif case == "exception-info":
        record.exc_info = (ValueError, "not an exception instance", None)
    elif case == "stack-info":
        record.stack_info = _Unprintable()
    elif case == "timestamp":
        record.created = float("inf")
    return record


@pytest.mark.parametrize(
    ("case", "text_format", "msg", "errors"),
    [
        pytest.param(
            "extra-str",
            "%(levelname)s %(payload)s: %(message)s",
            "api_key=***",
            ("RuntimeError", "RuntimeError"),
            id="extra-str",
        ),
        pytest.param(
            "message-object",
            None,
            "<_Unprintable message>",
            ("RuntimeError", "RuntimeError"),
            id="message-object",
        ),
        pytest.param(
            "args-key", None, "api_key=***", ("RuntimeError", "RuntimeError"), id="args-key"
        ),
        pytest.param(
            "exception-info",
            None,
            "api_key=***",
            ("AttributeError", "AttributeError"),
            id="exception-info",
        ),
        # JSON stringifies the stack via str(); the text formatter concatenates it.
        pytest.param(
            "stack-info", None, "api_key=***", ("RuntimeError", "TypeError"), id="stack-info"
        ),
        pytest.param(
            "timestamp",
            "%(asctime)s %(message)s",
            "api_key=***",
            ("OverflowError", "OverflowError"),
            id="timestamp",
        ),
    ],
)
@pytest.mark.parametrize("kind", ["json", "text"])
def test_formatters_write_the_redacted_template_when_any_other_step_raises(
    kind, case, text_format, msg, errors
):
    formatter = JsonFormatter() if kind == "json" else TextFormatter(text_format)
    line = formatter.format(_record_failing_at(case))
    assert "SECRET-" not in line
    data = json.loads(line)
    assert data["msg"] == msg
    assert (data["level"], data["logger"]) == ("WARNING", "val")
    assert data["format_error"] == errors[0 if kind == "json" else 1]


def test_redact_colon_forms_keep_their_shape():
    assert redact("Authorization: Bearer SECRET-HOTEL-444") == "Authorization: ***"
    assert json.loads(redact('{"api_key": "SECRET-GOLF-333", "model": "m"}')) == {
        "api_key": "***",
        "model": "m",
    }
    assert redact(str({"Authorization": "Bearer SECRET-JULIET-666"})) == "{'Authorization': '***'}"


def test_json_formatter_coerces_non_string_keys_without_logging_error():
    result = _probe(
        """
from aragora_verify._logging import configure_logging
import logging
configure_logging()
logging.getLogger("aragora_verify.val").warning(
    "probe", extra={"payload": {("tuple", "key"): "SECRET-INDIA-555"}}
)
""",
        ARAGORA_LOG_FORMAT="json",
    )
    (line,) = result.stderr.splitlines()
    assert json.loads(line)["payload"] == {"('tuple', 'key')": "***"}
    assert "SECRET-" not in result.stderr
    assert "Logging error" not in result.stderr


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
