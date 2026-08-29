# How RepoMind Works

RepoMind is local-first repository intelligence for coding agents. It scans a developer repository on your machine, builds a local SQLite index, keeps that index fresh when saved files change, and returns a task-focused ContextPack through the CLI or MCP.

```mermaid
flowchart LR
    subgraph Local["Local-first on your machine - no source upload"]
        Repo["Developer Repository"]
        Scan["Scanner / Parsers"]
        Index["Local SQLite Intelligence Index<br/>files<br/>symbols<br/>imports<br/>routes<br/>dependencies<br/>callers<br/>architecture facts<br/>repository memory with provenance"]
        Fresh["Automatic Freshness<br/>checks saved changes before reads"]
        Task["Coding Task / Agent Request"]
        Intent["Intent Detection"]
        Rank["Explainable Retrieval / Ranking"]
        Pack["ContextPack<br/>bounded, task-focused context"]
        API["CLI / MCP"]

        Repo --> Scan --> Index
        Repo -. saved changes .-> Fresh
        Fresh --> Scan
        Fresh --> Index
        Task --> Fresh --> Intent --> Rank --> Pack --> API
        Index --> Rank
    end

    Agents["AI coding agents"]
    API --> Agents
```

## Reading The Diagram

- `repomind init` scans the repository and writes a local `.repomind/index.sqlite3` cache.
- Scanner and parser output is stored as compact repository intelligence: paths, symbols, imports, routes, dependency/caller relationships, architecture facts, and evidence-backed memory.
- Read commands check freshness before answering, so saved source changes can be reflected without running `refresh` or `watch`.
- A task request goes through intent detection and explainable ranking, then returns a bounded ContextPack through the CLI or MCP.
- RepoMind does not require cloud indexing, embeddings, telemetry, or source upload.
