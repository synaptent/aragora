"""The logging entry point is explicit and secrets never reach its formatters."""

import ast
from collections import OrderedDict, namedtuple
import io
import json
import logging
import os
from pathlib import Path
import pprint
import random
import subprocess
import sys
import time
from types import SimpleNamespace

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


class _Unprintable:
    """An argument whose conversion to text raises something other than TypeError."""

    def __str__(self):
        raise RuntimeError("SECRET-ZULU-7 in the exception text")

    def __format__(self, spec):
        raise RuntimeError("SECRET-ZULU-7 in the exception text")


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


@pytest.mark.parametrize(
    "value",
    [
        ["Authorization: Bearer SECRET-FOXTROT-222"],
        '{"api_key": "SECRET-GOLF-333"}',
        "Authorization: Bearer SECRET-HOTEL-444",
        str({"Authorization": "Bearer SECRET-JULIET-666"}),
        "authorization:Basic SECRET-KILO-777",
        "x-api-key: SECRET-LIMA-888",
        "{'password': 'SECRET-MIKE-999 with spaces'}",
        '"token" = "SECRET-NOVEMBER-000"',
        'headers={"Authorization": "Basic SECRET-OSCAR-111"}',
        "Authorization: Token SECRET-PAPA-222",
        "proxy-authorization=Digest SECRET-QUEBEC-333",
        "Authorization: AWS4-HMAC-SHA256 Credential=SECRET-ROMEO-444/s3, Signature=SECRET-SIERRA-5",
    ],
)
def test_redact_colon_and_quoted_key_forms(value):
    assert "SECRET-" not in json.dumps(redact(value), default=str)


def test_redact_masks_the_whole_authorization_value_for_any_scheme():
    assert redact("Authorization: Token SECRET-PAPA-222 sent") == "Authorization: ***"
    assert redact("Authorization: ApiKey SECRET-UNIFORM-1, Accept: json\nnext line") == (
        "Authorization: ***\nnext line"
    )
    assert redact("token: Bearer SECRET-VICTOR-2 ok") == "token: *** ok"


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
    logger = logging.getLogger("aragora_debate.tests.auth_matrix")
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


# Further producers of the text a log call receives for a payload.
_PRODUCERS = {
    "double-json": lambda payload: json.dumps(json.dumps(payload, default=repr)),
    "exception-repr": lambda payload: repr(RuntimeError(payload)),
    "json-indent-0": lambda payload: json.dumps(payload, default=repr, indent=0),
    "json-indent-2": lambda payload: json.dumps(payload, default=repr, indent=2),
    "ordered-dict-repr": lambda payload: repr(OrderedDict(payload)),
    "item-tuples": lambda payload: str(list(payload.items())),
}


def _rendered(payload, render):
    """The text logging receives for payload, and the exception the arena would log."""
    if render == "repr":
        return repr(payload), RuntimeError(payload)
    if render in _PRODUCERS:
        text = _PRODUCERS[render](payload)
        return text, RuntimeError(text)
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
    logger = logging.getLogger(f"aragora_debate.tests.generated.{seed}")
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
            for render in ("repr", "json.dumps", *_PRODUCERS):
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


_HEADERS = ("Authorization", "Proxy-Authorization")


def _assert_never_leaks(text, path, error=None):
    """Render text through path: no synthetic secret survives and redact() is stable."""
    output, masked = _render_through(path, text, error)
    assert "SECRET-" not in output
    assert redact(masked) == masked
    return masked


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("header", _HEADERS)
@pytest.mark.parametrize(
    "produce",
    [
        lambda header: str({"msg": json.dumps({header: _DIGEST})}),
        lambda header: repr(RuntimeError(json.dumps({header: _DIGEST, "n": 1}))),
        lambda header: str([json.dumps({"n": 1, header: _DIGEST}), "ok"]),
        lambda header: repr({"body": json.dumps({header: 'Bearer SECRET-ESCV-1 "x"', "n": 1})}),
    ],
    ids=["dict-repr", "exception-repr", "list-repr", "bearer-with-quote"],
)
def test_an_escaped_authorization_value_inside_a_repr_string_is_masked_to_the_line_end(
    produce, header, path
):
    # json.dumps() escapes the quotes inside the value and repr() escapes those
    # backslashes again, so the value's closing quote cannot be trusted.
    masked = _assert_never_leaks(produce(header), path)
    assert masked.endswith(f'"{header}": ***')


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "key",
    [
        "authorization_token",
        "X-Authorization-Secret",
        "proxy_authorization_key",
        "Authorization-Password",
    ],
)
@pytest.mark.parametrize("separator", [": ", "=", " = "])
def test_authorization_anywhere_in_a_key_masks_its_value_to_the_line_end(key, separator, path):
    text = f'{key}{separator}Digest username="Jane Doe", response="SECRET-AK-1"'
    assert _assert_never_leaks(text, path) == f"{key}{separator}***"


_PAIR_PRODUCERS = {
    "header-list": lambda name, value: str([(name, value)]),
    "bytes-header-list": lambda name, value: str([(name.lower().encode(), value.encode())]),
    "exception-args": lambda name, value: str(RuntimeError(name, value)),
    "exception-repr": lambda name, value: repr(RuntimeError(name, value)),
    "nested-tuple": lambda name, value: str(((name, value),)),
    "ordered-dict": lambda name, value: repr(OrderedDict([("Accept", "*/*"), (name, value)])),
    "dict-items": lambda name, value: str(list({"n": "1", name: value}.items())),
    "har-json": lambda name, value: json.dumps([{"name": name, "value": value}]),
    "har-repr": lambda name, value: repr(
        [{"name": "Cookie", "value": "x"}, {"name": name.lower(), "value": value}]
    ),
    "har-indent": lambda name, value: json.dumps(
        {"headers": [{"name": name, "value": value}]}, indent=2
    ),
}


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "name", ["Authorization", "Proxy-Authorization", "X-Api-Key", "access_token"]
)
@pytest.mark.parametrize("producer", list(_PAIR_PRODUCERS))
def test_header_tuples_ordered_dicts_and_har_entries_mask_the_value(producer, name, path):
    text = _PAIR_PRODUCERS[producer](name, "Bearer SECRET-PAIR-1, realm=SECRET-PAIR-2")
    masked = _assert_never_leaks(text, path)
    # The name stays; the value and the rest of its line are masked.
    assert name.lower() in masked.lower()
    assert "***" in masked


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "name", ["Authorization", "Proxy-Authorization", "X-Api-Key", "access_token"]
)
@pytest.mark.parametrize("indent", [None, 0, 2], ids=["single-line", "indent-0", "indent-2"])
@pytest.mark.parametrize(
    "fields",
    [{"comment": "x"}, {"comment": "rotated, see ticket", "size": 7}, {"httpOnly": False}],
    ids=["comment", "two-fields", "flag"],
)
def test_a_har_entry_with_fields_between_name_and_value_masks_the_value(fields, indent, name, path):
    entry = {"name": name, **fields, "value": "Bearer SECRET-HARF-1"}
    _assert_never_leaks(json.dumps(entry, indent=indent), path)
    _assert_never_leaks(json.dumps({"headers": [entry], "n": 1}, indent=indent), path)
    _assert_never_leaks(repr([entry]), path)


