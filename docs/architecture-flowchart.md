# Project Architecture & Data Flow

This document provides a clear, end-to-end visualization of how data flows through the **Real-Time Topic Tracking & Alert Intelligence** system — from raw ingestion to discovered sub-theme intelligence.

---

## 1. High-Level System Architecture

The top-level orchestration view. The two **bold-bordered** nodes are abstracted pipelines — expanded in detail in Section 2.

```mermaid
graph TD
    %% ── Sources ──
    RSS(("🌐 RSS / API"))
    RedditSrc(("💬 Reddit"))

    %% ── Ingestion ──
    subgraph Ingestion ["⚙️  1 · Ingestion Layer  (Celery Workers)"]
        direction LR
        Ingest["Ingestion Service"]
    end

    RSS --> Ingest
    RedditSrc --> Ingest

    %% ── Kafka Bus ──
    K1{{"📨  Kafka · raw-articles"}}
    Ingest -->|publish| K1

    %% ── Abstracted Pipelines ──
    P[["🔍  2 · TOPIC MATCHING PIPELINE\n(real-time, per-article)"]]
    K1 --> P

    DB[("🗄️  PostgreSQL")]
    P -->|store matched articles| DB

    D[["🧠  3 · SUB-THEME DISCOVERY PIPELINE\n(batch, every few hours)"]]
    DB -.->|read 3-day window| D

    K2{{"📨  Kafka · sub-theme-events"}}
    D -->|publish events| K2

    %% ── Alerting ──
    subgraph Alerting ["🔔  4 · Alert Delivery"]
        direction LR
        Alert["Alert Router"]
        WS["WebSocket"]
        EM["Email Digest"]
        SM["SMS"]
        Alert --> WS
        Alert --> EM
        Alert --> SM
    end
    K2 --> Alert

    %% ── Frontend ──
    subgraph Frontend ["🖥️  5 · User Interface"]
        direction LR
        App["Next.js  App"]
        API["FastAPI"]
        App <-->|REST / WS| API
    end
    API -->|query| DB

    %% ── Styling ──
    style K1 fill:#ffe0f0,stroke:#d63384,stroke-width:2px,color:#000
    style K2 fill:#ffe0f0,stroke:#d63384,stroke-width:2px,color:#000
    style DB fill:#cfe2ff,stroke:#0d6efd,stroke-width:2px,color:#000
    style P  fill:#d1e7dd,stroke:#198754,stroke-width:3px,color:#000,font-weight:bold
    style D  fill:#fff3cd,stroke:#ffc107,stroke-width:3px,color:#000,font-weight:bold
```

---

## 2. Detailed Pipeline Breakdowns

### A · Topic Matching Pipeline  *(Real-Time)*

Every incoming article passes through this pipeline **individually**. It consumes from `Kafka: raw-articles`, deduplicates, matches against user topics, generates a summary, and stores the result.

```mermaid
graph TD
    %% ── Input ──
    K(("📨 Kafka\nraw-articles"))

    %% ── Steps ──
    URL["1 · URL\nDeduplication"]
    EMB["2 · Sentence-BERT\nEmbedding  (768D)"]
    VEC["3 · Vector Dedup\n(pgvector)"]
    MATCH["4 · Topic\nMatching"]
    SUM["5 · LLM Summary\n(Cohere)"]

    %% ── External Calls ──
    PG[("🗄️ PostgreSQL")]
    COHERE(("🤖 Cohere API"))

    %% ── Flow ──
    K --> URL
    URL -->|new URL| EMB
    EMB --> VEC
    VEC -->|unique| MATCH
    MATCH -->|matched| SUM
    SUM -->|persist| PG

    %% ── Side Calls ──
    VEC -.->|similarity check| PG
    MATCH -.->|load user topics| PG
    SUM -.->|API call| COHERE

    %% ── Styling ──
    style K fill:#ffe0f0,stroke:#d63384,stroke-width:2px,color:#000
    style PG fill:#cfe2ff,stroke:#0d6efd,stroke-width:2px,color:#000
    style COHERE fill:#e2d9f3,stroke:#6f42c1,stroke-width:2px,color:#000
    style URL fill:#f8f9fa,stroke:#495057,color:#000
    style EMB fill:#f8f9fa,stroke:#495057,color:#000
    style VEC fill:#f8f9fa,stroke:#495057,color:#000
    style MATCH fill:#f8f9fa,stroke:#495057,color:#000
    style SUM fill:#f8f9fa,stroke:#495057,color:#000
```

