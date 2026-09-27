#!/usr/bin/env python3
"""Check the stable, reviewed inventory of production inference call sites."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(__file__).with_name("inference_site_allowlist.json")
SCAN_ROOTS = ("aragora", "scripts", ".github")
SELF_PATH = "scripts/check_inference_site_allowlist.py"
SCAN_EXCLUDED_DIRS = frozenset(
    {"__pycache__", "__tests__", "baselines", "e2e", "generated", "node_modules"}
)
SCAN_EXCLUDED_NAMES = frozenset({"package-lock.json", "pnpm-lock.yaml", "yarn.lock"})
PYTHON_AST_NEEDLES = (
    "8317",
    "modeltransportpolicy",
    "openai",
    "anthropic",
    "genai",
    "google.genai",
    "generativemodel",
    "generatecontent",
    "api.x.ai",
    "openrouter.ai",
    "generativelanguage.googleapis.com",
    "api.moonshot.ai",
    "api.moonshot.cn",
    "api.mistral.ai",
    "mistral",
    "api.deepseek.com",
    "api.thinkingmachines.ai",
    "/audio/transcriptions",
    "/chat/completions",
    "/responses",
    "/messages",
    "/sample",
    "/embeddings",
    "/completions",
    "generate_content",
)
CLASSIFICATIONS = frozenset({"proxy-eligible", "direct-only"})
DIRECT_CALL_DETECTORS = frozenset({"client-constructor", "http-inference-call", "inference-method"})
# fmt: off
TEXT_SUFFIXES = frozenset({".py", ".sh", ".bash", ".zsh", ".yml", ".yaml", ".json", ".toml", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
JS_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"})
JS_CONSTRUCTORS = {"OpenAI": "openai-compatible", "Anthropic": "anthropic", "GoogleGenAI": "gemini"}
JS_IMPORTS = ((r'import\s+([A-Za-z_$][\w$]*)\s+from\s+["\']openai["\']', "", "openai-compatible"), (r'import\s*\{[^}]*\bOpenAI(?:\s+as\s+([A-Za-z_$][\w$]*))?[^}]*\}\s*from\s*["\']openai["\']', "OpenAI", "openai-compatible"), (r'import\s+([A-Za-z_$][\w$]*)\s+from\s+["\']@anthropic-ai/sdk["\']', "", "anthropic"), (r'import\s*\{[^}]*\bAnthropic(?:\s+as\s+([A-Za-z_$][\w$]*))?[^}]*\}\s*from\s*["\']@anthropic-ai/sdk["\']', "Anthropic", "anthropic"), (r'import\s+([A-Za-z_$][\w$]*)\s+from\s+["\']@google/genai["\']', "", "gemini"), (r'import\s*\{[^}]*\bGoogleGenAI(?:\s+as\s+([A-Za-z_$][\w$]*))?[^}]*\}\s*from\s*["\']@google/genai["\']', "GoogleGenAI", "gemini"), (r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*["\']openai["\']\s*\)(?:\.default)?', "", "openai-compatible"), (r'(?:const|let|var)\s*\{[^}]*\b(?:OpenAI|default)(?:\s*:\s*([A-Za-z_$][\w$]*))?[^}]*\}\s*=\s*require\(\s*["\']openai["\']\s*\)', "OpenAI", "openai-compatible"), (r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*["\']@anthropic-ai/sdk["\']\s*\)(?:\.default)?', "", "anthropic"), (r'(?:const|let|var)\s*\{[^}]*\b(?:Anthropic|default)(?:\s*:\s*([A-Za-z_$][\w$]*))?[^}]*\}\s*=\s*require\(\s*["\']@anthropic-ai/sdk["\']\s*\)', "Anthropic", "anthropic"), (r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*["\']@google/genai["\']\s*\)(?:\.default)?', "", "gemini"), (r'(?:const|let|var)\s*\{[^}]*\b(?:GoogleGenAI|default)(?:\s*:\s*([A-Za-z_$][\w$]*))?[^}]*\}\s*=\s*require\(\s*["\']@google/genai["\']\s*\)', "GoogleGenAI", "gemini"))
JS_COMMENT_RE = re.compile(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(/\*.*?\*/|//[^\n]*)''', re.DOTALL)
JS_CODE_STRING_RE = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`''')
JS_VALUE_ASSIGN_RE = re.compile(r'''(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)''', re.DOTALL)
JS_TEMPLATE_IDENTIFIER_RE = re.compile(r"\$\{\s*([A-Za-z_$][\w$]*)\s*\}")
JS_HTTP_CALL_RE = re.compile(r'''(?<![\w$])(?:fetch|[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\.(?:post|request))\s*(?:<(?:[^<>()]|<[^<>]*>)+>\s*)?\(\s*([A-Za-z_$][\w$]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)''', re.DOTALL)
FORBIDDEN_PORT_RE = re.compile(r":0*8317\b")
PORT_STRING_RE = re.compile(
    r"(?i)(?<![a-z])port(?![a-z])\D{0,8}0*8317(?!\d)|(?:^|\s)-p\s+0*8317(?!\d)"
)
PORT_ENFORCEMENT_PATH = "aragora/agents/transports/vibeproxy.py"
PORT_ENFORCEMENT_LINE = "PROHIBITED_PORTS = {8317}"
PROVIDER_HOSTS = {"api.openai.com": "openai", "api.anthropic.com": "anthropic", "openrouter.ai": "openrouter", "api.x.ai": "xai", "generativelanguage.googleapis.com": "gemini", "api.moonshot.ai": "kimi", "api.moonshot.cn": "kimi", "api.mistral.ai": "mistral", "api.deepseek.com": "deepseek", "api.thinkingmachines.ai": "tinker"}
URL_RE = re.compile(r'''https?://[^\s"'`<>()\[\]{}]+''', re.IGNORECASE)
PYTHON_NUMBER_RE = re.compile(r"(?<![\w.])(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|[0-9][0-9_]*)(?![\w.])")
PROTOCOL_PATHS = (("/audio/transcriptions", "audio"), ("/chat/completions", "chat"), ("/responses", "responses"), ("/messages", "messages"), ("/sample", "sample"), ("/embeddings", "embeddings"), ("/completions", "completions"))
PROTOCOL_PROVIDERS = {"audio": "openai-compatible", "chat": "openai-compatible", "responses": "openai-compatible", "embeddings": "openai-compatible", "completions": "openai-compatible"}
ANTHROPIC_CONTEXT_RE = re.compile(r"(?i)anthropic|claude")
TINKER_CONTEXT_RE = re.compile(r"(?i)tinker|thinkingmachines")
SDK_MODULE_PROVIDERS = {"openai": "openai-compatible", "anthropic": "anthropic", "mistralai": "mistral", "google.genai": "gemini", "google.generativeai": "gemini"}
DYNAMIC_CONSTRUCTOR_NAMES = {"openai-compatible": frozenset({"OpenAI", "AsyncOpenAI"}), "anthropic": frozenset({"Anthropic", "AsyncAnthropic"}), "mistral": frozenset({"Mistral"}), "gemini": frozenset({"Client", "GenerativeModel"})}
CONSTRUCTORS = {"OpenAI": ("openai-compatible", "client"), "AsyncOpenAI": ("openai-compatible", "client"), "Anthropic": ("anthropic", "client"), "AsyncAnthropic": ("anthropic", "client"), "GenerativeModel": ("gemini", "client"), "Mistral": ("mistral", "client")}
METHOD_SUFFIXES = (("audio.transcriptions.create", "openai-compatible", "audio"), ("chat.completions.create", "openai-compatible", "chat"), ("chat.completions.parse", "openai-compatible", "chat"), ("responses.create", "openai-compatible", "responses"), ("responses.parse", "openai-compatible", "responses"), ("responses.stream", "openai-compatible", "responses"), ("messages.create", "anthropic", "messages"), ("messages.stream", "anthropic", "messages"), ("embeddings.create", "openai-compatible", "embeddings"), ("completions.create", "openai-compatible", "completions"), ("models.generate_content", "gemini", "generate-content"), ("models.generate_content_async", "gemini", "generate-content"), ("models.generate_content_stream", "gemini", "generate-content"), ("models.generateContent", "gemini", "generate-content"), ("models.generateContentStream", "gemini", "generate-content"), ("generate_content", "gemini", "generate-content"), ("generate_content_async", "gemini", "generate-content"), ("audio.transcriptions.complete", "mistral", "audio"), ("chat.complete", "mistral", "chat"), ("chat.stream", "mistral", "chat"), ("agents.complete", "mistral", "messages"), ("agents.stream", "mistral", "messages"), ("fim.complete", "mistral", "completions"))
HTTP_CALL_TERMINALS = frozenset({"post", "request", "Request", "stream"})
URL_HELPER_TERMINALS = frozenset({"build_url", "join_url", "make_url", "resolve_url", "urljoin"})
PROTECTED_PATHS = {
    "ci": (".github/**", "scripts/ci/**"),
    "production-server": ("aragora/server/**",),
    "credential-validation": ("**/*key*", "**/*secret*", "**/*rotator*", "**/*pkce*", "scripts/rotate_keys.py", "scripts/migrate_secrets_to_aws.py", "aragora/cli/setup.py"),
    "public-gateway": ("aragora/gateway/**", "aragora/security/api_key_proxy.py"),
    "evidence-or-settlement": ("**/*evidence*", "**/*quorum*", "**/*review*", "**/*settle*", "aragora/verification/**"),
    "production-preflight": ("**/*preflight*", "**/*live_fire*"),
}
# fmt: on


@dataclass(frozen=True, order=True)
class SiteKey:
    path: str
    anchor: str
    provider: str
    protocol: str


@dataclass(frozen=True)
class Site:
    path: str
    anchor: str
    provider: str
    protocol: str
    detectors: dict[str, int]

    @property
    def key(self) -> SiteKey:
        return SiteKey(self.path, self.anchor, self.provider, self.protocol)


@dataclass(frozen=True)
class Discovery:
    sites: tuple[Site, ...]
    scanned_files: int
    raw_detections: int
    policy_consumers: tuple[str, ...]
    forbidden_ports: tuple[str, ...]
    scan_errors: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    scanned_files: int
    site_count: int
    raw_detections: int
    policy_consumers: tuple[str, ...]
    unclassified: tuple[str, ...]
    stale: tuple[str, ...]
    changed: tuple[str, ...]
    manifest_errors: tuple[str, ...]
    policy_errors: tuple[str, ...]
    forbidden_ports: tuple[str, ...]
    scan_errors: tuple[str, ...]


def _attr_chain(node: ast.AST, *, unwrap_calls: bool = False) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute) or (unwrap_calls and isinstance(node, ast.Call)):
        if isinstance(node, ast.Call):
            node = node.func
            continue
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _protocol_for_url(value: str) -> str:
    return next((name for fragment, name in PROTOCOL_PATHS if fragment in value.lower()), "base")


def _providers_for_urls(value: str) -> tuple[str, ...]:
    providers: list[str] = []
    for match in URL_RE.finditer(value):
        try:
            hostname = urlsplit(match.group()).hostname
        except ValueError:
            continue
        if hostname is not None and (provider := PROVIDER_HOSTS.get(hostname.lower())):
            providers.append(provider)
    return tuple(dict.fromkeys(providers))


def _provider_for_url(value: str) -> str | None:
    return next(iter(_providers_for_urls(value)), None)


def _provider_for_http_endpoint(value: str, context: str = "") -> str | None:
    provider = _provider_for_url(value)
    if provider is not None:
        return provider
    protocol = _protocol_for_url(value)
    if protocol == "sample" and TINKER_CONTEXT_RE.search(context):
        return "tinker"
    if "{}" not in value:
        return None
    provider = PROTOCOL_PROVIDERS.get(protocol)
    if provider is None and protocol == "messages" and ANTHROPIC_CONTEXT_RE.search(context):
        return "anthropic"
    return provider


def _contains_forbidden_port(value: Any, key: str = "") -> bool:
    if type(value) is int:
        return value == 8317
    if isinstance(value, (str, bytes)):
        text = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else value
        return (
            bool(FORBIDDEN_PORT_RE.search(text))
            or bool(PORT_STRING_RE.search(text))
            or bool(re.fullmatch(r"0*8317", text))
            or ("port" in key.lower() and bool(re.fullmatch(r"0*8317", text)))
        )
    if isinstance(value, list):
        return any(_contains_forbidden_port(item, key) for item in value)
    if isinstance(value, dict):
        return any(_contains_forbidden_port(item, str(name)) or _contains_forbidden_port(name) for name, item in value.items())  # fmt: skip
    return False


def _may_contain_python_numeric_port_literal(source: str) -> bool:
    """Cheap raw-text prefilter only; the parsed AST decides whether a port exists."""

    for match in PYTHON_NUMBER_RE.finditer(source):
        token = match.group().replace("_", "")
        base = 0 if token.lower().startswith(("0x", "0o", "0b")) else 10
        try:
            if int(token, base) == 8317:
                return True
        except ValueError:
            continue
    return False


def _targets(node: ast.AST) -> tuple[str, ...]:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return ()
    raw = node.targets if isinstance(node, ast.Assign) else [node.target]
    return tuple(chain for target in raw if (chain := _attr_chain(target)))


def _sdk_module_aliases(tree: ast.AST) -> dict[str, str]:
    return {
        name.asname or name.name.split(".", 1)[0]: provider
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for name in node.names
        if (provider := SDK_MODULE_PROVIDERS.get(name.name)) is not None
    }


def _dynamic_constructor(node: ast.AST, module_aliases: dict[str, str]) -> tuple[str, str] | None:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Call)):
        return None
    lookup = node.func
    if _attr_chain(lookup.func) != "getattr" or len(lookup.args) < 2:
        return None
    module = _attr_chain(lookup.args[0])
    name_node = lookup.args[1]
    if not (isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)):
        return None
    provider = module_aliases.get(module)
    if provider is None or name_node.value not in DYNAMIC_CONSTRUCTOR_NAMES[provider]:
        return None
    return provider, "client"


def _constructor_aliases(tree: ast.AST) -> dict[str, tuple[str, str]]:
    aliases = dict(CONSTRUCTORS)
    nodes = tuple(ast.walk(tree))
    for node in nodes:
        if isinstance(node, ast.Import):
            aliases.update({f"{name.asname or name.name}.Client": ("gemini", "client") for name in node.names if name.name == "google.genai"})  # fmt: skip
        if isinstance(node, ast.ImportFrom) and node.module in {"google", "google.genai"}:
            aliases.update({f"{name.asname or name.name}{'.Client' if node.module == 'google' else ''}": ("gemini", "client") for name in node.names if name.name == ("genai" if node.module == "google" else "Client")})  # fmt: skip
        if isinstance(node, ast.ImportFrom) and node.module in {"openai", "anthropic", "mistralai"}:
            for name in node.names:
                if name.name in CONSTRUCTORS:
                    aliases[name.asname or name.name] = CONSTRUCTORS[name.name]
    for _ in range(3):
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                if node.value is None:
                    continue
                source = _attr_chain(node.value)
                terminal = source.rsplit(".", 1)[-1]
                constructor = aliases.get(source) or (aliases.get(terminal) if terminal != "Client" or "." not in source else None)  # fmt: skip
                if constructor is not None:
                    aliases.update(
                        {target.rsplit(".", 1)[-1]: constructor for target in _targets(node)}
                    )
    return aliases


# fmt: off
def _typed_client(annotation: ast.AST | None, aliases: dict[str, tuple[str, str]]) -> bool:
    return annotation is not None and any((chain := _attr_chain(part)) in aliases or ((terminal := chain.rsplit(".", 1)[-1]) in aliases and (terminal != "Client" or "." not in chain)) for part in ast.walk(annotation))


def _client_provenance(tree: ast.AST, aliases: dict[str, tuple[str, str]], module_aliases: dict[str, str]) -> tuple[set[str], set[str]]:
    nodes = tuple(ast.walk(tree))
    functions = (
        node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    factories = {
        node.name
        for node in functions
        if (_typed_client(node.returns, aliases))
        or any(
            isinstance(part, ast.Call) and ((chain := _attr_chain(part.func)) in aliases or ((terminal := chain.rsplit(".", 1)[-1]) in aliases and (terminal != "Client" or "." not in chain)))  # fmt: skip
            for part in ast.walk(node)
        )
    }
    clients = {node.arg for node in nodes if isinstance(node, ast.arg) and _typed_client(node.annotation, aliases)}
    clients.update(name.asname or name.name for node in nodes if isinstance(node, ast.Import) for name in node.names if name.name == "openai")  # fmt: skip
# fmt: on
    def backed(value: ast.AST) -> bool:
        if isinstance(value, ast.IfExp):
            return backed(value.body) or backed(value.orelse)
        value = value.value if isinstance(value, ast.Await) else value
        chain = _attr_chain(value.func) if isinstance(value, ast.Call) else _attr_chain(value)
        terminal = chain.rsplit(".", 1)[-1]
        return _dynamic_constructor(value, module_aliases) is not None or chain in clients or chain in aliases or (terminal in aliases and (terminal != "Client" or "." not in chain)) or terminal in factories  # fmt: skip

    for _ in range(3):
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if value is None:
                    continue
                typed = isinstance(node, ast.AnnAssign) and _typed_client(node.annotation, aliases)
                if typed or backed(value):
                    clients.update(_targets(node))
    return clients, factories


def _scope_anchor(scope: list[tuple[str, str]]) -> str:
    if not scope:
        return "<module>"
    kind, name = scope[0]
    return f"{name}.{scope[1][1]}" if kind == "class" and len(scope) > 1 else name


def _url_values(
    node: ast.AST,
    bindings: dict[tuple[str, str], set[str]],
    anchor: str,
    class_name: str | None,
) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Name, ast.Attribute)):
        chain = _attr_chain(node)
        scopes = (
            [anchor, f"{class_name}.__init__", class_name]
            if class_name and chain.startswith(("self.", "cls."))
            else [anchor]
        )
        if anchor != "<module>":
            scopes.append("<module>")
        for scope in scopes:
            key = (scope or "<module>", chain)
            if key in bindings:
                return bindings[key]
        return set()
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left_values = _url_values(node.left, bindings, anchor, class_name) or {"{}"}
        right_values = _url_values(node.right, bindings, anchor, class_name) or {"{}"}
        return {left + right for left in left_values for right in right_values}
    if isinstance(node, ast.JoinedStr):
        values = {""}
        for part in node.values:
            pieces = {str(part.value)} if isinstance(part, ast.Constant) else _url_values(part.value, bindings, anchor, class_name) if isinstance(part, ast.FormattedValue) else set()  # fmt: skip
            values = {value + piece for value in values for piece in (pieces or {"{}"})}
        return values
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"rstrip", "removesuffix"}:  # fmt: skip
            return _url_values(node.func.value, bindings, anchor, class_name)
        chain = _attr_chain(node.func)
        terminal = chain.rsplit(".", 1)[-1]
        callees = [
            f"{class_name}.{terminal}"
            if class_name and chain.startswith(("self.", "cls."))
            else chain
        ]
        return_keys = tuple((callee, "<return>") for callee in callees)
        returned = {
            value
            for key in return_keys
            for value in bindings.get(key, set())
        }
        if any(key in bindings for key in return_keys):
            return returned | {
                value
                for candidate in (*node.args, *(keyword.value for keyword in node.keywords))
                for value in _url_values(candidate, bindings, anchor, class_name)
            }
        candidates = (*node.args, *(keyword.value for keyword in node.keywords))
        if terminal in URL_HELPER_TERMINALS and len(candidates) >= 2:
            combined = {""}
            for candidate in candidates:
                values = _url_values(candidate, bindings, anchor, class_name) or {"{}"}
                combined = {prefix + value for prefix in combined for value in values}
            return combined
    return set()


class _UrlAssignmentCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[tuple[str, str]] = []
        self.assignments: list[tuple[str, str | None, ast.Assign | ast.AnnAssign]] = []
        self.constructor_keywords: list[tuple[str, str, str, ast.AST]] = []
        self.returns: list[tuple[str, str | None, ast.Return]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(("class", node.name))
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(("function", node.name))
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def _record(self, node: ast.Assign | ast.AnnAssign) -> None:
        class_name = self.scope[0][1] if self.scope and self.scope[0][0] == "class" else None
        self.assignments.append((_scope_anchor(self.scope), class_name, node))
        self.generic_visit(node)

    visit_Assign = _record
    visit_AnnAssign = _record

    def visit_Call(self, node: ast.Call) -> None:
        class_name = self.scope[0][1] if self.scope and self.scope[0][0] == "class" else None
        if class_name and _attr_chain(node.func, unwrap_calls=True).endswith(".__init__"):
            self.constructor_keywords.extend(
                (_scope_anchor(self.scope), class_name, f"self.{keyword.arg}", keyword.value)
                for keyword in node.keywords
                if keyword.arg in {"api_url", "base_url", "endpoint"}
            )
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        class_name = self.scope[0][1] if self.scope and self.scope[0][0] == "class" else None
        self.returns.append((_scope_anchor(self.scope), class_name, node))
        self.generic_visit(node)


def _url_bindings(tree: ast.AST) -> dict[tuple[str, str], set[str]]:
    collector = _UrlAssignmentCollector()
    collector.visit(tree)
    bindings: dict[tuple[str, str], set[str]] = {}
    for _ in range(4):
        for anchor, class_name, return_node in collector.returns:
            if return_node.value is not None:
                bindings.setdefault((anchor, "<return>"), set()).update(
                    _url_values(return_node.value, bindings, anchor, class_name)
                )
        for anchor, class_name, target, value in collector.constructor_keywords:
            bindings.setdefault((anchor, target), set()).update(
                _url_values(value, bindings, anchor, class_name)
            )
        for anchor, class_name, assignment in collector.assignments:
            if assignment.value is None:
                continue
            values = _url_values(assignment.value, bindings, anchor, class_name)
            for target in _targets(assignment):
                bindings.setdefault((anchor, target), set()).update(values)
                if class_name and anchor == class_name and "." not in target:
                    bindings.setdefault((class_name, f"self.{target}"), set()).update(values)
    return bindings


class _InferenceVisitor(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.AST) -> None:
        self.path = path
        self.scope: list[tuple[str, str]] = []
        self.detections: list[tuple[SiteKey, str]] = []
        self.mentions_policy = False
        self.constructor_aliases = _constructor_aliases(tree)
        self.module_aliases = _sdk_module_aliases(tree)
        self.client_receivers, self.client_factories = _client_provenance(
            tree, self.constructor_aliases, self.module_aliases
        )
        self.url_bindings = _url_bindings(tree)
        policy_types = {"ModelTransportPolicy"} | {alias.asname or alias.name for item in ast.walk(tree) if isinstance(item, ast.ImportFrom) for alias in item.names if alias.name == "ModelTransportPolicy"}  # fmt: skip
        self.policy_receivers = {item.arg for item in ast.walk(tree) if isinstance(item, ast.arg) and item.annotation is not None and _attr_chain(item.annotation).rsplit(".", 1)[-1] in policy_types}  # fmt: skip
        self.policy_receivers.update(target for item in ast.walk(tree) if isinstance(item, (ast.Assign, ast.AnnAssign)) and item.value is not None and isinstance(item.value, ast.Call) and _attr_chain(item.value.func).split(".", 1)[0] in policy_types for target in _targets(item))  # fmt: skip
        self.policy_receivers.update(target for item in ast.walk(tree) if isinstance(item, (ast.Assign, ast.AnnAssign)) and item.value is not None and isinstance(item.value, ast.Attribute) and any(_attr_chain(item.value) == f"{receiver}.client" for receiver in tuple(self.policy_receivers)) for target in _targets(item))  # fmt: skip

    def _anchor(self) -> str:
        return _scope_anchor(self.scope)

    def _record(self, provider: str, protocol: str, detector: str) -> None:
        self.detections.append((SiteKey(self.path, self._anchor(), provider, protocol), detector))

    def _has_client(self, receiver: str) -> bool:
        prefixes = tuple(f"{client}." for client in self.client_receivers)
        rooted = receiver in self.client_receivers or receiver.startswith(prefixes)
        terminal = receiver.rsplit(".", 1)[-1]
        known = self.client_factories | self.constructor_aliases.keys()
        return rooted or receiver in known or (terminal in known and (terminal != "Client" or "." not in receiver))  # fmt: skip

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(("class", node.name))
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(("function", node.name))
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "ModelTransportPolicy":
            self.mentions_policy = True
        chain = _attr_chain(node, unwrap_calls=True)
        for suffix, provider, protocol in METHOD_SUFFIXES:
            receiver = chain[: -len(suffix)].rstrip(".")
            if chain.endswith(suffix) and self._has_client(receiver):
                self._record(provider, protocol, "inference-method")
                break
        if any(chain.startswith(f"{receiver}.") and chain.endswith(("generate_anthropic", "anthropic_message")) for receiver in self.policy_receivers):  # fmt: skip
            self._record("anthropic", "messages", "transport-policy-call")
        if any(chain.startswith(f"{receiver}.") and chain.endswith(("openai_request", "openai_catalog_alias_request")) for receiver in self.policy_receivers):  # fmt: skip
            self._record("openai-compatible", "chat", "transport-policy-call")
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        provider = _provider_for_url(node.value)
        if provider is not None:
            self._record(provider, _protocol_for_url(node.value), "endpoint-literal")

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        value = "".join(
            str(part.value) if isinstance(part, ast.Constant) else "{}" for part in node.values
        )
        provider = _provider_for_url(value)
        if provider is not None:
            self._record(provider, _protocol_for_url(value), "endpoint-literal")
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if any(alias.name == "ModelTransportPolicy" for alias in node.names):
            self.mentions_policy = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        chain = _attr_chain(node.func, unwrap_calls=True)
        terminal = chain.rsplit(".", 1)[-1]
        constructor = _dynamic_constructor(node, self.module_aliases) or self.constructor_aliases.get(chain) or (self.constructor_aliases.get(terminal) if terminal != "Client" or "." not in chain else None)  # fmt: skip
        if constructor is not None:
            self._record(*constructor, "client-constructor")
        if terminal in HTTP_CALL_TERMINALS:
            candidates = (*node.args, *(keyword.value for keyword in node.keywords))
            class_name = self.scope[0][1] if self.scope and self.scope[0][0] == "class" else None
            endpoints = {
                (provider, protocol)
                for candidate in candidates
                for value in _url_values(candidate, self.url_bindings, self._anchor(), class_name)
                if (provider := _provider_for_http_endpoint(value, f"{self._anchor()} {ast.unparse(candidate)}")) is not None
                if (protocol := _protocol_for_url(value)) != "base"
            }
            for provider, protocol in endpoints:
                self._record(provider, protocol, "http-inference-call")
        self.generic_visit(node)


def _js_constructor_end(source: str, start: int) -> int | None:
    depth = 1
    for index, char in enumerate(source[start:], start):
        depth += (char == "(") - (char == ")")
        if depth == 0:
            return index + 1
    return None


def _js_endpoint_value(raw: str, bindings: dict[str, str] | None = None) -> str:
    if raw[:1] in {'"', "'", "`"} and raw[-1:] == raw[:1]:
        raw = raw[1:-1]
    if bindings:
        raw = JS_TEMPLATE_IDENTIFIER_RE.sub(
            lambda match: bindings.get(match.group(1), "{}"), raw
        )
    return re.sub(r"\$\{.*?\}", "{}", raw)


def _js_http_endpoints(source: str, path: str = "") -> tuple[tuple[str, str], ...]:
    bindings: dict[str, str] = {}
    for name, value in JS_VALUE_ASSIGN_RE.findall(source):
        bindings[name] = _js_endpoint_value(value, bindings)
    endpoints: list[tuple[str, str]] = []
    for raw in JS_HTTP_CALL_RE.findall(source):
        value = bindings.get(raw, _js_endpoint_value(raw, bindings))
        provider = _provider_for_http_endpoint(value, f"{path} {raw}")
        protocol = _protocol_for_url(value)
        if provider is not None and protocol != "base":
            endpoints.append((provider, protocol))
    return tuple(endpoints)


def iter_scan_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for relative in SCAN_ROOTS
            for path in (root / relative).rglob("*")
            if path.is_file()
            and path.suffix in TEXT_SUFFIXES
            and path.name not in SCAN_EXCLUDED_NAMES
            and ".generated." not in path.name
            and not SCAN_EXCLUDED_DIRS.intersection(path.parts)
            and not any(marker in path.name for marker in (".test.", ".spec."))
            and path.relative_to(root).as_posix() != SELF_PATH
        )
    )


def discover(root: Path = REPO_ROOT) -> Discovery:
    grouped: dict[SiteKey, Counter[str]] = {}
    policy_consumers: set[str] = set()
    forbidden_ports: list[str] = []
    scan_errors: list[str] = []
    files = iter_scan_files(root)
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            scan_errors.append(f"{relative}: {type(exc).__name__}: {exc}")
            continue
        if path.suffix in JS_SUFFIXES:
            source = JS_COMMENT_RE.sub(lambda match: match.group(1) or "\n" * match.group(0).count("\n"), source)  # fmt: skip
        source_lines = source.splitlines()
        if path.suffix != ".py":
            js_aliases = dict(JS_CONSTRUCTORS) if path.suffix in JS_SUFFIXES else {}
            for pattern, default, provider in JS_IMPORTS:
                js_aliases.update({alias or default: provider for alias in re.findall(pattern, source)})
            js_structure = JS_CODE_STRING_RE.sub('""', source) if js_aliases else ""
            js_clients = {provider: (tuple(constructor for constructor, family in js_aliases.items() if family == provider), {client for constructor, family in js_aliases.items() if family == provider for client in (*re.findall(rf"(?<![\w$#])((?:this\.)?#?[A-Za-z_$][\w$]*(?:\.#?[A-Za-z_$][\w$]*)*)\s*(?:\s*:\s*[^=;\n]+)?=\s*new\s+{re.escape(constructor)}\s*\(", js_structure), *re.findall(rf"(?<![\w$#])((?:this\.)?#?[A-Za-z_$][\w$]*(?:\.#?[A-Za-z_$][\w$]*)*)\s*\??\s*:\s*{re.escape(constructor)}\b", js_structure))}) for provider in set(js_aliases.values())}  # fmt: skip
            js_compact = re.sub(r"\s+", "", js_structure)
            for suffix, provider, protocol in METHOD_SUFFIXES:
                constructors, clients = js_clients.get(provider, ((), set()))
                suffix_pattern = r"\s*\.\s*".join(re.escape(part) for part in suffix.split("."))
                count = sum(len(re.findall(rf"(?<![\w$]){re.escape(client)}\.{re.escape(suffix)}", js_compact)) for client in clients) + sum(1 for constructor in constructors for match in re.finditer(rf"\bnew\s+{re.escape(constructor)}\s*\(", js_structure) if (end := _js_constructor_end(js_structure, match.end())) is not None and re.match(rf"\s*\.\s*{suffix_pattern}", js_structure[end:]))  # fmt: skip
                if count:
                    grouped.setdefault(SiteKey(relative, "<file>", provider, protocol), Counter())["inference-method"] += count  # fmt: skip
            for provider, protocol in _js_http_endpoints(source, relative):
                grouped.setdefault(SiteKey(relative, "<file>", provider, protocol), Counter())["http-inference-call"] += 1  # fmt: skip
            for line_no, line in enumerate(source_lines, 1):
                content = line if path.suffix in JS_SUFFIXES else line.split("#", 1)[0]
                if re.search(r"(?<!\d)0*8317(?!\d)", content):
                    forbidden_ports.append(f"{relative}:{line_no}")
                for provider in _providers_for_urls(content):
                    key = SiteKey(relative, "<file>", provider, _protocol_for_url(content))
                    grouped.setdefault(key, Counter())["endpoint-literal"] += 1
            continue
        for line_no, line in enumerate(source_lines, 1):
            if FORBIDDEN_PORT_RE.search(line):
                forbidden_ports.append(f"{relative}:{line_no}")
        lowered_source = source.lower()
        if not any(
            needle in lowered_source for needle in PYTHON_AST_NEEDLES
        ) and not _may_contain_python_numeric_port_literal(source):
            continue
        try:
            tree = ast.parse(source, filename=relative)
        except SyntaxError as exc:
            scan_errors.append(f"{relative}: SyntaxError: {exc}")
            continue
        for node in ast.walk(tree):
            string_value = (
                node.value.decode("ascii", errors="ignore")
                if isinstance(node, ast.Constant) and isinstance(node.value, bytes)
                else node.value
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                else None
            )
            if (
                isinstance(node, ast.Constant)
                and string_value is not None
                and (
                    re.fullmatch(r"0*8317", string_value)
                    or PORT_STRING_RE.search(string_value)
                )
                and not FORBIDDEN_PORT_RE.search(string_value)
            ):
                forbidden_ports.append(f"{relative}:{node.lineno}")
            if not (
                isinstance(node, ast.Constant)
                and node.value == 8317
                and not isinstance(node.value, bool)
            ):
                continue
            line = source_lines[node.lineno - 1].strip()
            if relative == PORT_ENFORCEMENT_PATH and line == PORT_ENFORCEMENT_LINE:
                continue
            forbidden_ports.append(f"{relative}:{node.lineno}")
        visitor = _InferenceVisitor(relative, tree)
        visitor.visit(tree)
        if visitor.mentions_policy and relative != "aragora/agents/transports/vibeproxy.py":
            policy_consumers.add(relative)
        for key, detector in visitor.detections:
            grouped.setdefault(key, Counter())[detector] += 1
    sites = tuple(
        Site(
            path=key.path,
            anchor=key.anchor,
            provider=key.provider,
            protocol=key.protocol,
            detectors=dict(sorted(detectors.items())),
        )
        for key, detectors in sorted(grouped.items())
    )
    return Discovery(
        sites=sites,
        scanned_files=len(files),
        raw_detections=sum(sum(site.detectors.values()) for site in sites),
        policy_consumers=tuple(sorted(policy_consumers)),
        forbidden_ports=tuple(forbidden_ports),
        scan_errors=tuple(scan_errors),
    )


def protected_reasons(path: str) -> tuple[str, ...]:
    return tuple(
        reason
        for reason, patterns in PROTECTED_PATHS.items()
        if any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
    )


def _key_text(key: SiteKey) -> str:
    return f"{key.path}::{key.anchor}::{key.provider}::{key.protocol}"


def _site_from_manifest(raw: Any, index: int, errors: list[str]) -> tuple[Site, str] | None:
    if not isinstance(raw, dict):
        errors.append(f"sites[{index}] must be an object")
        return None
    required = ("path", "anchor", "provider", "protocol", "detectors", "classification")
    if any(name not in raw for name in required):
        errors.append(f"sites[{index}] is missing required fields")
        return None
    classification = raw["classification"]
    if classification not in CLASSIFICATIONS:
        errors.append(f"sites[{index}] has invalid classification {classification!r}")
    rationale = raw.get("rationale", "")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append(f"sites[{index}] {classification} entry needs a rationale")
    detectors = raw["detectors"]
    if not isinstance(detectors, dict) or not detectors:
        errors.append(f"sites[{index}] detectors must be a non-empty object")
        return None
    normalized: dict[str, int] = {}
    for name, count in detectors.items():
        if not isinstance(name, str) or not isinstance(count, int) or count < 1:
            errors.append(f"sites[{index}] detector counts must be positive integers")
            continue
        normalized[name] = count
    if classification == "proxy-eligible" and not normalized.get("transport-policy-call"):
        errors.append(f"sites[{index}] proxy-eligible needs transport-policy-call")
    direct_detectors = sorted(DIRECT_CALL_DETECTORS.intersection(normalized))
    if classification == "proxy-eligible" and direct_detectors:
        errors.append(
            f"sites[{index}] proxy-eligible cannot include direct-call detectors: "
            + ", ".join(direct_detectors)
        )
    values = [raw[name] for name in required[:4]]
    if not all(isinstance(value, str) and value for value in values):
        errors.append(f"sites[{index}] identity fields must be non-empty strings")
        return None
    return (
        Site(
            path=str(raw["path"]),
            anchor=str(raw["anchor"]),
            provider=str(raw["provider"]),
            protocol=str(raw["protocol"]),
            detectors=normalized,
        ),
        classification,
    )


def load_manifest(path: Path) -> tuple[dict[SiteKey, tuple[Site, str]], tuple[str, ...], list[str]]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, (), [f"cannot read manifest: {exc}"]
    if _contains_forbidden_port(payload):
        errors.append("manifest must not contain forbidden port 8317")
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return {}, (), ["manifest schema_version must be 1"]
    raw_consumers = payload.get("transport_policy_consumers")
    if not isinstance(raw_consumers, list) or not all(
        isinstance(item, str) and item for item in raw_consumers
    ):
        errors.append("transport_policy_consumers must be a list of paths")
        consumers: tuple[str, ...] = ()
    else:
        consumers = tuple(sorted(set(raw_consumers)))
    entries: dict[SiteKey, tuple[Site, str]] = {}
    raw_sites = payload.get("sites")
    if not isinstance(raw_sites, list):
        return {}, consumers, errors + ["sites must be a list"]
    for index, raw in enumerate(raw_sites):
        parsed = _site_from_manifest(raw, index, errors)
        if parsed is None:
            continue
        site, classification = parsed
        if site.key in entries:
            errors.append(f"duplicate site {_key_text(site.key)}")
        entries[site.key] = (site, classification)
        reasons = protected_reasons(site.path)
        if reasons and classification != "direct-only":
            errors.append(
                f"protected site {_key_text(site.key)} must be direct-only ({', '.join(reasons)})"
            )
        if classification == "proxy-eligible" and site.path not in consumers:
            errors.append(f"proxy-eligible site {_key_text(site.key)} is not a policy consumer")
    return entries, consumers, errors


def check_allowlist(root: Path = REPO_ROOT, manifest_path: Path = DEFAULT_MANIFEST) -> CheckResult:
    discovery = discover(root)
    expected, expected_consumers, manifest_errors = load_manifest(manifest_path)
    actual = {site.key: site for site in discovery.sites}
    unclassified = tuple(_key_text(key) for key in sorted(actual.keys() - expected.keys()))
    stale = tuple(_key_text(key) for key in sorted(expected.keys() - actual.keys()))
    changed = tuple(
        f"{_key_text(key)} expected={expected[key][0].detectors} actual={actual[key].detectors}"
        for key in sorted(actual.keys() & expected.keys())
        if actual[key].detectors != expected[key][0].detectors
    )
    policy_errors: list[str] = []
    if discovery.policy_consumers != expected_consumers:
        policy_errors.append(
            "transport policy consumers differ: "
            f"expected={list(expected_consumers)} actual={list(discovery.policy_consumers)}"
        )
    violations = (
        unclassified,
        stale,
        changed,
        manifest_errors,
        policy_errors,
        discovery.forbidden_ports,
        discovery.scan_errors,
    )
    ok = not any(violations)
    return CheckResult(
        ok=ok,
        scanned_files=discovery.scanned_files,
        site_count=len(discovery.sites),
        raw_detections=discovery.raw_detections,
        policy_consumers=discovery.policy_consumers,
        unclassified=unclassified,
        stale=stale,
        changed=changed,
        manifest_errors=tuple(manifest_errors),
        policy_errors=tuple(policy_errors),
        forbidden_ports=discovery.forbidden_ports,
        scan_errors=discovery.scan_errors,
    )


def template_manifest(discovery: Discovery) -> dict[str, Any]:
    sites: list[dict[str, Any]] = []
    for site in discovery.sites:
        reasons = protected_reasons(site.path)
        rationale = (
            f"protected {', '.join(reasons)} surface remains direct by issue #9409"
            if reasons
            else "not yet routed through the central exact-match transport policy"
        )
        sites.append(
            {
                **asdict(site),
                "classification": "direct-only",
                "rationale": rationale,
            }
        )
    return {
        "generated_by": "scripts/check_inference_site_allowlist.py --emit-template",
        "policy_note": "Template output defaults to direct-only; preserve reviewed classifications and rationales.",
        "schema_version": 1,
        "transport_policy_consumers": list(discovery.policy_consumers),
        "sites": sites,
    }


def _print_human(result: CheckResult) -> None:
    if result.ok:
        print(
            "inference-site allowlist: ok "
            f"({result.site_count} sites, {result.raw_detections} detections, "
            f"{result.scanned_files} files)"
        )
        return
    print("inference-site allowlist: violations found")
    for label in (
        "manifest_errors",
        "policy_errors",
        "unclassified",
        "stale",
        "changed",
        "forbidden_ports",
        "scan_errors",
    ):
        for value in getattr(result, label):
            print(f"  {label}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results.")
    parser.add_argument(
        "--emit-template",
        action="store_true",
        help="Print a candidate manifest; never writes the reviewed file.",
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    if args.emit_template:
        print(json.dumps(template_manifest(discover(args.root)), indent=2, sort_keys=True))
        return 0
    result = check_allowlist(args.root, args.manifest)
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        _print_human(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
