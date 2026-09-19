from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_module() -> Any:
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_inference_site_allowlist.py"
    spec = importlib.util.spec_from_file_location("inference_site_allowlist_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_module()


def test_repository_manifest_matches_current_tree() -> None:
    result = checker.check_allowlist()
    payload = json.loads(checker.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert result.ok is True, result
    assert result.policy_consumers == (
        "aragora/agents/api_agents/openai.py",
        "aragora/agents/transports/claude_vibeproxy.py",
        "aragora/swarm/quorum_evidence.py",
        "scripts/consult_claude.py",
        "scripts/prepare_claude_code_vibeproxy_review.py",
        "scripts/vibeproxy_burnin_recorder.py",
    )
    assert [
        (site["path"], site["anchor"])
        for site in payload["sites"]
        if site["classification"] == "proxy-eligible"
    ] == [
        ("aragora/agents/api_agents/openai.py", "OpenAIAPIAgent.generate"),
        ("aragora/agents/transports/claude_vibeproxy.py", "run_claude_vibeproxy"),
        ("scripts/consult_claude.py", "_run_vibeproxy"),
        ("scripts/vibeproxy_burnin_recorder.py", "run_inference"),
        ("scripts/vibeproxy_burnin_recorder.py", "run_inference"),
    ]


def _write_source(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _write_manifest(root: Path, payload: dict[str, Any]) -> Path:
    path = root / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _template(root: Path) -> dict[str, Any]:
    return checker.template_manifest(checker.discover(root))


def _empty_manifest(root: Path) -> Path:
    return _write_manifest(root, {"schema_version": 1, "transport_policy_consumers": [], "sites": []})  # fmt: skip


@pytest.mark.parametrize(
    "relative",
    ["aragora/swarm/quorum_evidence.py", "scripts/prepare_claude_code_vibeproxy_review.py"],
)
def test_review_policy_consumer_requires_explicit_registration(
    tmp_path: Path, relative: str
) -> None:
    _write_source(
        tmp_path,
        relative,
        "from aragora.agents.transports.vibeproxy import ModelTransportPolicy\n"
        "policy = ModelTransportPolicy.from_env()\n",
    )
    payload = _template(tmp_path)
    assert payload["transport_policy_consumers"] == [relative]
    assert payload["sites"] == []
    assert checker.check_allowlist(tmp_path, _write_manifest(tmp_path, payload)).ok

    payload["transport_policy_consumers"] = []
    missing = checker.check_allowlist(tmp_path, _write_manifest(tmp_path, payload))
    assert not missing.ok
    assert missing.policy_consumers == (relative,)
    assert len(missing.policy_errors) == 1
    assert "transport policy consumers differ" in missing.policy_errors[0]
    assert missing.manifest_errors == ()


def test_discovery_groups_by_stable_symbol_anchor(tmp_path: Path) -> None:
    source = """from openai import AsyncOpenAI
class Runner:
    async def generate(self):
        client = AsyncOpenAI()
        return await client.chat.completions.create(model="gpt", messages=[])
"""
    path = _write_source(tmp_path, "aragora/runner.py", source)
    first = checker.discover(tmp_path)
    path.write_text("\n\n\n" + source, encoding="utf-8")
    second = checker.discover(tmp_path)
    assert first.sites == second.sites and first.raw_detections == 2
    assert {site.anchor for site in first.sites} == {"Runner.generate"}


@pytest.mark.parametrize("module,name", [("openai", "OpenAI"), ("anthropic", "Anthropic")])
def test_discovery_finds_aliased_constructors(tmp_path: Path, module: str, name: str) -> None:
    _write_source(tmp_path, "aragora/run.py", f"from {module} import {name} as Client\nClient()\n")
    assert checker.discover(tmp_path).sites[0].provider in {"openai-compatible", "anthropic"}


def test_discovery_finds_getattr_sdk_constructors_with_module_provenance(
    tmp_path: Path,
) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """import openai as oai
import anthropic
openai_client = getattr(oai, "OpenAI")()
openai_client.responses.create()
claude_client = getattr(anthropic, "Anthropic")()
claude_client.messages.create()
unrelated = getattr(other, "OpenAI")()
unrelated.responses.create()
""",
    )
    sites = checker.discover(tmp_path).sites
    assert {(site.provider, site.protocol) for site in sites} == {
        ("anthropic", "client"),
        ("anthropic", "messages"),
        ("openai-compatible", "client"),
        ("openai-compatible", "responses"),
    }


def test_discovery_finds_native_mistral_sdk_calls(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """from mistralai import Mistral as MistralClient
client = MistralClient(api_key="key")
client.chat.complete(model="mistral-large", messages=[])
client.fim.complete(model="codestral", prompt="pass")
unrelated.chat.complete(model="not-mistral", messages=[])
""",
    )
    sites = checker.discover(tmp_path).sites
    assert {(site.provider, site.protocol) for site in sites} == {
        ("mistral", "chat"),
        ("mistral", "client"),
        ("mistral", "completions"),
    }


def test_bare_mistral_types_reach_ast_discovery(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """def run(client: Mistral):
    client.chat.complete(model="mistral-large", messages=[])
""",
    )
    sites = checker.discover(tmp_path).sites
    assert [(site.provider, site.protocol) for site in sites] == [("mistral", "chat")]


def test_modern_gemini_camel_case_calls_reach_ast_discovery(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """from google import genai
client = genai.Client()
client.models.generateContent("hello")
""",
    )
    sites = checker.discover(tmp_path).sites
    assert {(site.provider, site.protocol) for site in sites} == {
        ("gemini", "client"),
        ("gemini", "generate-content"),
    }


def test_method_detection_uses_sdk_provenance(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """import asyncio, openai, openai as oai, google.generativeai as genai; from google import genai as modern_genai; from google.genai import Client as GeminiClient; from anthropic import Anthropic
async def run(api: openai.OpenAI):
    await asyncio.to_thread(api.responses.create); api.responses.stream()
client_store.responses.create(); openai.chat.completions.create(); oai.responses.create(); modern = modern_genai.Client(); modern.models.generate_content("hi"); modern.models.generate_content_stream("hi"); direct = GeminiClient(); direct.models.generate_content("hi"); Other.Client().models.generate_content("ignore"); anthropic = Anthropic(); anthropic.messages.stream(model="claude", messages=[])
openai.OpenAI().responses.create()
genai.GenerativeModel().generate_content("hello")
""",
    )
    discovery = checker.discover(tmp_path)
    assert discovery.raw_detections == 15 and {site.protocol for site in discovery.sites} == {"client", "chat", "responses", "messages", "generate-content"}  # fmt: skip


def test_raw_http_calls_follow_provider_url_bindings(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """import requests
OPENAI_API_URL = "https://api.openai.com/v1"
def run():
    requests.post(f"{OPENAI_API_URL}/chat/completions", json={})
    requests.post("https://example.com/v1/chat/completions", json={})
""",
    )
    discovery = checker.discover(tmp_path)
    site = next(site for site in discovery.sites if site.anchor == "run")
    assert (site.provider, site.protocol, site.detectors) == (
        "openai",
        "chat",
        {"http-inference-call": 1},
    )


def test_tinker_sample_http_calls_use_contextual_provider_provenance(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/training/tinker_client.py",
        """class TinkerClient:
    async def sample(self, client):
        await client.post("/sample", json={})
    async def sample_stream(self, client):
        async with client.stream("POST", "/sample", json={}):
            pass
class Sampler:
    async def sample(self, client):
        await client.post("/sample", json={})
""",
    )
    sites = checker.discover(tmp_path).sites
    assert {
        (site.anchor, site.provider, site.protocol, tuple(site.detectors.items())) for site in sites
    } == {
        ("TinkerClient.sample", "tinker", "sample", (("http-inference-call", 1),)),
        (
            "TinkerClient.sample_stream",
            "tinker",
            "sample",
            (("http-inference-call", 1),),
        ),
    }


def test_raw_http_url_bindings_do_not_cross_class_scopes(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """class Kimi:
    def __init__(self): self.base_url = "https://api.moonshot.cn/v1"
    def run(self, client): client.post(f"{self.base_url}/chat/completions")
class OpenRouter:
    def __init__(self): self.base_url = "https://openrouter.ai/api/v1"
    def run(self, client): client.post(f"{self.base_url}/chat/completions")
""",
    )
    discovery = checker.discover(tmp_path)
    assert {
        (site.anchor, site.provider) for site in discovery.sites if site.protocol == "chat"
    } == {
        ("Kimi.run", "kimi"),
        ("OpenRouter.run", "openrouter"),
    }


def test_raw_http_url_bindings_do_not_cross_method_scopes(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """class Router:
    def kimi(self, client):
        self.base_url = "https://api.moonshot.cn/v1"
        client.post(f"{self.base_url}/chat/completions")
    def openrouter(self, client):
        self.base_url = "https://openrouter.ai/api/v1"
        client.post(f"{self.base_url}/chat/completions")
""",
    )
    discovery = checker.discover(tmp_path)
    assert {
        (site.anchor, site.provider) for site in discovery.sites if site.protocol == "chat"
    } == {
        ("Router.kimi", "kimi"),
        ("Router.openrouter", "openrouter"),
    }


def test_raw_http_calls_follow_dynamic_instance_and_helper_endpoints(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/run.py",
        """def resolve_base_url(env_name, default):
    return default
class AnthropicAgent:
    def __init__(self):
        super().__init__(base_url=resolve_base_url("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"))
    async def generate(self, session):
        url = f"{self.base_url}/messages"
        await session.post(url)
class CompatibleAgent:
    def _get_endpoint_url(self):
        return f"{self.base_url}/chat/completions"
    async def generate(self, session):
        url = self._get_endpoint_url()
        await session.post(url)
class DynamicAnthropicAgent:
    async def generate(self, session, base_url):
        await session.post(f"{base_url}/messages")
class HelperAnthropicAgent:
    async def generate(self, session, base_url):
        await session.post(build_url(base_url, "/messages"))
class MessagingClient:
    async def send(self, session):
        await session.post(f"{self.base_url}/messages")
""",
    )
    sites = checker.discover(tmp_path).sites
    assert {
        (site.anchor, site.provider, site.protocol, site.detectors.get("http-inference-call"))
        for site in sites
        if "http-inference-call" in site.detectors
    } == {
        ("AnthropicAgent.generate", "anthropic", "messages", 1),
        ("CompatibleAgent.generate", "openai-compatible", "chat", 1),
        ("DynamicAnthropicAgent.generate", "anthropic", "messages", 1),
        ("HelperAnthropicAgent.generate", "anthropic", "messages", 1),
    }


def test_javascript_sdk_property_receivers_are_discovered(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/live/src/run.ts",
        """import OpenAIClient from "openai"
class Runner {
  client = new OpenAIClient()
  run() { this.client.responses.create({}) }
}
const holder = {}
holder.client = new OpenAIClient()
holder.client.chat.completions.create({})
this.embedder = new OpenAIClient()
this.embedder.embeddings.create({})
this.#privateClient = new OpenAIClient()
this.#privateClient.completions.create({})
""",
    )
    sites = checker.discover(tmp_path).sites
    assert {(site.provider, site.protocol) for site in sites} == {
        ("openai-compatible", "chat"),
        ("openai-compatible", "completions"),
        ("openai-compatible", "embeddings"),
        ("openai-compatible", "responses"),
    }


def test_javascript_typed_sdk_receivers_are_discovered(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/live/src/run.ts",
        """import OpenAIClient from "openai"
import { Anthropic as ClaudeClient } from "@anthropic-ai/sdk"
function run(client: OpenAIClient, claude: ClaudeClient) {
  client.chat.completions.create({})
  claude.messages.create({})
  untyped.responses.create({})
}
""",
    )
    sites = checker.discover(tmp_path).sites
    assert {(site.provider, site.protocol) for site in sites} == {
        ("anthropic", "messages"),
        ("openai-compatible", "chat"),
    }


def test_javascript_raw_http_calls_follow_dynamic_url_bindings(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/live/src/run.ts",
        """const chatUrl = `${baseUrl}/chat/completions`
fetch<ChatResponse>(chatUrl)
axios.post<Response<Payload>>(`${baseUrl}/responses`, {})
const anthropicBase = "https://api.anthropic.com/v1"
fetch(`${anthropicBase}/messages`)
const dynamicAnthropicMessages = `${anthropicUrl}/messages`
fetch(dynamicAnthropicMessages)
const ordinaryMessages = `${baseUrl}/messages`
client.request<MessageResponse>(ordinaryMessages)
""",
    )
    sites = checker.discover(tmp_path).sites
    assert {(site.provider, site.protocol, tuple(site.detectors)) for site in sites} == {
        ("anthropic", "base", ("endpoint-literal",)),
        ("anthropic", "messages", ("http-inference-call",)),
        ("openai-compatible", "chat", ("http-inference-call",)),
        ("openai-compatible", "responses", ("http-inference-call",)),
    }
    assert (
        next(
            site for site in sites if site.provider == "anthropic" and site.protocol == "messages"
        ).detectors["http-inference-call"]
        == 2
    )


def test_javascript_template_literal_sdk_lookalikes_are_ignored(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/live/src/run.ts",
        'import OpenAI from "openai"\nconst client = new OpenAI()\nconst text = `client.responses.create({})`\n',
    )
    sites = checker.discover(tmp_path).sites
    assert sites == ()


def test_commonjs_sdk_aliases_are_discovered(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/live/src/run.cjs",
        """const OpenAIClient = require("openai")
const { Anthropic: ClaudeClient } = require("@anthropic-ai/sdk")
const { default: GeminiClient } = require("@google/genai")
const openai = new OpenAIClient()
openai.chat.completions.create({})
const claude = new ClaudeClient()
claude.messages.create({})
const gemini = new GeminiClient()
gemini.models.generateContent({})
""",
    )
    assert {(site.provider, site.protocol) for site in checker.discover(tmp_path).sites} == {
        ("anthropic", "messages"),
        ("gemini", "generate-content"),
        ("openai-compatible", "chat"),
    }


def test_discovery_finds_urls_methods_and_transport_policy_calls(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "scripts/consult_claude.py",
        """from somewhere import ModelTransportPolicy as MTP
ANTHROPIC = "https://api.anthropic.com/v1/messages"
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
def consult(policy: MTP):
    other.anthropic_message(model="fake"); assigned = MTP.from_env(); assigned.client.anthropic_message(model="claude"); assigned.client.openai_catalog_alias_request(model="gpt"); return policy.generate_anthropic(model="claude", messages=[])
""",
    )
    # fmt: off
    _write_source(tmp_path, "aragora/live/src/run.tsx", 'import OpenAIClient from "openai"\nimport { Anthropic as ClaudeClient } from "@anthropic-ai/sdk"\nimport { GoogleGenAI as GeminiClient } from "@google/genai"\nurls = ["https://api.openai.com/v1/responses",\n "https://api.mistral.ai/v1",\n "https://api.deepseek.com/v1",\n "https://api.moonshot.cn/v1",\n "https://api.thinkingmachines.ai/v1/*quoted*/"]\nthis.#endpoint = "https://api.x.ai/v1"\nconst ai = new OpenAI()\nai.chat\n .completions.create({})\nnew OpenAI({ apiKey: getKey() }).embeddings.create({})\nconst alias = new OpenAIClient()\nalias.responses.create({})\nconst fake = "alias.completions.create({})"\nconst claude = new ClaudeClient()\nclaude.messages.create({})\nconst gemini = new GeminiClient()\ngemini.models.generateContent({})\nunproven.responses.create({})\n// https://api.x.ai/v1/commented\n/*\nhttps://generativelanguage.googleapis.com/v1\n*/\n')
    discovery = checker.discover(tmp_path)
    assert discovery.policy_consumers == ("scripts/consult_claude.py",)
    assert {(site.provider, site.protocol) for site in discovery.sites} == {("anthropic", "messages"), ("deepseek", "base"), ("gemini", "generate-content"), ("kimi", "base"), ("mistral", "base"), ("openai", "responses"), ("openai-compatible", "chat"), ("openai-compatible", "embeddings"), ("openai-compatible", "responses"), ("openrouter", "chat"), ("tinker", "base"), ("xai", "base")}
    assert {(site.provider, site.protocol) for site in discovery.sites if site.path.endswith("run.tsx")} >= {("anthropic", "messages"), ("gemini", "generate-content"), ("openai-compatible", "chat"), ("openai-compatible", "embeddings"), ("openai-compatible", "responses")}
    assert next(site for site in discovery.sites if site.provider == "openai-compatible" and site.protocol == "responses").detectors == {"inference-method": 1}
    # fmt: on
    assert sum(site.detectors.get("transport-policy-call", 0) for site in discovery.sites) == 3
    payload = _template(tmp_path)
    assert {site["classification"] for site in payload["sites"]} == {"direct-only"}
    payload["sites"][0]["classification"] = "proxy-eligible"
    payload["transport_policy_consumers"] = []
    result = checker.check_allowlist(tmp_path, _write_manifest(tmp_path, payload))
    assert result.policy_errors and len(result.manifest_errors) >= 2


@pytest.mark.parametrize(
    "relative",
    ["aragora/run.py", "aragora/run.ts", "scripts/config.json", ".github/config.yml"],
)
def test_provider_hosts_require_exact_normalized_url_hostnames(
    tmp_path: Path, relative: str
) -> None:
    _write_source(
        tmp_path,
        relative,
        """URLS = [
    "https://api.openai.com.evil.example/v1/responses",
    "https://evil.example/?next=api.anthropic.com/v1/messages",
    "https://api.openai.com/v1/responses",
]
""",
    )
    sites = checker.discover(tmp_path).sites
    assert [(site.provider, site.protocol) for site in sites] == [("openai", "responses")]


def test_scan_excludes_generated_lock_and_baseline_artifacts(tmp_path: Path) -> None:
    ignored = (
        "aragora/live/src/types/api.generated.ts",
        "aragora/live/package-lock.json",
        "aragora/live/src/api/generated/client.ts",
        "scripts/baselines/inventory.json",
    )
    for relative in ignored:
        _write_source(tmp_path, relative, 'URL = "https://api.openai.com/v1/responses"\n')
    _write_source(
        tmp_path, "aragora/live/src/run.ts", 'URL = "https://api.openai.com/v1/responses"\n'
    )
    discovery = checker.discover(tmp_path)
    assert discovery.scanned_files == 1
    assert [(site.path, site.provider, site.protocol) for site in discovery.sites] == [
        ("aragora/live/src/run.ts", "openai", "responses")
    ]


def test_scan_skips_ast_for_irrelevant_python_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(100):
        _write_source(tmp_path, f"aragora/module_{index}.py", f"VALUE = {index}\n")
    _write_source(
        tmp_path,
        "aragora/inference.py",
        'URL = "https://api.openai.com/v1/responses"\n',
    )
    real_parse = checker.ast.parse
    parsed: list[str] = []

    def tracking_parse(source: str, *, filename: str) -> ast.AST:
        parsed.append(filename)
        return real_parse(source, filename=filename)

    monkeypatch.setattr(checker.ast, "parse", tracking_parse)
    discovery = checker.discover(tmp_path)
    assert discovery.scanned_files == 101
    assert parsed == ["aragora/inference.py"]


def test_proxy_eligible_rejects_mixed_direct_call_detectors(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "scripts/consult.py",
        """from somewhere import ModelTransportPolicy
import requests
def run(policy: ModelTransportPolicy):
    policy.generate_anthropic(model="claude", messages=[])
    requests.post("https://api.anthropic.com/v1/messages", json={})
""",
    )
    payload = _template(tmp_path)
    payload["sites"][0]["classification"] = "proxy-eligible"
    payload["transport_policy_consumers"] = ["scripts/consult.py"]
    result = checker.check_allowlist(tmp_path, _write_manifest(tmp_path, payload))
    assert any(
        "proxy-eligible cannot include direct-call detectors: http-inference-call" in error
        for error in result.manifest_errors
    )


def test_unclassified_stale_and_count_changes_fail(tmp_path: Path) -> None:
    source = """from openai import OpenAI
def run():
    return OpenAI()
"""
    path = _write_source(tmp_path, "aragora/run.py", source)
    payload = _template(tmp_path)
    manifest = _write_manifest(tmp_path, payload)
    path.write_text(
        source.replace("return OpenAI()", "OpenAI()\n    return OpenAI()"), encoding="utf-8"
    )
    changed = checker.check_allowlist(tmp_path, manifest)
    assert len(changed.changed) == 1
    _write_source(tmp_path, "aragora/new.py", "from anthropic import Anthropic\nclient = Anthropic()\n")  # fmt: skip
    missing = checker.check_allowlist(tmp_path, manifest)
    assert missing.unclassified
    path.unlink()
    stale = checker.check_allowlist(tmp_path, manifest)
    assert stale.stale


# fmt: off
@pytest.mark.parametrize("relative", [".github/scripts/check.py", "scripts/ci/check.py", "aragora/server/handler.py", "aragora/live/src/lib/provider-keys.ts", "aragora/gateway/proxy.py", "aragora/compat/openclaw/skills/pr-reviewer/policy.yaml"])
# fmt: on
def test_protected_paths_cannot_be_proxy_eligible(tmp_path: Path, relative: str) -> None:
    _write_source(tmp_path, relative, 'URL = "https://api.anthropic.com/v1/messages"\n')
    payload = _template(tmp_path)
    payload["sites"][0]["classification"] = "proxy-eligible"
    result = checker.check_allowlist(tmp_path, _write_manifest(tmp_path, payload))
    assert any("must be direct-only" in error for error in result.manifest_errors)


@pytest.mark.parametrize("source", ['URL: "http://localhost:08317"\n', 'PORT: "8317"\n'])
def test_forbidden_port_fails_even_without_inference_site(tmp_path: Path, source: str) -> None:
    _write_source(tmp_path, ".github/workflows/config.yml", source)
    result = checker.check_allowlist(tmp_path, _empty_manifest(tmp_path))
    assert result.forbidden_ports == (".github/workflows/config.yml:1",)


def test_unparseable_scanned_source_fails_closed(tmp_path: Path) -> None:
    _write_source(tmp_path, "aragora/broken.py", "OpenAI(\n")
    result = checker.check_allowlist(tmp_path, _empty_manifest(tmp_path))
    assert result.scan_errors and "aragora/broken.py: SyntaxError" in result.scan_errors[0]


def test_central_port_prohibition_is_allowed_but_other_uses_fail(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/agents/transports/vibeproxy.py",
        'PROHIBITED_PORTS = {8317}\nOTHER_PORT = 8317\nPORTS = ["8317"]\n',
    )
    result = checker.check_allowlist(tmp_path, _empty_manifest(tmp_path))
    assert result.forbidden_ports == ("aragora/agents/transports/vibeproxy.py:2", "aragora/agents/transports/vibeproxy.py:3")  # fmt: skip


def test_python_numeric_port_spellings_trigger_ast_enforcement(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/ports.py",
        "PORTS = [8_317, 0x207d, 0o20175, 0b10000001111101]\n",
    )
    result = checker.check_allowlist(tmp_path, _empty_manifest(tmp_path))
    assert result.forbidden_ports == ("aragora/ports.py:1",) * 4


def test_python_embedded_string_ports_trigger_ast_enforcement(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/ports.py",
        "ARGS = ['--port=8317', 'http://localhost/?port=8317', b'port=08317', '-p 8317']\n",
    )
    result = checker.check_allowlist(tmp_path, _empty_manifest(tmp_path))
    assert result.forbidden_ports == ("aragora/ports.py:1",) * 4


def test_python_issue_references_are_not_ports(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "aragora/history.py",
        '"""Review history for #8317."""\n# review fix #8317\nNOTE = "review fix #8317"\n',
    )
    result = checker.check_allowlist(tmp_path, _empty_manifest(tmp_path))
    assert result.forbidden_ports == ()


def test_manifest_port_strings_and_bytes_are_forbidden(tmp_path: Path) -> None:
    assert checker._contains_forbidden_port({"note": "--port=8317"})
    assert checker._contains_forbidden_port({"note": b"port=08317"})
    assert not checker._contains_forbidden_port({"note": "review fix #8317"})


def test_malformed_and_duplicate_manifest_entries_fail(tmp_path: Path) -> None:
    _write_source(tmp_path, "aragora/run.py", "from openai import OpenAI\nclient = OpenAI()\n")
    payload = _template(tmp_path)
    payload["sites"].append(dict(payload["sites"][0]))
    payload["sites"][0]["classification"] = "sometimes"
    payload["sites"][1]["rationale"] = ""
    payload["port"] = "8317"
    result = checker.check_allowlist(tmp_path, _write_manifest(tmp_path, payload))
    errors = "\n".join(result.manifest_errors)
    assert all(message in errors for message in ("invalid classification", "duplicate site", "forbidden port"))