def test_a_har_value_after_another_field_is_masked_to_the_end_of_its_line():
    entry = {"name": "Authorization", "comment": "x", "value": "Bearer SECRET-HARF-2"}
    assert redact(json.dumps(entry, indent=0)) == '{\n"name": "Authorization",\n***\n}'


# Text in the fields between a HAR entry's name and its value: quoted brackets, escaped
# quotes, commas, colons and a decoy value field.
_HAR_FIELD_TEXTS = [
    "}",
    "]",
    "{",
    "[",
    'say "}" now',
    'it\'s "]" {x}',
    "a, b: c",
    '}, "value": "decoy"',
]
_HAR_FIELDS = {
    "one-field": lambda text: {"comment": text},
    "several-fields": lambda text: {"comment": text, "size": 7, "other": text + "]"},
    "nested-fields": lambda text: {"comment": [text, {"k": text}], "other": {"v": [text]}},
}
_HAR_LAYOUTS = {
    "single-line": json.dumps,
    "indent-0": lambda payload: json.dumps(payload, indent=0),
    "indent-2": lambda payload: json.dumps(payload, indent=2),
    "indent-4": lambda payload: json.dumps(payload, indent=4),
    "repr": repr,
    "pprint": lambda payload: pprint.pformat(payload, width=40),
}


def _har_payload(entry, wrap):
    if wrap == "standalone":
        return entry
    other = {"name": "Accept", "value": "*/*"}
    request, response = (
        ([entry, other], [other]) if wrap == "request" else ([other], [other, entry])
    )
    return {
        "log": {"entries": [{"request": {"headers": request}, "response": {"headers": response}}]}
    }


@pytest.mark.parametrize("path", _LOG_PATHS)
def test_a_har_value_after_a_field_holding_a_quoted_brace_is_masked(path):
    text = json.dumps(
        {"name": "Authorization", "comment": "}", "value": "Bearer SECRET-F3"}, indent=0
    )
    assert _assert_never_leaks(text, path) == '{\n"name": "Authorization",\n***\n}'


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("name", _HEADERS)
@pytest.mark.parametrize("wrap", ["standalone", "request", "response"])
def test_har_fields_holding_quoted_brackets_never_hide_the_value(wrap, name, path):
    failures = []
    for fields, make in _HAR_FIELDS.items():
        for field_text in _HAR_FIELD_TEXTS:
            entry = {"name": name, **make(field_text), "value": "Bearer SECRET-HAR3-1"}
            for layout, render in _HAR_LAYOUTS.items():
                text = render(_har_payload(entry, wrap))
                output, masked = _render_through(path, text)
                if "SECRET-" in output or redact(masked) != masked or masked != redact(text):
                    failures.append((fields, field_text, layout))
    assert not failures


def test_a_har_mask_ends_at_the_line_that_closes_the_entry():
    entries = [
        {"name": "Authorization", "comment": ["}", {"k": "]"}], "value": "Bearer SECRET-HAR3-2"},
        {"name": "Accept", "value": "*/*"},
    ]
    assert redact(json.dumps(entries, indent=0)) == (
        '[\n{\n"name": "Authorization",\n***\n},\n{\n"name": "Accept",\n"value": "*/*"\n}\n]'
    )


@pytest.mark.parametrize("render", [json.dumps, repr], ids=["json", "repr"])
def test_a_single_line_har_entry_is_masked_to_the_end_of_its_line(render):
    entry = {"name": "Authorization", "comment": "}", "value": "Bearer SECRET-HAR3-3"}
    quote = '"' if render is json.dumps else "'"
    expected = f"[{{{quote}name{quote}: {quote}Authorization{quote}, ***\nnext line"
    assert redact(render([entry]) + "\nnext line") == expected


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("layout", list(_HAR_LAYOUTS))
def test_a_har_entry_for_another_header_with_quoted_brackets_stays_unchanged(layout, path):
    entry = {"name": "Accept", "comment": "}", "other": ["]", {"k": "{"}], "value": "x, y: [z"}
    text = _HAR_LAYOUTS[layout](_har_payload(entry, "request"))
    output, masked = _render_through(path, text)
    assert masked == text


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "text",
    [
        '{"name": "Authorization", "comment": "x"\n, "value": "Bearer SECRET-HW-1"}',
        '{"name": "Authorization", "comment": "}"\n, "value": "Bearer SECRET-HW-2"}',
        '{ "name": "Authorization"\n, "comment": "}"\n, "value": "Bearer SECRET-HW-3"\n}',
        '{"name": "Authorization", "comment": "}",\n"value": "Bearer SECRET-HW-4"}\nnext',
        '"name": "Authorization", "c": "x"\n"value": "Bearer SECRET-HW-5"',
        '{\n"name": "Authorization",\n"c": ["x",\n"y"\n],\n"value": "Bearer SECRET-HW-6"\n}',
        '{\n"name": "Authorization",\n"c": ["}",\n"y"\n],\n"value": "Bearer SECRET-HW-7"\n}',
        '  "name": "Authorization",\n  "c": "x",\n  }\n  more\nplain\n"value": "SECRET-HW-8"\n}',
        '{\r\n"name": "Authorization",\r\n"comment": "}",\r\n"value": "Bearer SECRET-HW-9"\r\n}',
        '{"name": "Authorization", "c": "x", "value": "Bearer SECRET-HW-10"}\n"c": 1\n'
        '"value": "Bearer SECRET-HW-11"',
        '{"name": "Authorization", "c": "x", "value": "Bearer SECRET-HW-12"}\n "c": null\n'
        ', "c": 1\n"value": "Bearer SECRET-HW-13"\n]',
        '{\n"name": "Authorization",\n"name": "Proxy-Authorization",\n],\n"c": 1,\n'
        '"value": "Bearer SECRET-HW-14"\n}',
    ],
    ids=[
        "comma-first-value",
        "comma-first-value-after-quoted-brace",
        "comma-first-fields",
        "fields-wrapped-after-a-comma",
        "value-on-the-next-line",
        "list-opened-inside-a-line",
        "list-opened-inside-a-line-holding-a-quoted-brace",
        "indented-closer-then-unindented-text",
        "crlf-lines",
        "value-field-after-a-one-line-entry",
        "comma-first-line-after-a-one-line-entry",
        "name-before-the-closing-line",
    ],
)
def test_hand_written_har_layouts_mask_the_value_and_stay_stable(text, path):
    _assert_never_leaks(text, path)


