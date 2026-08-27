# CEP-001: Sandbox-provided skill command resolver

**Status:** Draft for discussion. This RFC proposes a direction and ownership boundary, not an implementation-ready protocol.

## Summary

Move skill command materialization out of Carapace core and behind an optional resolver supplied by the sandbox image.

Carapace would continue to own skill activation, security approval, command aliases, and sandbox lifecycle. The resolver would own environment-specific preparation such as `uv sync`, `pnpm install`, or realizing Nix packages. It would return executable paths for declared skill commands, which Carapace would expose through its existing command shims.

`setup.sh` is a separate lifecycle-hook concern and is not part of this proposal.

## Motivation and use case

Carapace currently detects package-manager files and runs hardcoded uv, npm, and pnpm commands during skill activation. This couples Carapace core and its official sandbox image to particular language ecosystems.

The motivating deployment uses a custom Nix-based sandbox:

- The workspace has one committed, locked root flake.
- Skills contribute Nix modules and packages.
- CI and a binary cache provide the package closures.
- Python, uv, Node, and pnpm should not need to be general agent-facing tools merely because a skill uses them internally.
- Running `nix develop` or another Nix command for every skill command is too expensive.
- Multiple independently activated skills should not require composing devshell environments.

For this deployment, skill activation should realize each command once and replace it with a direct executable path. A possible Nix resolver could build `.#skills.web_search` and return `/nix/store/.../bin/web_search`. An image startup process could alternatively prefetch known closures from the binary cache and provide a manifest, trading slower startup and more initial network traffic for faster later resolution.

Carapace should enable this design without gaining Nix-specific behavior.

## Goals

- Let a trusted sandbox image define how skill commands are materialized.
- Keep package-manager and Nix logic out of Carapace core.
- Resolve all commands for one skill in a single resolver invocation.
- Preserve the existing command-alias interface used by agents.
- Support the official uv, npm, and pnpm behavior through the same extension point.
- Resolve only at explicit lifecycle synchronization points.

## Non-goals

- Nix-aware behavior in Carapace core.
- Devshell activation or environment capture.
- PATH composition between skills.
- File watching, input glob tracking, fingerprints, or automatic re-resolution after workspace edits.
- `setup.sh` or general pre/post activation hooks.

## Skill declaration

The intended steady state is for skills to declare logical commands rather than package-manager invocations. The following example is conceptual, not a final schema:

```yaml
metadata:
  carapace:
    commands:
      - name: web_search
        command: web_search
      - name: web_fetch
        command: web_fetch
```

It remains undecided whether the existing `command` field changes meaning, a new field such as `entrypoint` is introduced, or both forms coexist during migration. Current skills contain complete shell commands such as `uv run --directory ...`; an implementation must define an explicit compatibility and migration path.

No resolver command should be embedded in skill metadata. This avoids giving a skill another automatic arbitrary-code execution mechanism and keeps deployment-specific Nix details out of the skill.

If conventions later prove insufficient, a future revision may add opaque resolver metadata that Carapace passes through without interpreting. It is not required initially.

## Resolver configuration

A deployment may configure one absolute executable path inside the sandbox image, conceptually:

```text
CARAPACE_SANDBOX_SKILL_COMMAND_RESOLVER=/usr/libexec/carapace/resolve-skill-commands
```

The behavior when no resolver is configured remains undecided. Possibilities include retaining the current provider system during migration, supporting only concrete static commands, or requiring the official sandbox resolver for provider-backed skills. The final design must not silently treat unresolved logical command names as working static commands.

The official Carapace sandbox image would ship a default resolver at this path. A custom sandbox image may provide a different implementation.

## Resolver protocol

The following request and response illustrate the proposed ownership boundary. Field names and transport details are not normative yet.

Carapace invokes the resolver once per skill with a versioned request containing all declared commands:

```json
{
  "protocol_version": 1,
  "skill": "web",
  "skill_dir": "/workspace/skills/web",
  "workspace": "/workspace",
  "commands": [
    {"name": "web_search", "command": "web_search"},
    {"name": "web_fetch", "command": "web_fetch"}
  ]
}
```

The resolver returns overrides for commands it materialized:

```json
{
  "protocol_version": 1,
  "commands": {
    "web_search": "/nix/store/...-web-search/bin/web_search",
    "web_fetch": "/nix/store/...-web-fetch/bin/web_fetch"
  }
}
```

It remains undecided whether the resolver must return every declared command or may return partial overrides. Fallback behavior must be specified together with the command-schema migration rather than inferred from this example.

Resolved values should be absolute executable paths. A resolver that needs arguments or environment setup can create its own executable wrapper and return that wrapper's path.

