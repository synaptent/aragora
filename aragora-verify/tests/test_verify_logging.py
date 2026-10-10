"""Logging is local, explicitly configured, and redacts placeholder secrets."""

import ast
import io
import json
import logging
import os
import random
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
    # Inside a JSON or repr string the value is masked to the end of the line.
    assert redact(json.dumps(plain)) == f'"{header}: ***'
    assert redact(json.dumps({"headers": plain})) == f'{{"headers": "{header}: ***'
    assert redact(str({"headers": plain})) == f"{{'headers': '{header}: ***"
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
    assert redact(json.dumps(line)) == '"Authorization: ***'
    assert redact(json.dumps({"headers": line})) == '{"headers": "Authorization: ***'


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


def _render_through(path, text, error=None):
    """Return the full output and the redacted text for one rendering path.

    The -formatter paths log text as the "%s" argument of a provider exception
    (error, if given); the -message and -extra paths log it as the message or as
    an extra field.
    """
    if path == "redact":
        masked = redact(text)
        return masked, masked
    kind, _, how = path.partition("-")
    text_format = "%(levelname)s %(name)s: %(message)s" + (" %(payload)s" if how == "extra" else "")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter() if kind == "json" else TextFormatter(text_format))
    logger = logging.getLogger("aragora_verify.tests.auth_matrix")
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        if how == "message":
            logger.warning(text)
        elif how == "extra":
            logger.warning("probe", extra={"payload": text})
        else:
            # The arena's failure path logs the provider exception through "%s".
            logger.warning(_PROPOSAL_FAILED + "%s", error or RuntimeError(text))
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert output.endswith("\n")
    if kind == "json":
        assert "\n" not in output[:-1]
        data = json.loads(output)
        message = data["payload"] if how == "extra" else data["msg"]
    else:
        message = output[:-1].removeprefix(f"WARNING {logger.name}: ")
        if how == "extra":
            message = message.removeprefix("probe ")
    if how == "formatter":
        assert message.startswith(_PROPOSAL_FAILED)
        message = message[len(_PROPOSAL_FAILED) :]
    return output, message


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
    text = _AUTH_CONTAINERS[container](line)
    output, masked = _render_through(path, text)
    assert "SECRET-" not in output
    assert redact(masked) == masked
    # Inside a JSON or repr string the mask runs past the closing quote to the line end.
    assert masked == text[: text.index(header)] + f"{header}: ***"


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
        # The closing quote of a JSON or repr string holding the header does not end it.
        ("Req(h='Authorization: Bearer SECRET-Q5', n=1)", "Req(h='Authorization: ***"),
        (json.dumps(["Authorization: Bearer SECRET-Q6", "ok"]), '["Authorization: ***'),
        (repr(("Authorization: Bearer SECRET-Q10", "ok")), "('Authorization: ***"),
        ('{"headers": "Authorization: ", "n": 1}', '{"headers": "Authorization: ***'),
        # Only a quoted key with a quoted value masks just that string.
        (
            json.dumps({"Authorization": 'Digest response="SECRET-Q7"', "n": 1}),
            '{"Authorization": "***", "n": 1}',
        ),
        # Another secret's value that runs into the header name is masked to the line end.
        (
            repr({"raw": "token: SECRET-Q11\r\nAuthorization: Bearer SECRET-Q12"}),
            "{'raw': 'token: ***",
        ),
        (
            repr({"n": 'secret="SECRET-Q13', "h": "Authorization: " + _DIGEST}),
            "{'n': 'secret=***",
        ),
        (
            "x-api-key=SECRET-Q14xProxy-Authorization: Bearer SECRET-Q15\nnext",
            "x-api-key=***\nnext",
        ),
        # So is one whose quoted value ends at the quote that opens the header name.
        (
            repr({"url": "/x?access_token=", "Authorization": "Bearer SECRET-Q16", "n": 1}),
            "{'url': '/x?access_token=***",
        ),
        (
            json.dumps({"url": "/x?token=", "Authorization": "Bearer SECRET-Q17"}, indent=2),
            '{\n  "url": "/x?token=***\n}',
        ),
    ],
)
def test_redact_ends_an_authorization_value_at_the_line_end(text, expected):
    assert redact(text) == expected
    assert redact(expected) == expected


