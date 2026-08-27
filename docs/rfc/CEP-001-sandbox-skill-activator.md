# CEP-001: Sandbox-provided skill activator

**Status:** Draft for discussion. This CEP proposes a direction and ownership boundary, not an implementation-ready protocol.

## Summary

Move all automatic skill activation behavior out of Carapace core and behind one activator supplied by the sandbox image.

Carapace continues to own `use_skill`, security approval, activation lifecycle, and command shims. The sandbox activator owns runtime materialization. It may perform side effects such as `uv sync`, `pnpm install`, `setup.sh`, or realizing Nix packages. It may also return command overrides that Carapace installs through its existing shims.

## Motivation and use case

Carapace currently detects package-manager and hook files in server code through `SKILL_ACTIVATION_PROVIDERS`. It runs uv, npm, pnpm, and `setup.sh` in a fixed order. This only works when the selected sandbox image contains those tools and supports their assumptions, so the behavior belongs to the execution layer provided by that image.

The motivating deployment uses a custom Nix-based sandbox:

- The workspace has one committed and locked root flake.
- Skills contribute Nix modules and packages.
- CI and a binary cache provide package closures.
- Running `nix develop` for every skill command is too expensive.
- Multiple skills should not require composing devshell environments.
- Carapace core should not gain Nix-specific behavior.

A Nix activator can realize all packages for one skill in one invocation and return direct store-backed commands.

## Goals

- Move the complete current activation-provider chain into the official sandbox image.
- Let custom sandbox images replace that behavior without changing Carapace core.
- Preserve the existing `metadata.carapace.commands` schema and concrete command semantics.
- Allow activation-time side effects and optional command overrides through one extension point.
- Resolve or prepare all commands for one skill in one activator invocation.
- Run the activator only at explicit lifecycle synchronization points, such as initial skill loading and sandbox recreation.

## Non-goals

- Nix-aware behavior in Carapace core.
- PATH composition between skills.
- A general multi-phase lifecycle-hook framework.
- File watching, input fingerprints, or automatic reactivation after workspace edits.
- Re-resolution or a manual refresh tool.

## Existing skill schema

Existing skills continue to declare concrete commands:

```yaml
metadata:
  carapace:
    commands:
      - name: web_search
        command: uv run --directory /workspace/skills/web web_search
      - name: web_fetch
        command: uv run --directory /workspace/skills/web web_fetch
```

The activator receives these declarations. For each command it may either:

1. Return a command override.
2. Omit the command, causing Carapace to use the original declared command unchanged.

The official activator can therefore reproduce current behavior by preparing dependencies, running `setup.sh` when present, and returning no overrides. A custom activator can instead use the alias name or its own skill-file conventions to return another command without changing the skill schema.

No activator command is embedded in skill metadata. The activator is selected by the deployment, not by the skill.

## Activator configuration

A compatible sandbox image provides one activator executable at an operator-configured absolute path, conceptually:

```text
CARAPACE_SANDBOX_SKILL_ACTIVATOR=/usr/libexec/carapace/activate-skill
```

The official Carapace sandbox image ships the default implementation. A custom sandbox image may provide a different implementation.

When no activator is configured or available, Carapace uses no-op activation: it performs no runtime preparation, returns no command overrides, and installs the originally declared commands unchanged.

Carapace core does not retain the legacy uv, npm, pnpm, or `setup.sh` provider chain as a fallback. No-op activation is therefore still an intentional execution-layer compatibility break for older sandbox images: a command such as `uv run ...` is preserved, but the preceding `uv sync` no longer happens. This avoids keeping two activation implementations indefinitely and does not require a skill-schema migration.

## Conceptual activator protocol

Carapace invokes the activator once per skill with all declared commands:

```json
{
  "protocol_version": 1,
  "skill": "web",
  "skill_dir": "/workspace/skills/web",
  "workspace": "/workspace",
  "commands": [
    {
      "name": "web_search",
      "command": "uv run --directory /workspace/skills/web web_search"
    },
    {
      "name": "web_fetch",
      "command": "uv run --directory /workspace/skills/web web_fetch"
    }
  ]
}
```

It returns optional command overrides and status messages:

```json
{
  "protocol_version": 1,
  "command_overrides": {
    "web_search": "/nix/store/...-web-search/bin/web_search",
    "web_fetch": "/nix/store/...-web-fetch/bin/web_fetch"
  },
  "messages": ["Realized 2 skill commands."]
}
```