@pytest.mark.parametrize(
    "text",
    [
        '{\n"name": "Authorization",\n"comment": "}",\n"value": "Bearer SECRET-LIN-2"\n},\n'
        * 2_000,
        '"name": "Authorization",\n' + "[\n" * 20_000 + "token=SECRET-LIN-3",
        '"name": "Authorization",\n}\n' * 8_000,
        '{"name": "Authorization", "c": "}",\n}\n' * 6_000,
        '("Authorization",\n' * 8_000,
        '"name": "Authorization", ' + ", " * 20_000,
        ' "name": "Authorization",\n' + " ]\nx\n" * 20_000 + '"value": "SECRET-LIN-4"',
        '"name": "Authorization",\n' + ']\n"value": "SECRET-LIN-5",\n' * 10_000,
    ],
    ids=[
        "entries-at-indent-0",
        "open-bracket-lines",
        "closed-name-lines",
        "continued-name-lines",
        "tuple-name-lines",
        "long-name-line",
        "indented-closer-lines",
        "closer-then-value-lines",
    ],
)
def test_har_entry_scans_take_linear_time(text):
    started = time.perf_counter()
    masked = redact(text)
    assert time.perf_counter() - started < 5
    # A count keeps a failure report from diffing the whole text.
    assert masked.count("SECRET-") == 0


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("header", _HEADERS)
@pytest.mark.parametrize(
    ("template", "kept"),
    [
        ("{h} header: Bearer SECRET-PH-1", "{h} header: "),
        ('invalid {h} header: Digest realm="r", response="SECRET-PH-2"', "invalid {h} header: "),
        ("{h} header was Bearer SECRET-PH-3", "{h} header was "),
        ("{h} value = Bearer SECRET-PH-4", "{h} value = "),
        ("{h} credentials: Basic SECRET-PH-5 (retrying)", "{h} credentials: "),
        ("rejected {h} field=Negotiate SECRET-PH-6", "rejected {h} field="),
        ('sent {h} using Digest response="SECRET-PH-7"', "sent {h} using "),
        ("{h} still DPoP SECRET-PH-8, n=1", "{h} still "),
        ("{h} for the upstream call carried AWS4-HMAC-SHA256 SECRET-PH-9", None),
    ],
)
def test_authorization_phrasing_masks_the_value_to_the_line_end(template, kept, header, path):
    text = template.format(h=header)
    masked = _assert_never_leaks(text, path)
    if kept is None:
        kept = text[: text.index("AWS4")]
    assert masked == kept.format(h=header) + "***"


# Producers of the text a log call receives for one string.
_STRING_PRODUCERS = {
    "plain": lambda text: text,
    "exception-repr": lambda text: repr(RuntimeError(text)),
    "dict-repr": lambda text: repr({"msg": text}),
    "json": lambda text: json.dumps({"msg": text}),
}


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("header", _HEADERS)
@pytest.mark.parametrize(
    "space", ["\t", "\n", "\r", "\x0b", "\xa0"], ids=["tab", "lf", "cr", "vt", "nbsp"]
)
@pytest.mark.parametrize("producer", ["exception-repr", "dict-repr", "json"])
@pytest.mark.parametrize(
    "template",
    [
        "{h} was{s}Bearer SECRET-ESP-1",
        "{h}{s}Basic SECRET-ESP-2",
        "{h} header was Digest{s}SECRET-ESP-3",
    ],
    ids=["before-scheme", "after-name", "after-scheme"],
)
def test_an_escaped_space_around_an_auth_scheme_masks_the_credential(
    template, producer, space, header, path
):
    text = _STRING_PRODUCERS[producer](template.format(h=header, s=space))
    # repr() and json.dumps() write the space as an escape sequence.
    assert space not in text
    _assert_never_leaks(text, path)


@pytest.mark.parametrize("producer", ["exception-repr", "dict-repr", "json"])
@pytest.mark.parametrize(
    "scheme",
    [
        "Basic",
        "Bearer",
        "Digest",
        "Negotiate",
        "NTLM",
        "Token",
        "ApiKey",
        "AWS4-HMAC-SHA256",
        "HOBA",
        "Mutual",
        "SCRAM-SHA-1",
        "SCRAM-SHA-256",
        "vapid",
        "DPoP",
        "OAuth",
    ],
)
def test_every_auth_scheme_between_escaped_tabs_masks_the_credential(scheme, producer):
    text = _STRING_PRODUCERS[producer](f"Proxy-Authorization was\t{scheme}\tSECRET-ESP-4")
    masked = redact(text)
    assert "SECRET-" not in masked
    assert redact(masked) == masked


