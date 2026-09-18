# Native Claude launch-time credentials

`scripts/claude_profile.sh exec-claude` is an **opt-in qualification path** for
operator-owned native Claude Code. It is not a gateway, OAuth refresher, or
countable reviewer. Existing generic `exec`, native-only profiles, Factory
routes, and the credential synchronizer are unchanged.

## Credential ownership

VibeProxy remains the only refresh-token owner. Each invocation locates the
explicitly enrolled identity in its credential directory, validates the access
token lifetime, and supplies only that access token to the Claude child through
`CLAUDE_CODE_OAUTH_TOKEN`. No token is copied into Keychain or profile files.
This prevents stored subscription credentials from shadowing the selected token;
it does not make a revoked token valid or replenish quota.

The documented Claude baseline is `claude setup-token`. Compatibility of a
VibeProxy-issued short-lived access token requires a separately authorized native
canary; deterministic tests do **not** establish that compatibility.

## Private enrollment and invocation

After ownership and activation approval, the operator enrolls only explicitly
mapped VibeProxy-managed profiles in `~/.aragora/claude_launch_profiles.json`:

```json
{"version":1,"profiles":{"example-profile":{"email":"operator@example.invalid","account_uuid":"account-id","organization_uuid":"organization-id"}}}
```

Keep enrollment private and outside the repository. Credential files must be
owner-only regular files; writable shared directories, symlinks, ambiguous
identities, malformed inputs and insufficient lifetime fail closed. Filename
changes do not select a different account. Remaining lifetime must strictly
exceed the requested deadline plus 300 seconds.

```bash
printf 'Reply exactly OK' | scripts/claude_profile.sh exec-claude example-profile \
  --model APPROVED_MODEL --timeout-seconds 90 -- --output-format json
```

The example makes a real model call: do not run it without authorization and
capacity clearance. `ARAGORA_NATIVE_CLAUDE_ENROLLMENT`, `VIBEPROXY_AUTH_DIR` and
`CLAUDE_PROFILE_ROOT` select private input locations; they do not authorize
another account. Only output-format selection is forwarded initially. Tools,
MCP, persistence, retries and fallback are disabled. Therefore this first path
does not provide the repository access needed for grounded review.

Conflicting authentication, cloud/gateway routing, model overrides, or profile
selectors stop launch rather than being silently removed. Detected managed
policy is held for explicit qualification, never disabled to make a probe pass.
Claude Code 2.x is eligible only when the required runtime flags are available.
Absent local policy files do not prove absence of uncached server-managed policy;
that admission question must be resolved before activating a real account.

The launcher does not persist tokens or forward unrelated credential variables.
An environment secret remains visible to sufficiently privileged local software.
The flags are not a filesystem sandbox: native Claude may write its own local
operational state. Do not claim sandbox-enforced read-only behavior.

## Rollout and recovery

First qualify one explicitly selected profile using an exact-model, one-attempt
canary. Require exit success, expected output and reported model identity. A
cached login indicator is not live availability; availability is not evidence.
Authentication, quota, model, timeout and transport errors require different
operator actions; none triggers account rotation or paid fallback here.

After independent review and owner clearance, migrate both availability and
collection callers to the same approved route without preliminary calls or
fallback. This integration is a separate batch. Install a reviewed version
outside the shared checkout, then remove only qualified profiles from the
legacy sync mapping and verify the deployed job skips them. Do not delete old
Keychain items or copy refresh tokens. Native-only profiles remain native-only.
Rollback parks the migrated caller; it does not revive a known-stale credential.

Sources: [Claude authentication](https://code.claude.com/docs/en/authentication),
[environment variables](https://code.claude.com/docs/en/env-vars), and
[managed policy](https://code.claude.com/docs/en/managed-settings).