`protocol_version` identifies the protocol spoken by both sides. `command_overrides` replaces only the listed aliases; an omitted command always uses its original declaration. Overrides use the same shell-command semantics as existing skill commands and may include arguments or environment preparation.

`messages` contains model-facing activation status. The official activator can use it to report completed uv, npm, pnpm, or `setup.sh` work and include appropriate non-sensitive hook output.

Carapace validates that overrides reference declared aliases and contain nonempty, single-line command strings without carriage returns or newlines. It installs new shims only after successful activation and successful result validation. Exact transport, timeout, logging, and rollback details remain open.

## Lifecycle

The activator runs at these explicit synchronization points:

1. Initial `use_skill` activation.
2. Sandbox recreation, before an already activated skill is used again.

No automatic reactivation occurs when workspace files change. Skill development and explicit refresh behavior can be considered separately if needed later.

## Official sandbox activator

The official implementation moves the full current provider chain out of the server and preserves its order and behavior:

1. `pyproject.toml` plus `uv.lock` runs `uv sync --locked`.
2. `package.json` plus the npm lockfile runs `npm ci` when pnpm does not apply.
3. `package.json` plus `pnpm-lock.yaml` runs `pnpm install --frozen-lockfile`.
4. `setup.sh` runs `sh ./setup.sh`.

These operations primarily materialize runtime state and may return no command overrides. `setup.sh` belongs here because it is currently an equal activation provider and acts as the generic runtime-preparation mechanism when no specialized provider is sufficient.

A separate lifecycle-hook system may still be useful for events unrelated to skill runtime preparation, but it is outside this CEP.

## Credentials and network policy

Current automatic providers receive approved activation credentials and run with proxy bypass. `setup.sh` relies on this for use cases such as materializing tool-specific configuration. Preserving official behavior therefore requires the activator interface to support equivalent inputs and capabilities.

This does not mean every activator should receive every skill credential or unrestricted network access. Credential injection and network policy should be explicit operator-controlled activator capabilities:

- The official activator can request compatibility behavior.
- Any custom activator can disable runtime credential injection.
- Credentials for private registries or binary caches should be activator-specific deployment credentials, invocation-scoped secrets, or supplied through an authenticated proxy.

The exact capability configuration remains open. Skills must not be able to grant these capabilities to the activator themselves.

## Security model

The activator is trusted deployment code. The skill files, manifests, package definitions, and `setup.sh` it consumes remain untrusted activation input.

Required controls:

- The activator path is configured by the operator and cannot be overridden by skill metadata.
- The path is absolute and outside writable workspace and temporary directories.
- Activator code is immutable to the agent through a read-only root filesystem, read-only mount, or an unprivileged agent combined with root-owned files.
- A writable container root filesystem is insufficient when agent commands run as root.
- The activator runs only after `use_skill` security approval.
- Returned overrides may reference only commands declared by the skill.
- Every override is validated before Carapace replaces command shims.

Activator confidentiality is not a security boundary. Read access can aid auditing. Integrity, not secrecy, is required.

The final design must specify whether activation consumes the live workspace, files restored from upstream, or another pinned snapshot. This CEP does not yet choose that trust model.

## Alternatives considered

### Keep the current provider chain as a fallback

Rejected because it duplicates activation logic across core and the sandbox image and makes the legacy path difficult to remove. This CEP instead accepts coordinated server and image upgrades.

### Command resolver only

Rejected as too narrow. Current uv, npm, pnpm, and `setup.sh` providers primarily perform side effects and do not resolve commands. Optional command overrides are one output of activation, not the whole abstraction.

### General lifecycle-hook framework

Deferred because the current need has one clear event and contract: prepare a skill runtime during activation. Multiple hook phases would add complexity without serving the motivating use case.

### PATH or devshell injection

Rejected because it introduces global lookup order, collision, environment-composition, and shell-hook questions across several active skills.

### Activator commands in skill frontmatter

Rejected because they make deployment-specific execution skill-controlled and recreate arbitrary automatic shell execution in the schema.

## Open questions

- Exact configuration and protocol names.
- Request and response transport, timeout, exit-code, stdout, stderr, and versioning semantics.
- Failure and rollback behavior after partial activator side effects.
- How credential and network capabilities are configured per activator.
- Whether activation consumes the live workspace, upstream-restored files, or a pinned snapshot.
- How activator immutability is enforced consistently in Docker and Kubernetes.
- How the official activator is packaged so custom images can reuse or extend it.