def test_an_escaped_tab_before_the_scheme_keeps_the_text_before_it():
    text = repr(RuntimeError("Authorization was\tBearer SECRET-ESP-5"))
    assert redact(text) == "RuntimeError('Authorization was\\t***"


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("header", _HEADERS)
@pytest.mark.parametrize(
    "produce",
    [
        lambda header: json.dumps(json.dumps({header: "Bearer SECRET-ESC-1"})),
        lambda header: json.dumps(json.dumps(json.dumps({header: "Negotiate SECRET-ESC-2"}))),
        lambda header: repr("{'%s': 'Basic SECRET-ESC-3', \"x\": 1}" % header),
        lambda header: json.dumps(
            {"e": RuntimeError(json.dumps({header: "Bearer SECRET-ESC-4"}))}, default=repr
        ),
        lambda header: repr(
            RuntimeError(f"upstream rejected request with headers { ({header: _DIGEST}) }")
        ),
        lambda header: str([RuntimeError(f"upstream rejected { ({header: _DIGEST}) }")]),
    ],
    ids=[
        "double-json",
        "triple-json",
        "repr-of-str",
        "json-default-repr",
        "exception-repr",
        "list",
    ],
)
def test_escaped_key_quotes_mask_an_authorization_value_to_the_line_end(produce, header, path):
    masked = _assert_never_leaks(produce(header), path)
    assert header in masked
    assert masked.endswith("***")


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("key", ["api_key", "token", "password", "client_secret"])
@pytest.mark.parametrize(
    "produce",
    [
        lambda key: json.dumps(json.dumps({key: "SECRET-ESK-1 two words", "n": 1})),
        lambda key: json.dumps(json.dumps(json.dumps({key: "SECRET-ESK-2"}))),
        lambda key: repr("{'%s': 'SECRET-ESK-3', \"x\": 1}" % key),
        lambda key: json.dumps(
            {"e": RuntimeError(json.dumps({key: "SECRET-ESK-4"}))}, default=repr
        ),
    ],
    ids=["double-json", "triple-json", "repr-of-str", "json-default-repr"],
)
def test_escaped_key_quotes_mask_any_secret_value_to_the_line_end(produce, key, path):
    masked = _assert_never_leaks(produce(key), path)
    assert key in masked
    assert masked.endswith("***")


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("key", ["Authorization", "Proxy-Authorization", "api_key", "password"])
@pytest.mark.parametrize("width", [40, 60])
def test_pprint_literals_that_continue_a_value_are_masked(key, width, path):
    value = "Bearer " + " ".join(f"SECRET-PP-{n}" for n in range(8))
    text = pprint.pformat({key: value, "n": 1}, width=width)
    assert text.count("\n") > 2
    _assert_never_leaks(text, path)


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("header", _HEADERS)
@pytest.mark.parametrize(
    "template",
    [
        "n='token=', '{h}': 'SECRET-LF-1' password=\"SECRET-LF-2\nSECRET-LF-3\"",
        "{h}: Bearer SECRET-LF-4 token='SECRET-LF-5\nSECRET-LF-6' tail",
        '{h} header was Bearer SECRET-LF-7 api_key="a\nSECRET-LF-8"',
    ],
)
def test_a_secret_value_running_past_a_masked_line_end_is_masked(template, header, path):
    masked = _assert_never_leaks(template.format(h=header), path)
    assert masked.endswith("***")


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "key",
    [
        "http.request.header.authorization",
        "http.request.header.proxy-authorization",
        " Authorization",
        "Proxy Authorization",
        "header:authorization",
        "Authorization.value",
        "user.password",
        " api_key",
        "x:token",
    ],
)
@pytest.mark.parametrize(
    "produce",
    [
        lambda key: repr({key: ["Bearer SECRET-KEY-1"], "n": 1}),
        lambda key: repr({key: "Bearer SECRET-KEY-2"}),
        lambda key: json.dumps({key: "Bearer SECRET-KEY-3", "n": 1}),
        lambda key: json.dumps({"attributes": {key: "Bearer SECRET-KEY-4"}}),
    ],
    ids=["repr-list", "repr", "json", "nested-json"],
)
def test_dotted_spaced_and_colon_keys_are_recognised(produce, key, path):
    masked = _assert_never_leaks(produce(key), path)
    assert key in masked


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("key", ["Authorization", "Proxy-Authorization", "api_key", "tokens"])
@pytest.mark.parametrize("indent", [0, 2])
@pytest.mark.parametrize(
    "value",
    [["Bearer SECRET-IND-1"], ["SECRET-IND-2", "SECRET-IND-3"], {"value": "SECRET-IND-4", "n": 1}],
    ids=["list", "two-items", "object"],
)
def test_an_indented_json_list_or_object_value_is_masked_whole(value, indent, key, path):
    text = json.dumps({key: value, "n": 1}, indent=indent)
    masked = _assert_never_leaks(text, path)
    if indent and "Authorization" in key:
        # Indented lines read as folded continuation lines of the header value.
        assert masked == "{\n" + " " * indent + f'"{key}": ***\n}}'
    else:
        assert masked.endswith('"n": 1\n}')


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("api_key=SECRET-BC-1,SECRET-BC-2", "api_key=***"),
        ("token=SECRET-BS-1;SECRET-BS-2 next=1", "token=*** next=1"),
        ("secret=SECRET-BB-1]SECRET-BB-2", "secret=***"),
        ("password: SECRET-BR-1}SECRET-BR-2", "password: ***"),
        ("api_key=SECRET-BM-1,SECRET-BM-2;SECRET-BM-3]x}y, model=m", "api_key=***, model=m"),
        ("Request(token=SECRET-BP-1,SECRET-BP-2, n=1)", "Request(token=***, n=1)"),
    ],
)
def test_a_bare_value_continues_over_embedded_delimiters(text, expected, path):
    assert _assert_never_leaks(text, path) == expected


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "access_token=SECRET-NK-1,refresh_token: SECRET-NK-2",
            "access_token=***,refresh_token: ***",
        ),
        ("api_key=SECRET-NK-3;password: SECRET-NK-4", "api_key=***;password: ***"),
        ("token=SECRET-NK-5,secret: SECRET-NK-6 next=1", "token=***,secret: *** next=1"),
        ("token=SECRET-NK-7,x/password: SECRET-NK-8", "token=***,x/password: ***"),
        ('token=SECRET-NK-9,password="SECRET-NK-10 x"', 'token=***,password="***"'),
    ],
)
def test_a_bare_value_stops_before_another_secret_key(text, expected, path):
    assert _assert_never_leaks(text, path) == expected


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "text",
    [
        "password=(x)SECRET-RUN-1",
        "login failed password=(pw)SECRET-RUN-2 retry",
        "token=[a]SECRET-RUN-3",
        "secret={a}SECRET-RUN-4, n=1",
        "token=u'x'SECRET-RUN-5",
        'token=b"x"SECRET-RUN-6',
        "token='x'SECRET-RUN-7",
        'api_key="a b"SECRET-RUN-8',
    ],
)
def test_a_quoted_or_bracketed_value_that_runs_on_is_masked_to_the_line_end(text, path):
    assert _assert_never_leaks(text, path).endswith("=***")


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "text",
    [
        json.dumps({"msg": repr({"api_key": "it's SECRET-ESCVAL-1"})}),
        json.dumps({"msg": repr({"token": "O'Brien SECRET-ESCVAL-2", "n": 1})}),
        json.dumps({"error": repr(RuntimeError({"password": "pa'ss SECRET-ESCVAL-3"}))}),
    ],
    ids=["repr-in-json", "repr-in-json-two-keys", "exception-repr-in-json"],
)
def test_an_escaped_value_quote_masks_to_the_line_end(text, path):
    # repr() picks double quotes for a value holding a single quote, and json.dumps()
    # escapes them, so the value starts with a backslash-quote of unknown extent.
    assert _assert_never_leaks(text, path).endswith(": ***")


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "text",
    [
        repr(OrderedDict([("http.request.header.authorization", "SECRET-QN-1")])),
        repr([("Accept", "*/*"), ("Proxy Authorization", "SECRET-QN-2")]),
        repr({"headers": [{"name": "header:authorization", "value": "SECRET-QN-3"}]}),
        repr([(" Authorization", "SECRET-QN-4")]),
        repr([(b"Authorization.value", b"SECRET-QN-5")]),
        repr(RuntimeError("x.api_key", "SECRET-QN-6")),
        json.dumps({"headers": [{"name": "Proxy Authorization", "value": "SECRET-QN-7"}]}),
    ],
    ids=["dotted", "spaced", "colon-har", "leading-space", "dotted-suffix", "exc", "har-json"],
)
def test_a_dotted_spaced_or_colon_name_in_a_pair_masks_the_rest_of_the_line(text, path):
    assert _assert_never_leaks(text, path).endswith(", ***")


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            '"error:token": Basic abc_token: \'header:authorization\', "SECRET-KE-1"',
            '"error:token": ***',
        ),
        ("x.api_key: Bearer my_password= 'Authorization', 'SECRET-KE-2'", "x.api_key: ***"),
        ("token=Basic abc_secret= Authorization SECRET-KE-3", "token=***"),
    ],
)
def test_a_bare_value_that_ends_in_another_key_masks_to_the_line_end(text, expected, path):
    # The value swallowed the next key and its separator, so where it ends is unknown.
    assert _assert_never_leaks(text, path) == expected


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "text",
    [
        "password=(x)'SECRET-RQ-1",
        'password=(x)"SECRET-RQ-2',
        "password=(a)\\SECRET-RQ-3",
        "token=(a)'SECRET-RQ-4' more",
        "password=u'a'\"SECRET-RQ-5",
        "password=[a]'SECRET-RQ-6",
        'password={a}"SECRET-RQ-7',
        "password='a'\"SECRET-RQ-8",
    ],
)
def test_a_value_followed_by_a_quote_and_more_text_is_masked_to_the_line_end(text, path):
    assert _assert_never_leaks(text, path).endswith("=***")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"msg": "token=\'x\'", "n": 1}', '{"msg": "token=\'***\'", "n": 1}'),
        ('{"msg": "token=(x)", "n": 1}', '{"msg": "token=(***)", "n": 1}'),
        ("{'msg': 'password=\"x\"', 'n': 1}", "{'msg': 'password=\"***\"', 'n': 1}"),
    ],
)
def test_a_value_closing_inside_another_string_keeps_the_rest_readable(text, expected):
    assert redact(text) == expected


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("producer", list(_STRING_PRODUCERS))
@pytest.mark.parametrize("value", ["(x)", "[x]", "{x}", "'x'", "u'x'"])
@pytest.mark.parametrize("tail", ["''", "'\\", "')", "))", "'\"", '"\\', '""', ")'"])
def test_closing_quotes_and_brackets_that_run_on_into_text_mask_the_rest_of_the_line(
    tail, value, producer, path
):
    text = _STRING_PRODUCERS[producer](f"password={value}{tail}SECRET-TAIL-1")
    _assert_never_leaks(text, path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("password=(x)''SECRET-TAIL-2", "password=***"),
        ('{"msg": "token=(x)\'\'SECRET-TAIL-3", "n": 1}', '{"msg": "token=***'),
        ("f(token=(x)) next", "f(token=(***)) next"),
        ("{'token': 'x'}, n=1", "{'token': '***'}, n=1"),
    ],
)
def test_closing_quotes_and_brackets_end_a_value_only_before_a_delimiter(text, expected):
    assert redact(text) == expected


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('api_key"= token = SECRET-SK-1', 'api_key"= ***'),
        ('api_key"= password: SECRET-SK-2', 'api_key"= ***'),
    ],
)
def test_a_bare_value_that_is_another_key_masks_to_the_line_end(text, expected, path):
    assert _assert_never_leaks(text, path) == expected