_R3_DIGEST = 'Digest realm=", private", response="SECRET-R3-RESPONSE"'
_LOG_PATHS = [
    "redact",
    "text-message",
    "text-formatter",
    "text-extra",
    "json-message",
    "json-formatter",
    "json-extra",
]


def _rendered(payload, render):
    """The text logging receives for payload, and the exception the arena would log."""
    if render == "repr":
        return repr(payload), RuntimeError(payload)
    text = json.dumps(payload, default=repr)
    return text, RuntimeError(text)


def _assert_masked_from_the_header(text, masked, header):
    """Text before the header name stays; everything after it on the line is masked."""
    start = text.index(header)
    assert masked == redact(text[:start]) + f"{header}: ***"


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("render", ["repr", "json.dumps"])
@pytest.mark.parametrize("header", ["Authorization", "Proxy-Authorization"])
def test_a_quote_swallowed_by_an_earlier_secret_does_not_end_the_header_value(header, render, path):
    # The bare password value swallows the quote that closes its repr string.
    payload = {
        "note": "password=SECRET-NOTE-O'Brien",
        "headers": f"{header}: {_R3_DIGEST}",
        "next": "ok",
    }
    text, error = _rendered(payload, render)
    output, masked = _render_through(path, text, error)
    assert "SECRET-" not in output
    assert redact(masked) == masked
    _assert_masked_from_the_header(text, masked, header)


@pytest.mark.parametrize("path", ["redact", "text-formatter", "json-formatter"])
@pytest.mark.parametrize("render", ["repr", "json.dumps"])
@pytest.mark.parametrize("header", ["Authorization", "Proxy-Authorization"])
@pytest.mark.parametrize(
    "note",
    [
        "token=SECRET-NOTE-O'Brien",
        "api_key=SECRET-NOTE-O'Brien",
        "secret=SECRET-NOTE-O'Brien",
        "token: Bearer SECRET-NOTE-X'",
        "api_key=Bearer SECRET-NOTE-X'",
    ],
)
def test_any_secret_value_that_swallows_a_quote_leaves_the_header_masked(
    note, header, render, path
):
    payload = {"note": note, "headers": f"{header}: {_R3_DIGEST}", "next": "ok"}
    text, error = _rendered(payload, render)
    output, masked = _render_through(path, text, error)
    assert "SECRET-" not in output
    assert redact(masked) == masked
    _assert_masked_from_the_header(text, masked, header)


@pytest.mark.parametrize("path", ["redact", "text-formatter", "json-formatter"])
@pytest.mark.parametrize("header", ["Authorization", "Proxy-Authorization"])
@pytest.mark.parametrize("shape", ["bytes-prefix-list", "hand-quoted"])
def test_quotes_before_the_header_do_not_end_its_value(shape, header, path):
    if shape == "bytes-prefix-list":
        text = repr([b', "', f'{header}: Digest realm=", x", response="SECRET-B1"', "ok"])
    else:
        text = f'note: "{header}: Digest realm=":", response="SECRET-X"'
    output, masked = _render_through(path, text)
    assert "SECRET-" not in output
    assert redact(masked) == masked
    _assert_masked_from_the_header(text, masked, header)