### B · Sub-theme Discovery Pipeline  *(Batch)*

Runs every few hours over a **rolling 3-day window**. Clusters articles, maps Reddit social signals, performs sentiment analysis, generates AI labels, and publishes state-change events.

```mermaid
graph TD
    %% ── Input ──
    PG_IN[("🗄️ PostgreSQL\n3-day articles")]

    %% ── Steps ──
    UMAP["1 · UMAP\nDim Reduction  (768D → 10D)"]
    HDB["2 · HDBSCAN\nClustering  (Leaf Mode)"]
    REDDIT["3 · Reddit Post\nMatching  (Anchor-Based)"]
    FETCH["4 · Async Comment\nFetch  (httpx)"]
    VADER["5 · VADER\nSentiment Scoring"]
    LABEL["6 · LLM Labeling\n& Description"]
    SAVE["7 · Persistence\n(Frozen Centroids)"]

    %% ── External ──
    REDDIT_API(("💬 Reddit\nJSON API"))
    GROQ(("🤖 Groq API\nLlama 3.1"))
    PG_OUT[("🗄️ PostgreSQL\nsnapshots")]
    K_OUT{{"📨 Kafka\nsub-theme-events"}}

    %% ── Main Flow ──
    PG_IN --> UMAP
    UMAP --> HDB
    HDB --> REDDIT
    REDDIT --> FETCH
    FETCH --> VADER
    VADER --> LABEL
    LABEL --> SAVE

    %% ── Side Calls ──
    REDDIT -.->|embeddings| PG_IN
    FETCH -.->|concurrent GET| REDDIT_API
    LABEL -.->|API call| GROQ
    SAVE -->|write| PG_OUT
    SAVE -->|publish| K_OUT

    %% ── Styling ──
    style PG_IN fill:#cfe2ff,stroke:#0d6efd,stroke-width:2px,color:#000
    style PG_OUT fill:#cfe2ff,stroke:#0d6efd,stroke-width:2px,color:#000
    style K_OUT fill:#ffe0f0,stroke:#d63384,stroke-width:2px,color:#000
    style REDDIT_API fill:#e2d9f3,stroke:#6f42c1,stroke-width:2px,color:#000
    style GROQ fill:#e2d9f3,stroke:#6f42c1,stroke-width:2px,color:#000
    style UMAP fill:#f8f9fa,stroke:#495057,color:#000
    style HDB fill:#f8f9fa,stroke:#495057,color:#000
    style REDDIT fill:#f8f9fa,stroke:#495057,color:#000
    style FETCH fill:#f8f9fa,stroke:#495057,color:#000
    style VADER fill:#f8f9fa,stroke:#495057,color:#000
    style LABEL fill:#f8f9fa,stroke:#495057,color:#000
    style SAVE fill:#f8f9fa,stroke:#495057,color:#000
```

---

## 3. Component Summary

| Layer | Technology | Role |
|-------|-----------|------|
| **Ingestion** | Celery Workers, PRAW | Polls RSS/API every 10 min, fetches Reddit posts |
| **Topic Matching** | Sentence-BERT, pgvector, Cohere | Dedup → Embed → Match → Summarize (real-time) |
| **Discovery** | UMAP, HDBSCAN, VADER, Groq | Cluster → Reddit Align → Sentiment → Label (batch) |
| **Kafka** | Apache Kafka | Decouples ingestion, matching, and alerting |
| **Alerting** | WebSocket, Email, SMS | Fan-out delivery of state-change events |
| **Frontend** | Next.js, FastAPI | Dashboard, topic management, intelligence views |

---

## 4. Data Flow Summary

1. **Articles** flow from **RSS / API** → **Kafka** → **Topic Matching Pipeline** → **PostgreSQL**.
2. **Social Signals** flow from **Reddit API** → **Discovery Pipeline** → **Sentiment Analysis**.
3. **Sub-themes** are formed by **Discovery** reading from **PostgreSQL** → **Kafka** → **Alert Service**.
4. **Users** view everything via **Next.js** ↔ **FastAPI** ↔ **PostgreSQL**.
