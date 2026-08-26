# Mindmap, Journey, Git Graph, Architecture and Friends

Less common types that are exactly right in their niche.

## Mindmap — hierarchies and brainstorms

```mermaid
mindmap
  root((carapace))
    Security
      Sentinel
      Policy in SECURITY.md
      Audit trail
    Runtime
      Docker
      Kubernetes
        Warm pool
        Per-session PVC
    Knowledge
      Git repos
      Skills
```

Structure comes from **indentation only** — no arrows, no ids. Node shapes reuse the
flowchart forms on the text: `id[square]`, `id(round)`, `id((circle))`, `id))bang((`,
`id)cloud(`, `id{{hexagon}}`. Icons need an icon pack; skip them.

Indentation must be consistent (two spaces per level). Inconsistent indent is the one way
to break a mindmap.

## User journey — experience with sentiment

```mermaid
journey
    title Adding a new skill
    section Discover
        Read create-skill: 4: User
        Search examples: 3: User
    section Build
        Write SKILL.md: 5: User, Agent
        Test in sandbox: 2: User, Agent
    section Ship
        Commit to knowledge repo: 5: User
```

Line format: `Task: score: actors`. Score is 1–5 (low = painful). Actors are comma
separated. Use it to argue about where a workflow hurts.

## Git graph — branching stories

```mermaid
gitGraph
    commit id: "init"
    branch feature/mermaid
    checkout feature/mermaid
    commit id: "renderer"
    commit id: "skill docs"
    checkout main
    merge feature/mermaid tag: "v0.155.0"
    commit
```

Commands: `commit [id: "x"] [tag: "v1"] [type: NORMAL|REVERSE|HIGHLIGHT]`, `branch name`,
`checkout name`, `merge name`, `cherry-pick id: "x"`. Options go in a `%%{init}%%`
directive: `%%{init: {'gitGraph': {'mainBranchName': 'trunk', 'showBranches': true}}}%%`.

## Architecture — infrastructure sketches

```mermaid
architecture-beta
    group plane(cloud)[Control plane]

    service api(server)[Server] in plane
    service store(database)[Postgres] in plane
    service disk1(disk)[Knowledge repos] in plane
    service user(internet)[Browser]

    user:R --> L:api
    api:B --> T:store
    api:R --> L:disk1
```

Only five icons ship by default: `cloud`, `database`, `disk`, `internet`, `server`. Edge
syntax is `src:SIDE --> SIDE:dst` with sides `T`, `B`, `L`, `R`; `--` for a plain line and
`-->` for an arrow. Junctions (`junction j1 in plane`) split shared edges.

For anything beyond a sketch, a `flowchart` with subgraphs gives more control.

## Block — layout-first boxes

```mermaid
block-beta
    columns 3
    api["Server"]:2
    cache[("Redis")]
    space
    db[("Postgres")]:3
```

`columns n` sets the grid, `:n` spans columns, `space` leaves a gap. Use it when the
*arrangement* is the message (memory layout, dashboards, panel structure) and edges are
secondary.

## Packet — binary formats

```mermaid
packet-beta
    0-15: "Source port"
    16-31: "Destination port"
    32-63: "Sequence number"
    64-64: "SYN"
```

Bit ranges must be contiguous and start at 0. Perfect for protocol headers, useless for
anything else.

## Kanban — board snapshots

```mermaid
kanban
    todo[To do]
        t1[Pan and zoom]
    doing[In progress]
        t2[Mermaid rendering]
    done[Done]
        t3[Skill docs]
```

Columns are top-level, cards are indented. Metadata per card:
`t2[Task]@{ assigned: "thies", priority: "High" }`.

## Also available

`requirementDiagram` (formal requirements and their verification), `c4Context` (C4 model,
still experimental and rougher than a flowchart), `radar-beta`, `treemap-beta`,
`zenuml`. Reach for them only when the specific notation is being asked for.