@pytest.mark.parametrize("path", ["redact", "text-formatter", "json-formatter"])
@pytest.mark.parametrize("render", ["repr", "json.dumps"])
@pytest.mark.parametrize(
    "payload",
    [
        {"raw": "token: SECRET-H1\r\nAuthorization: Bearer SECRET-H2", "n": 1},
        {"raw": b'api_key=SECRET-H3\nProxy-Authorization: Digest response="SECRET-H4"'},
        {"note": 'token="SECRET-H5', "headers": f"Authorization: {_R3_DIGEST}"},
        {"note": "secret=SECRET-H6xProxy-Authorization: Negotiate SECRET-H7", "n": 1},
    ],
    ids=["crlf", "bytes", "unclosed-quote", "adjacent"],
)
def test_a_header_inside_another_secret_value_is_masked_to_the_line_end(payload, render, path):
    text, error = _rendered(payload, render)
    output, masked = _render_through(path, text, error)
    assert "SECRET-" not in output
    assert redact(masked) == masked


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("render", ["repr", "json.dumps"])
@pytest.mark.parametrize(
    "payload",
    [
        {"url": "https://api.example/x?access_token=", "Authorization": "Bearer SECRET-K1"},
        {"hint": "expected password: ", "Proxy-Authorization": "Basic SECRET-K2"},
        {"note": "missing token=", "authorization": ["Bearer SECRET-K3"]},
        {"note": "api_key:", "Authorization": 'Digest username="u", response="SECRET-K4"'},
        [{"a": "secret="}, {"Proxy-Authorization": b"Negotiate SECRET-K5"}],
        {"note": "token=", "n": 1, "X-Forwarded-Authorization": "Bearer SECRET-K6"},
    ],
    ids=["url", "password", "list-value", "digest", "nested-bytes", "between"],
)
def test_a_secret_value_ending_at_the_header_key_quote_leaves_the_header_masked(
    payload, render, path
):
    # An empty secret value lets the quoted-value match run from the quote closing its
    # string to the quote opening the header key, which leaves the key unrecognised.
    text, error = _rendered(payload, render)
    output, masked = _render_through(path, text, error)
    assert "SECRET-" not in output
    assert redact(masked) == masked


_SCHEMES = ("Basic", "Bearer", "Digest", "AWS4-HMAC-SHA256", "Negotiate", "X-Vendor.v1")
_HEADER_NAMES = ("Authorization", "Proxy-Authorization", "authorization", "PROXY-AUTHORIZATION")
_SECRET_KEYS = ("password", "token", "api_key", "secret", "access_token", "X-Api-Key")
_NOISE = ("'", '"', "\\", ",", "=", ", ", "O'Brien", 'say "hi"', "a=b", "x")
_AUTH_PARAMS = ("realm", "nonce", "response", "username*", "Credential", "Signature", "opaque")