_BRACKETS_IN_STRINGS = [
    {"api_key": ["p(ss-SECRET-BK-1"], "n": 1},
    {"api_key": ["ok", "x]y", "SECRET-BK-2"], "n": 1},
    {"api_key": {"k": "SECRET-{BK-3"}, "n": 1},
    {"token": ["a[b", "SECRET-BK-4"], "n": 1},
]


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("indent", [0, 2])
@pytest.mark.parametrize("payload", _BRACKETS_IN_STRINGS)
def test_a_one_level_value_whose_strings_hold_brackets_never_leaks(payload, indent, path):
    _assert_never_leaks(json.dumps(payload, indent=indent), path)


@pytest.mark.parametrize("payload", _BRACKETS_IN_STRINGS)
def test_a_one_level_value_whose_strings_hold_brackets_is_masked_whole(payload):
    masked = redact(json.dumps(payload, indent=0))
    assert masked.endswith('\n"n": 1\n}')
    assert "SECRET-" not in masked


_ESCAPED_QUOTES_IN_STRINGS = [
    ['say "hi" SECRET-EQ-1'],
    ['SECRET-EQ-2"', 'x"SECRET-EQ-3'],
    ['it\'s "quoted" SECRET-EQ-4', "SECRET-EQ-5"],
    {"k": 'say "hi" SECRET-EQ-6', "k2": "SECRET-EQ-7"},
]
_ESCAPED_QUOTES_IDS = ["list", "two-items", "both-quotes", "object"]


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize("key", ["api_key", "Authorization", "Proxy-Authorization", "access_token"])
@pytest.mark.parametrize("indent", [0, 2])
@pytest.mark.parametrize("value", _ESCAPED_QUOTES_IN_STRINGS, ids=_ESCAPED_QUOTES_IDS)
def test_a_one_level_value_whose_strings_hold_escaped_quotes_never_leaks(value, indent, key, path):
    _assert_never_leaks(json.dumps({key: value, "n": 1}, indent=indent), path)
    _assert_never_leaks(json.dumps({"request": {key: value}, "n": 1}, indent=indent), path)