The desired outcome is that Carapace validates a resolver result and atomically generates or replaces its shims under `/workspace/.carapace/bin`. Resolver failure should not leave a half-active skill. Exact rollback behavior, including how this changes current activation semantics, remains to be designed.

Invocation mechanics also remain open, including request transport, stdout and stderr handling, working directory, timeout, environment, and proxy behavior. The security requirements below constrain those choices.

## Lifecycle

Resolution happens only at explicit synchronization points:

1. Initial `use_skill` activation.
2. Sandbox recreation, before an already activated skill is used again.

No automatic invalidation or re-resolution after workspace edits is proposed. A later RFC may add an explicit refresh operation if skill-development workflows demonstrate the need.

## Official sandbox behavior

The official sandbox resolver would own the current provider logic:

- Detect `pyproject.toml` plus `uv.lock` and perform locked uv synchronization.
- Detect npm or pnpm manifests and perform locked installation.
- Resolve declared commands to generated wrappers or executables inside the prepared environment.

This preserves existing behavior while removing uv, npm, and pnpm knowledge from the Carapace server.

`setup.sh` remains separate because it is an arbitrary lifecycle hook, may have unrelated side effects, and may require different credential and network policy.

## Security model

The resolver is trusted deployment code, not skill-controlled code.

Required controls:

- The resolver path is configured by the operator and cannot be overridden by skill metadata.
- The resolver path must be absolute and outside writable workspace and temporary directories.
- Resolver code must be immutable to the agent. It should be supplied through a read-only root filesystem, a read-only mount, or a root-owned location combined with an unprivileged agent user.
- A normal writable container root filesystem is insufficient when agent commands run as root, because root can replace an image-provided executable. Docker and Kubernetes deployments must enforce immutability rather than relying only on file mode bits.
- The resolver runs only after `use_skill` security approval.
- The resolver receives no application or runtime skill credentials by default. Passing every skill credential would expose unrelated secrets to dependency build logic.
- Credentials needed for a private package registry or binary cache are resolver-specific deployment credentials. They must not be baked into resolver code. A deployment may inject them only for the resolver invocation or use an authenticated proxy. Defining that mechanism is outside the initial protocol; deployments without one cannot resolve private sources.
- A future extension may support separately declared resolver credential references, but it must not implicitly reuse runtime skill credentials.
- The resolver does not receive automatic proxy bypass. Network access follows normal sandbox policy.
- Resolver output may reference only commands declared by the skill.
- Every returned path must be absolute, present, and executable before Carapace installs the shims.

Resolver confidentiality is not a security boundary. Read access to trusted resolver code is acceptable and can aid auditing. Execute-only permissions are not generally meaningful for scripts and do not protect code from a root agent. Integrity, not secrecy, is the required property.

The resolver executable is trusted deployment code, but the skill files and package definitions it consumes remain untrusted build input. A resolver may intentionally evaluate or build those inputs, including Nix expressions, inside the sandbox as part of approved skill activation. The final design must specify whether it consumes the live workspace, files restored from upstream, or another pinned snapshot; this RFC does not yet choose that trust model.

## Alternatives considered

### PATH injection

Rejected because it globally changes command lookup, creates ordering and collision questions across skills, and exposes more tools than the declared aliases require.

### Capturing a devshell environment

Rejected because devshells include arbitrary variables and shell hooks and have no clear composition semantics when several skills are active.

### Resolver commands in skill frontmatter

Rejected because they make resolution deployment-specific, expose Nix or package-manager details in skills, and recreate automatic skill-controlled shell execution.

### Automatic input tracking

Deferred because glob semantics, dirty worktrees, imported files, and cache invalidation add substantial complexity. Explicit lifecycle synchronization is sufficient for the initial use case.

## Open questions

- Whether logical entrypoints reuse the current `command` field or use a new schema.
- How existing concrete shell commands and built-in provider behavior migrate.
- Whether resolver responses must cover every declared command or may contain partial overrides.
- What happens when no resolver is configured.
- Whether resolution consumes the live workspace, upstream-restored files, or a pinned snapshot.
- Exact invocation mechanics: transport, working directory, timeout, environment, proxy policy, exit codes, logging, and protocol-version handling.
- Atomic failure and rollback semantics, including replacement of existing shims.
- Exact configuration and protocol names.
- How the official resolver maps logical command names to Python and Node entrypoints during migration.
- How resolver immutability is enforced consistently in the Docker and Kubernetes sandbox runtimes.
- How resolver-specific credentials are supplied for private registries and binary caches without exposing them as runtime skill credentials.
- Whether a future explicit refresh operation belongs as an agent tool, a user action, or both.
