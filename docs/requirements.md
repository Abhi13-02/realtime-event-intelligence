# Requirements — Real-Time Topic Tracking & Alert Intelligence System

> **Phase:** 1 — Requirements  
> **Status:** Draft  
> **Last Updated:** 2026-03-16  

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Target Users](#2-target-users)
3. [Functional Requirements](#3-functional-requirements)
4. [Non-Functional Requirements](#4-non-functional-requirements)
5. [Constraints & Out of Scope](#5-constraints--out-of-scope)
6. [Approved Data Sources (v1)](#6-approved-data-sources-v1)
7. [Glossary](#7-glossary)

---

## 1. Problem Statement

Keeping up with fast-moving information across news portals, Reddit, and forums is a significant challenge for researchers, analysts, and businesses. Existing tools are static and require manual re-querying — they don't proactively notify users when meaningful changes occur.

This system solves that by:
- Crawling a curated set of sources automatically on a schedule
- Matching crawled content to user-defined topics using NLP
- Filtering out duplicates so users don't see the same story twice
- Delivering concise, relevant alerts via multiple channels

---

## 2. Target Users

**Primary persona (v1):** A researcher or analyst tracking a specific topic.

The system is **multi-tenant** — many users can use it simultaneously, each with independent topic configurations and alert preferences. Infrastructure (crawling, processing) is shared; user data and notifications are isolated.

> 📝 **Engineering Note:** Multi-tenancy is how SaaS products like Google Alerts and Mention operate. You crawl once per unique topic across all users, then fan-out notifications to each user who tracks it. This avoids redundant API calls (e.g. 1000 users tracking "AI" → crawl once, notify all 1000).

**Out of scope for v1:** Enterprise shared dashboards, mobile app users, custom source power users.

---

## 3. Functional Requirements

> 📝 **Engineering Note:** Functional requirements describe *what* the system does (user-facing behaviour). Non-functional requirements (Section 4) describe *how well* it does it. Keeping them separate is standard practice in PRDs at product companies.

### 3.1 User & Topic Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | User can sign in and out (via Google OAuth — handled by NextAuth on the frontend; no custom register/login flow in the backend) | Must Have |
| FR-02 | User can create a tracked topic (e.g. "AI chips", "climate policy") | Must Have |
| FR-03 | User can track multiple topics simultaneously | Must Have |
| FR-04 | User can pause or delete a tracked topic | Must Have |
| FR-05 | User can set an alert sensitivity per topic: Broad, Balanced, or High. Broad surfaces loosely related articles. Balanced surfaces clearly related articles. High surfaces only strong, direct matches. | Must Have |

> 📝 **Engineering Note (FR-05):** Alert sensitivity abstracts the internal cosine similarity threshold from the user. Broad maps to 0.55, Balanced to 0.65, High to 0.75 internally. The user never sees these float values. Relevance score is still shown on each delivered alert so users can see how strongly an article matched — but they don't need to understand it to configure their preferences.

---

### 3.2 Data Ingestion

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-06 | Poll a fixed curated list of news RSS feeds on a schedule | Must Have |
| FR-07 | Crawl Reddit (broad subreddits: r/technology, r/worldnews, r/science, r/MachineLearning) | Must Have |
| FR-08 | Crawl Hacker News top stories via its public API | Must Have |
| FR-09 | Each source is polled on a configurable interval (default: every 10 minutes) | Must Have |
| FR-10 | All raw articles are stored before any processing begins | Must Have |
| FR-11 | System crawls sources broadly and filters by topic locally — NOT one crawl request per user topic | Must Have |

> 📝 **Engineering Note (FR-11):** Crawling per-topic = 1000 users × 10 topics = 10,000 API calls per cycle. Instead, crawl sources once (e.g. top 100 Reddit posts), store everything, then match against all topics locally. This is exactly how search engines work: crawl broadly → index → match at query time.

---

### 3.3 Processing Pipeline

All ingested content passes through a **fail-fast pipeline** — cheap elimination steps run first so expensive steps only run on the smallest possible dataset.

| Order | Stage | What It Does | Why This Order |
|-------|-------|-------------|----------------|
| 1 | **Deduplication** | Detects if article is already seen (same URL or near-identical text) | Cheapest filter — skip reprocessing entirely |
| 2 | **Topic Matching** | Checks if content relates to any tracked topic using NLP | Eliminates irrelevant content before heavy ops |
| 3 | **Relevance Scoring** | Scores match strength against topic (0.0–1.0) | Needed before threshold check |
| 4 | **Summarisation** | Generates 2–3 sentence summary via external AI API | Most expensive — runs last on smallest set |

> 📝 **Engineering Note:** This pattern is called **fail-fast filtering**. It's used in data pipelines, compilers, and HFT order validation. The principle: eliminate cheaply first, process expensively last.

> 📝 **Engineering Note:** Summarisation uses the Gemini API for v1. Deduplication and topic matching use lightweight local models (Sentence-BERT + cosine similarity). This balances cost, speed, and learning value.

---

### 3.4 Alert Delivery

| ID | Requirement | Mode | Priority |
|----|-------------|------|----------|
| FR-12 | Email alerts | Digest — batched and sent once every 24 hours (fixed, not configurable) | Must Have |
| FR-13 | WebSocket push to dashboard | Instant | Must Have |
| FR-14 | SMS / WhatsApp via Twilio | Instant | Should Have |
| FR-16 | Each alert payload includes: topic name, headline, summary, source URL, relevance score, timestamp | — | Must Have |

> 📝 **Engineering Note:** Email is digest-only — all alerts accumulated over 24 hours are sent in a single daily email per user. There is no instant email option. This is a deliberate product decision: per-article instant emails = spam. The 24-hour window is fixed and not user-configurable. WebSocket and SMS remain instant.

---

## 4. Non-Functional Requirements

> 📝 **Engineering Note:** NFRs are the backbone of system design interviews. Always attach a number to them — vague answers like "should scale well" are a red flag at product companies and HFTs.

| Category | Requirement | Target | Rationale |
|----------|-------------|--------|-----------|
| Latency | End-to-end alert delivery (publish → notification) | < 5 minutes | Achievable with 10-min poll + fast pipeline. Google Alerts averages 15–30 min. |
| Latency | API response time (p99) | < 200ms | Standard SLO for consumer-facing APIs |
| Scalability | Concurrent users | 10,000 | Mid-scale — forces real architectural decisions without Google-scale complexity |
| Scalability | Topics per user | Up to 10 | Drives unique-topic deduplication logic in ingestion |
| Availability | System uptime | 99.9% (three nines) | ~8.7 hrs downtime/year. Appropriate for non-critical alerting. |
| Reliability | Crawl failure handling | Exponential backoff, max 3 retries | Prevents cascade failures when a source goes down |
| Reliability | Crawl success rate per source | > 99% over 24hr window | Ensures alert coverage despite transient failures |
| Consistency | CAP preference | Availability over Consistency (AP) | Slightly stale alert = acceptable. Broken dashboard = not. |
| Accuracy | Deduplication accuracy | > 95% | Measured as: duplicates correctly filtered / total duplicates seen |

> 📝 **Engineering Note (CAP Theorem):** In a distributed system, during a network partition you must choose between Consistency (always return latest data) and Availability (always return a response). This system chooses Availability — showing a slightly old result is fine. Databases like Cassandra are AP; traditional banking DBs are CP.

> 📝 **Engineering Note (Exponential Backoff):** Instead of retrying every second (which hammers a struggling service), you wait 1s → 2s → 4s → 8s. Standard in all distributed systems. Comes up in almost every backend interview.

---

## 5. Constraints & Out of Scope

> 📝 **Engineering Note:** Explicitly scoping out features is as important as scoping them in. In design interviews, inability to prioritise is a red flag.

| Out of Scope | Reason |
|---|---|
| Twitter / X integration | API is now paid and heavily rate-limited |
| Custom user-defined source URLs | Adds scraping complexity; fixed list sufficient for v1 |
| Frontend / mobile app | Backend-first project |
| Billing / subscriptions | Out of product scope |
| Full-text historical search | Would require Elasticsearch — separate concern |
| Training custom ML models | Use pre-trained models and external APIs |
| Multi-language support | English sources only for v1 |

---

## 6. Approved Data Sources (v1)

| Source | Access Method | Crawl Scope | Complexity |
|--------|--------------|-------------|------------|
| Google News RSS | Free RSS feed | Top stories by category | Low |
| BBC News RSS | Free RSS feed | World / Tech / Science feeds | Low |
| Reuters RSS | Free RSS feed | Top headlines | Low |
| TechCrunch RSS | Free RSS feed | Technology news | Low |
| Reddit | Official free read-only API | r/technology, r/worldnews, r/science, r/MachineLearning | Medium |
| Hacker News | Free Algolia API | Top 100 stories | Low |

> 📝 **Engineering Note:** RSS (Really Simple Syndication) is an XML format most news sites publish automatically. No scraping needed — just parse XML. This is the simplest and most reliable way to get structured article data, which is why we start here.

---

## 7. Glossary

| Term | Definition |
|------|-----------|
| Multi-tenancy | One system instance serves many users with shared infra but isolated data |
| Fail-fast filtering | Pipeline design where cheap elimination runs first; expensive ops run last |
| Deduplication | Removing near-identical content so users don't see the same story twice |

| Relevance score | Float (0.0–1.0) indicating how strongly content matches a tracked topic |
| Alert threshold | Minimum relevance score required to trigger an alert for a topic |
| Digest mode | Email-only delivery mode where all alerts accumulated over 24 hours are sent in a single daily email |
| Exponential backoff | Retry strategy where wait time doubles after each failure (1s, 2s, 4s, 8s...) |
| CAP theorem | Distributed systems tradeoff: during partition, choose Consistency or Availability |
| SLO | Service Level Objective — a measurable performance target |
| RSS | Really Simple Syndication — XML feed format published by news sites |
| WebSocket | Persistent client-server connection enabling real-time push notifications |
| Fan-out | Delivering one event (new article) to multiple recipients (all users tracking that topic) |