@pytest.mark.parametrize("value", _ESCAPED_QUOTES_IN_STRINGS, ids=_ESCAPED_QUOTES_IDS)
def test_an_unscanned_value_is_masked_up_to_the_line_holding_its_closer(value):
    masked = redact(json.dumps({"api_key": value, "n": 1}, indent=0))
    assert masked == '{\n"api_key": ***\n"n": 1\n}'


def test_a_value_opening_a_container_with_no_closing_line_is_masked_to_the_end():
    text = '{\n"api_key": [\n"x\\"SECRET-EQ-8",\n"SECRET-EQ-9"'
    assert redact(text) == '{\n"api_key": ***'


@pytest.mark.parametrize("formatter", ["text", "json"])
def test_exception_text_with_a_value_that_runs_on_is_masked(formatter):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JsonFormatter() if formatter == "json" else TextFormatter("%(levelname)s %(message)s")
    )
    logger = logging.getLogger("aragora_debate.tests.exception_text")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError("login failed password=(pw)SECRET-EXC-1\ntoken=u'x'SECRET-EXC-2")
        except RuntimeError:
            logger.exception("request failed")
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert "password=***" in output
    assert "SECRET-" not in output


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": ["SECRET-STABLE-1"]},
        {"token": ("SECRET-STABLE-2", 1)},
        {"n": {"password": {"v": "SECRET-STABLE-3"}}},
    ],
    ids=["list", "tuple", "object"],
)
def test_a_masked_container_value_stays_stable_inside_an_exception_repr(payload, path):
    masked = _assert_never_leaks("request failed: " + repr(RuntimeError(payload)), path)
    assert masked.endswith("})")


@pytest.mark.parametrize(
    "text",
    [
        "a" * 40_000,
        "token" * 8_000,
        "authorization" * 3_077,
        ("token=''" + "b" * 5_000 + " ") * 8,
        "Authorization x " * 2_500,
        "Authorization Bearer x\n" * 1_800 + "token=SECRET-LIN-1",
        "token: [" * 5_000,
        "a." * 20_000,
        'api_key=["\\" ' * 3_000,
        '"api_key": {"\\" ' * 2_500,
        "Authorization: ('\\' " * 2_500,
        'api_key=["[\'" ' * 3_000,
        "api_key=['[\"' " * 3_000,
        "password=a," + "token" * 8_000,
        "password=a," + "a_token" * 5_700,
        "token=x;" + "secret-" * 5_700,
        "token=x}" + "token" * 8_000,
        "token=x," + "api_key." * 5_000,
        "Authorization=Bearer a," + "token" * 8_000,
    ],
    ids=[
        "long-word",
        "token-word",
        "authorization-word",
        "token-heavy-line",
        "authorization-words",
        "phrase-lines",
        "open-brackets",
        "dotted",
        "open-brackets-with-quotes",
        "open-braces-with-quotes",
        "open-parentheses-with-quotes",
        "open-brackets-with-quoted-brackets",
        "open-brackets-with-quoted-brackets-sq",
        "comma-then-token-word",
        "comma-then-key-words",
        "semicolon-then-secret-words",
        "brace-then-token-word",
        "comma-then-dotted-keys",
        "authorization-comma-then-token-word",
    ],
)
def test_redact_takes_linear_time_on_long_words_and_token_heavy_lines(text):
    started = time.perf_counter()
    masked = redact(text)
    assert time.perf_counter() - started < 5
    assert "SECRET-" not in masked


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    "text",
    [
        "missing fields: ['api_key', 'model'] in request",
        "{'type': 'token', 'value': 'v', 'n': 1}",
        json.dumps({"required": ["api_key", "password"], "type": "token", "n": 1}),
        "authorization failed for user bob: Bearer token expired",
        "Authorization is required for this endpoint",
    ],
)
def test_secret_names_without_a_value_stay_unchanged(text, path):
    output, masked = _render_through(path, text)
    assert masked == text


@pytest.mark.parametrize("path", _LOG_PATHS)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Invalid Authorization header format - expected 'Bearer <token>'",
            "Invalid Authorization header format - expected '***",
        ),
        ("token=abc,def next=1", "token=*** next=1"),
        (
            json.dumps({"Authorization": "Bearer SECRET-END-1", "n": 1}),
            '{"Authorization": "***", "n": 1}',
        ),
        (
            repr({"Proxy-Authorization": "Basic SECRET-END-2", "n": 1}),
            "{'Proxy-Authorization': '***', 'n': 1}",
        ),
        ("token: [SECRET-END-3 (unclosed)\nnext", "token: ***\nnext"),
        (
            json.dumps({"api_key": ["SECRET-END-4"], "n": 1}, indent=0),
            '{\n"api_key": [***],\n"n": 1\n}',
        ),
    ],
)
def test_masks_end_where_the_value_or_its_line_ends(text, expected, path):
    output, masked = _render_through(path, text)
    assert "SECRET-" not in output
    assert masked == expected
    assert redact(masked) == masked


