# Data, Schedules and Charts

`erDiagram` for schemas, `gantt`/`timeline` for time, `xychart`/`pie`/`quadrantChart`/
`sankey` for numbers.

## ER diagram — database schemas

```mermaid
erDiagram
    USER ||--o{ SESSION : owns
    SESSION ||--o{ MESSAGE : contains
    SESSION }o--|| SANDBOX : claims
    USER {
        uuid id PK
        string email UK
        string role
        timestamp created_at
    }
    SESSION {
        uuid id PK
        uuid user_id FK
        string title
        bool attended "false for job runs"
    }
```

Cardinality is written on both ends; left symbol reads first:

| Symbol | Meaning        |
| ------ | -------------- |
| `\|o`  | zero or one    |
| `\|\|` | exactly one    |
| `}o`   | zero or more   |
| `}\|`  | one or more    |

`--` between them means identifying (solid), `..` means non-identifying (dashed). The
label after the colon is required — use `""` if there is nothing to say.

Attribute lines are `type name [PK|FK|UK] ["comment"]`. Types are free text; use whatever
your database calls them. Names cannot contain spaces.

## Gantt — schedules and plans

```mermaid
gantt
    title Migration plan
    dateFormat YYYY-MM-DD
    axisFormat %d.%m
    excludes weekends

    section Prep
        Audit current setup   :done,    a1, 2026-09-01, 5d
        Write runbook         :active,  a2, after a1, 3d
    section Cutover
        Dry run               :         c1, after a2, 2d
        Switch traffic        :crit,    c2, after c1, 1d
        Go/no-go              :milestone, m1, after c2, 0d
    section After
        Decommission old      :         d1, after c2, 1w
```

Task line: `label : [tags,] id, start, duration`.

- tags: `done`, `active`, `crit`, `milestone` (comma-separated, any order)
- start: a date in `dateFormat`, or `after <id>` (chain from another task)
- duration: `3d`, `2w`, `6h`, or an end date
- `id` is only needed if another task references it

Header options: `dateFormat` (input parsing), `axisFormat` (display, strftime-style),
`excludes weekends` / `excludes 2026-12-24`, `tickInterval 1week`, `todayMarker off`.

## Timeline — history, roadmaps

```mermaid
timeline
    title Release history
    section 2025
        Q3 : first sandbox runtime : Docker only
        Q4 : Kubernetes runtime
    section 2026
        Q1 : per-user knowledge repos
        Q2 : jobs and scheduling
```

Each `period : event : event` line puts multiple events under one period. Simpler than a
gantt when there are no durations or dependencies.

## Pie — parts of a whole

```mermaid
pie showData
    title Token usage by tool
    "exec" : 45.2
    "read" : 22.8
    "web_search" : 18.1
    "other" : 13.9
```

`showData` prints the raw values next to the legend. Labels must be quoted. Use it only
for three to six slices; beyond that a table beats a pie.

## XY chart — trends and comparisons

```mermaid
xychart-beta
    title "Sessions per day"
    x-axis [Mon, Tue, Wed, Thu, Fri]
    y-axis "count" 0 --> 60
    bar [12, 28, 41, 33, 55]
    line [12, 28, 41, 33, 55]
```

`xychart-beta horizontal` rotates it. Multiple `bar`/`line` series are allowed; there is
no legend, so name the series in the surrounding prose. Axis labels with spaces must be
quoted; a numeric x-axis is written `x-axis "load" 0 --> 100`.

## Quadrant chart — prioritization

```mermaid
quadrantChart
    title Effort vs impact
    x-axis "Low effort" --> "High effort"
    y-axis "Low impact" --> "High impact"
    quadrant-1 Do now
    quadrant-2 Plan
    quadrant-3 Drop
    quadrant-4 Quick wins
    Mermaid rendering: [0.35, 0.8]
    Pan and zoom: [0.6, 0.35]
    Diagram export: [0.25, 0.45]
```

Point coordinates are 0–1 on both axes. Quadrants are numbered counter-clockwise from the
top right.

## Sankey — flows and budgets

```mermaid
sankey-beta

Requests,Cache hit,320
Requests,Backend,180
Backend,Postgres,140
Backend,Error,40
```

CSV body: `source,target,value`. Quote any name containing a comma. Good for traffic
splits, cost breakdowns and funnel drop-off.