class _LogPayloads:
    """Seeded dicts of the shapes logs receive; every synthetic secret contains SECRET-."""

    def __init__(self, seed):
        self.random = random.Random(seed)
        self.count = 0

    def secret(self):
        self.count += 1
        return f"SECRET-G{self.count}"

    def noise(self):
        return "".join(self.random.choice(_NOISE) for _ in range(self.random.randint(0, 3)))

    def assignment(self):
        """A key=SECRET-... fragment whose value may swallow a quote that follows it."""
        value = self.random.choice(
            (
                self.secret() + self.random.choice(_NOISE),
                "Bearer " + self.secret() + self.random.choice(("", "'", '"')),
                f'"{self.secret()} quoted"',
                f"'{self.secret()} quoted'",
            )
        )
        separator = self.random.choice(("=", ": ", ":"))
        return f"{self.random.choice(_SECRET_KEYS)}{separator}{value}"

    def credential(self, scheme):
        if scheme in ("Basic", "Bearer", "Negotiate") and self.random.random() < 0.8:
            return self.secret() + self.random.choice(("", "==", "+/9"))
        params = []
        for name in self.random.sample(_AUTH_PARAMS, self.random.randint(1, 4)):
            if self.random.random() < 0.5:
                params.append(f"{name}={self.secret()}" + self.random.choice(("", "/s3", "'")))
                continue
            inner = self.noise() + self.secret() + self.noise()
            if self.random.random() < 0.7:
                inner = inner.replace("\\", "\\\\").replace('"', '\\"')
            params.append(f'{name}="{inner}"')
        return self.random.choice((", ", ",", ",\r\n ")).join(params)

    def text(self):
        pieces = [self.random.choice((self.assignment, self.noise))() for _ in range(3)]
        return self.random.choice((" ", ", ", "; ")).join(pieces)

    def header_text(self, scheme):
        before = ""
        if self.random.random() < 0.7:
            before = self.text() + self.random.choice((" ", ", ", "\n", "\r\n", ""))
        separator = self.random.choice((": ", ":", "="))
        header = f"{self.random.choice(_HEADER_NAMES)}{separator}{scheme} {self.credential(scheme)}"
        after = self.random.choice(("", " (retrying)", "\r\nHost: x", ", " + self.assignment()))
        return before + header + after

    def value(self, depth=0):
        roll = self.random.random()
        if roll < 0.2 and depth < 2:
            items = [self.value(depth + 1) for _ in range(self.random.randint(1, 3))]
            return items if self.random.random() < 0.5 else tuple(items)
        if roll < 0.3:
            return self.text().encode()
        if roll < 0.35:
            return self.random.choice((None, 7, 2.5, True))
        return self.text()

    def payload(self, index):
        scheme = _SCHEMES[index % len(_SCHEMES)]
        entries = [(f"n{n}", self.value()) for n in range(self.random.randint(1, 4))]
        header = self.header_text(scheme)
        shape = self.random.randrange(4)
        if shape == 0:
            entry = ("headers", header)
        elif shape == 1:
            entry = ("raw", header.encode())
        elif shape == 2:
            entry = ("items", [self.value(1), (header, self.value(1))])
        else:
            entry = (self.random.choice(_HEADER_NAMES), f"{scheme} {self.credential(scheme)}")
        position = self.random.randint(0, len(entries))
        if shape == 3 and position and self.random.random() < 0.5:
            # An empty secret value just before the header key: its quoted-value match
            # runs from the quote closing that string to the quote opening the key.
            key = self.random.choice(_SECRET_KEYS) + self.random.choice(("=", ": ", ":"))
            entries[position - 1] = (entries[position - 1][0], f"{self.text()} {key}")
        entries.insert(position, entry)
        return dict(entries)


_GENERATED_PER_SEED = 600


@pytest.mark.parametrize("seed", [208, 10539, 20261010, 31337])
def test_seeded_repr_and_json_payloads_never_leak_through_any_path(seed):
    generator = _LogPayloads(seed)
    streams = {"text": io.StringIO(), "json": io.StringIO()}
    logger = logging.getLogger(f"aragora_verify.tests.generated.{seed}")
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    handlers = [logging.StreamHandler(stream) for stream in streams.values()]
    handlers[0].setFormatter(TextFormatter("%(levelname)s %(name)s: %(message)s"))
    handlers[1].setFormatter(JsonFormatter())
    for handler in handlers:
        logger.addHandler(handler)
    try:
        for index in range(_GENERATED_PER_SEED):
            payload = generator.payload(index)
            for render in ("repr", "json.dumps"):
                text, error = _rendered(payload, render)
                for stream in streams.values():
                    stream.seek(0)
                    stream.truncate()
                logger.warning(_PROPOSAL_FAILED + "%s", error)
                line = streams["json"].getvalue()
                assert line.endswith("\n") and "\n" not in line[:-1]
                assert json.loads(line)["msg"].startswith(_PROPOSAL_FAILED)
                masked = redact(text)
                output = masked + streams["text"].getvalue() + line
                assert "SECRET-" not in output, (seed, index, render, text)
                assert redact(masked) == masked, (seed, index, render, text)
    finally:
        for handler in handlers:
            logger.removeHandler(handler)
    assert generator.count > _GENERATED_PER_SEED


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