def test_redact_replaces_reference_cycles():
    payload = {"name": "x", "token": "SECRET-WHISKEY-3"}
    payload["self"] = payload
    items = ["a"]
    items.append(items)
    assert redact(payload) == {"name": "x", "token": "***", "self": "<cycle>"}
    assert redact(items) == ["a", "<cycle>"]
    shared = {"n": 1}
    assert redact([shared, shared]) == [{"n": 1}, {"n": 1}]


def test_redact_colon_forms_keep_their_shape():
    assert redact("Authorization: Bearer SECRET-HOTEL-444") == "Authorization: ***"
    assert json.loads(redact('{"api_key": "SECRET-GOLF-333", "model": "m"}')) == {
        "api_key": "***",
        "model": "m",
    }
    assert redact(str({"Authorization": "Bearer SECRET-JULIET-666", "n": 1})) == (
        "{'Authorization': '***', 'n': 1}"
    )
    assert redact("model: gpt, retries: 3") == "model: gpt, retries: 3"


def test_redact_masks_values_under_keys_json_cannot_encode():
    payload = {("api", "key"): "SECRET-ALPHA-123", 7: "seven", "n": {("a", 1): 2}}
    assert redact(payload) == {"('api', 'key')": "***", 7: "seven", "n": {"('a', 1)": "***"}}
    assert payload[("api", "key")] == "SECRET-ALPHA-123"


def test_json_formatter_coerces_non_string_keys_without_logging_error():
    result = _probe(
        """
from aragora_debate._logging import configure_logging
import logging
configure_logging()
logging.getLogger("aragora_debate.val").warning(
    "probe",
    extra={"payload": {("tuple", "key"): "SECRET-INDIA-555", 2: {"n": 1}}},
)
""",
        ARAGORA_LOG_FORMAT="json",
    )
    (line,) = result.stderr.splitlines()
    data = json.loads(line)
    assert data["payload"] == {"('tuple', 'key')": "***", "2": {"n": 1}}
    assert data["msg"] == "probe"
    assert "SECRET-" not in result.stderr
    assert "Logging error" not in result.stderr


@pytest.mark.parametrize("format_name", ["text", "json"])
def test_unformattable_arguments_never_reach_the_logging_error_handler(format_name):
    result = _probe(
        """
from aragora_debate._logging import configure_logging
import logging
configure_logging()
logging.getLogger("val").warning("api_key=%s retries=%d", "SECRET-XRAY-4", "many")
cyclic = {"token": "SECRET-YANKEE-5"}
cyclic["self"] = cyclic
logging.getLogger("val").warning("cyclic", extra={"payload": cyclic})
""",
        ARAGORA_LOG_FORMAT=format_name,
    )
    lines = result.stderr.splitlines()
    assert len(lines) == 2, result.stderr
    assert "unformattable log arguments: TypeError" in lines[0]
    assert "SECRET-" not in result.stderr
    assert "Logging error" not in result.stderr
    if format_name == "json":
        assert json.loads(lines[1])["payload"] == {"token": "***", "self": "<cycle>"}


def test_json_formatter_falls_back_when_extras_are_too_deep_to_encode():
    nested: list = []
    for _ in range(5000):
        nested = [nested]
    record = logging.LogRecord("val", logging.WARNING, "", 0, "deep api_key=%s", ("x",), None)
    record.payload = nested
    data = json.loads(JsonFormatter().format(record))
    assert data["msg"] == "deep api_key=***"
    assert data["format_error"] == "RecursionError"
    assert "payload" not in data


_STREAM_PROBE = """
import io
import logging
import sys
from aragora_debate._logging import JsonFormatter, configure_logging

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
from aragora_debate._logging import configure_logging

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


_SECRET_WORD_LOGGERS = ["aragora.security.token_rotation", "svc.authorization.check"]
_SECRET_WORD_LOGGERS += ["api_key_loader", "password_reset"]


@pytest.mark.parametrize("name", _SECRET_WORD_LOGGERS)
def test_a_logger_name_with_a_secret_word_never_masks_the_message(name):
    result = _probe(f"""
from aragora_debate._logging import configure_logging
import logging
configure_logging()
logging.getLogger({name!r}).warning("rotating keys")
logging.getLogger({name!r}).warning("rotated token=SECRET-NAME-1")
""")
    assert result.stderr == f"WARNING {name}: rotating keys\nWARNING {name}: rotated token=***\n"
    fields = dict(name=name, msg="rotating keys", pathname="token.py", funcName="api_key_get")
    record = logging.makeLogRecord(fields)
    assert TextFormatter("%(name)s: %(message)s").format(record) == f"{name}: rotating keys"
    line = TextFormatter("%(pathname)s %(funcName)s %(name)s: %(message)s").format(record)
    assert line == f"token.py api_key_get {name}: rotating keys"
    record.msg = "api_key=SECRET-NAME-2 sent"
    assert TextFormatter("%(name)s: %(message)s").format(record) == f"{name}: api_key=*** sent"


_BYTES = {b"Authorization: Bearer abc": b"Authorization: ***", b"\xff\xfe api_key=SECRET-X": b"***"}
_BYTES[b"retry api_key=SECRET-X now"] = b"retry api_key=*** now"


@pytest.mark.parametrize("kind", [bytes, bytearray])
@pytest.mark.parametrize("raw", _BYTES, ids=["header", "undecodable", "assignment"])
def test_redact_masks_bytes_alone_and_nested_and_keeps_their_type(kind, raw):
    masked = redact({"raw": kind(raw), "items": [kind(raw)], "pair": (kind(raw), "ok")})
    for value in (redact(kind(raw)), masked["raw"], masked["items"][0], masked["pair"][0]):
        assert (type(value), value) == (kind, _BYTES[raw])
    assert masked["pair"][1] == "ok"


@pytest.mark.parametrize("kind", [set, frozenset])
def test_redact_masks_set_items_alone_and_nested_and_keeps_their_type(kind):
    value = kind({"api_key=SECRET-X", "plain", b"Authorization: Bearer abc", 42})
    expected = kind({"api_key=***", "plain", b"Authorization: ***", 42})
    masked = redact({"tags": value, "items": [value], "pair": (value, "ok")})
    for item in (redact(value), masked["tags"], masked["items"][0], masked["pair"][0]):
        assert (type(item), item) == (kind, expected)


_RECORD = dict(msg="login for %s token=%s", args=("alice", "SECRET-EXTRA-7"), user="alice", count=3)
_RECORD.update(api_key="SECRET-EXTRA-1", token=123456, authorization="Bearer SECRET-EXTRA-3")
_RECORD.update(password=b"SECRET-EXTRA-4", note="password=SECRET-EXTRA-5")
_RECORD["error"] = RuntimeError("token=SECRET-EXTRA-6")
_TEXT = {"%(api_key)s %(message)s": "*** login for alice token=***"}
_TEXT["%(token)s %(authorization)s %(password)s"] = "*** *** ***"
_TEXT["%(note)s %(error)s %(user)s %(count)d"] = "password=*** token=*** alice 3"
_TEXT["%(msg)s %(args)s"] = "login for alice token=*** ()"


@pytest.mark.parametrize(("text_format", "expected"), _TEXT.items())
def test_text_formats_naming_extras_never_print_a_secret(text_format, expected):
    assert TextFormatter(text_format).format(logging.makeLogRecord(_RECORD)) == expected


def test_text_formats_never_print_secrets_from_exceptions_stacks_or_object_extras():
    try:
        raise ValueError("password=SECRET-EXTRA-8")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    record.stack_info = "Stack (most recent call last):\n  token=SECRET-EXTRA-9"
    record.payload = {"items": [RuntimeError("api_key=SECRET-EXTRA-10")], "n": 1}
    text_format = "%(exc_info)s %(exc_text)s %(stack_info)s %(payload)s %(message)s"
    line = TextFormatter(text_format).format(record)
    assert "SECRET-" not in line
    assert "password=***" in line and "token=***" in line and "api_key=***" in line


def test_json_extras_named_like_fixed_fields_move_to_a_prefixed_key():
    record = logging.LogRecord("val", logging.WARNING, "", 0, "hello", (), None, sinfo="here")
    record.created, record.extra_ts = 0.0, "kept"
    record.__dict__.update(level="DEBUG token=SECRET-FIX-1", logger="x", ts="then", stack="mine")
    data = json.loads(line := JsonFormatter().format(record))
    fixed = [data[key] for key in ("ts", "level", "logger", "msg", "stack")]
    assert fixed == ["1970-01-01T00:00:00+00:00", "WARNING", "val", "hello", "here"]
    moved = [data[key] for key in ("extra_level", "extra_logger", "extra_extra_ts", "extra_stack")]
    assert moved == ["DEBUG token=***", "x", "then", "mine"]
    assert data["extra_ts"] == "kept" and "SECRET-" not in line


_PAYLOAD = SimpleNamespace(password="LEAK-R1", inner=SimpleNamespace(token="LEAK-R1"))
_DEFAULTS = {"note": "password=LEAK-R1", "token": "LEAK-R1"}
_LEAKS = {"api_key=%(credential)s": "api_key=***", "%(note)s": "password=***", "%(token)s": "***"}
_LEAKS["{payload.__dict__}"] = "{'password': '***', 'inner': namespace(token='***')}"
_LEAKS["{payload.inner.token}"] = _LEAKS["{payload.__dict__[_value].password}"] = "format_error"
_DATA = {"items": [({"api_key[primary]": "LEAK-R1"},)]}
_LEAKS["%(data)s %(message)s"] = _LEAKS["{data} {message}"] = "[({'api_key[primary]': '***'},)]"
_Pair = namedtuple("Credentials", "password user")
_PAIRS = [(_Pair("LEAK-R3", "alice"), "Credentials(password='***', user='alice')")]
_PAIRS += [(namedtuple("Credentials", "password")("LEAK-R3"), "Credentials(password='***')")]
_odd = lambda **attrs: (type("Odd", (_Pair,), attrs)._make(["LEAK-R3", "bob"]), "('***', '***')")
_PAIRS += [_odd(_fields=f) for f in [(0, 1), ("password",), ("user", "password")]]
_PAIRS += [_odd(__new__=f) for f in [lambda cls: cls, lambda *_: 1 / 0, lambda *_: _PAIRS[0][0]]]


@pytest.mark.parametrize("text_format", _LEAKS)
def test_labels_defaults_and_brace_traversal_are_redacted_with_the_line(text_format):
    style = "{" if "{" in text_format else "%"
    record = logging.makeLogRecord({"credential": "LEAK-R1", "payload": _PAYLOAD, "data": _DATA})
    line = TextFormatter(text_format, style=style, defaults=_DEFAULTS).format(record)
    assert _LEAKS[text_format] in line and "LEAK-R1" not in line
    assert _DATA == {"items": [({"api_key[primary]": "LEAK-R1"},)]}


@pytest.mark.parametrize(("pair", "shown"), _PAIRS)
def test_namedtuple_fields_are_masked_by_name_or_the_tuple_is_masked_whole(pair, shown):
    nested, inner = {"items": [pair]}, f"{{'items': [{shown}]}}"
    record = logging.makeLogRecord({"msg": "ok", "pair": pair, "nested": nested})
    for fmt in ("%(pair)s %(nested)s %(message)s", "{pair} {nested} {message}"):
        assert TextFormatter(fmt, style=fmt[0]).format(record) == f"{shown} {inner} ok"
    assert (repr(redact(pair)), repr(redact(nested)), nested) == (shown, inner, {"items": [pair]})
    line = JsonFormatter().format(record)
    assert json.loads(line)["pair"] == json.loads(line)["nested"]["items"][0] == list(redact(pair))


@pytest.mark.parametrize("field, shown", [("context", "{'api_key': '***'}"), ("api_token", "***")])
def test_fields_a_record_factory_adds_are_caller_data(field, shown):
    result = _probe(f"""
import logging
class Record(logging.LogRecord):
    def __init__(self, *args):
        super().__init__(*args)
        self.__dict__.update(context={{"api_key": "LEAK-R1"}}, api_token="LEAK-R1")
logging.setLogRecordFactory(Record)
from aragora_debate._logging import TextFormatter
print(TextFormatter("%({field})s").format(logging.makeLogRecord({{}})))
""")
    assert result.stdout == f"{shown}\n"
