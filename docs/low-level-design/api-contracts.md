# API Contracts â€” Real-Time Topic Tracking & Alert Intelligence System

> **Section:** 3.3 â€” API Contracts
> **Phase:** 3 â€” Low-Level Design
> **Depends on:** schema.sql, auth-lld.md, high-level-design.md

---

## Table of Contents

1. [General Conventions](#1-general-conventions)
2. [Authentication â€” `/auth/*`](#2-authentication)
3. [User Profile â€” `/users/*`](#3-user-profile)
4. [Topics â€” `/topics/*`](#4-topics)
5. [Alerts â€” `/alerts/*`](#5-alerts)
6. [Analytics](#6-analytics)
7. [Articles â€” `/articles/*`](#7-articles)
8. [WebSocket â€” `/ws`](#8-websocket)
9. [Full Endpoint Index](#9-full-endpoint-index)

---

## 1. General Conventions

### 1.1 Base URL
```
https://api.yourapp.com/v1
```

All endpoints are prefixed with `/v1`. Versioning the API from day one means you can introduce breaking changes in `/v2` without affecting existing clients.

### 1.2 Authentication
All endpoints except `/auth/register` and `/auth/login` require a valid JWT access token:
```
Authorization: Bearer <access_token>
```
The access token is obtained via `POST /auth/login` and refreshed via `POST /auth/refresh`.

### 1.3 HTTP Methods
| Method | Meaning |
|--------|---------|
| `GET` | Read data â€” no side effects |
| `POST` | Create a new resource |
| `PATCH` | Partially update a resource (send only changed fields) |
| `PUT` | Replace a resource entirely (send the complete new state) |
| `DELETE` | Remove a resource |

> ðŸ“ **Engineering Note:** PATCH vs PUT is a common interview question. PATCH = partial update. PUT = full replacement. Use PATCH when the client only wants to change one field. Use PUT when the client is replacing an entire sub-resource (e.g. the full channel config for a topic).

### 1.4 Standard Error Response Shape
All errors return a consistent JSON body:
```json
{
  "error": "human readable message",
  "code": "MACHINE_READABLE_CODE"
}
```

### 1.5 Pagination
All list endpoints that can return large result sets support pagination via query params:
```
?page=1&limit=20
```
Paginated responses are wrapped in:
```json
{
  "data": [...],
  "total_count": 143,
  "page": 1,
  "limit": 20
}
```
`total_count` allows the frontend to calculate total pages (`ceil(total_count / limit)`).

### 1.6 HTTP Status Codes Used
| Code | Meaning |
|------|---------|
| `200` | Success with response body |
| `201` | Resource created successfully |
| `204` | Success with no response body (deletes) |
| `400` | Bad request â€” invalid input |
| `401` | Unauthenticated â€” missing or invalid token |
| `403` | Forbidden â€” authenticated but not authorised |
| `404` | Resource not found (also used when resource exists but belongs to another user â€” see Section 1.7) |
| `409` | Conflict â€” duplicate resource |

### 1.7 Resource Enumeration Protection
When a user tries to access or modify a resource that exists but belongs to another user, always return `404` â€” not `403`. Returning `403` would confirm that the resource exists, leaking information to an attacker. This pattern is called **resource enumeration protection** and is standard security practice.

---

## 2. Authentication

> Full authentication design including JWT structure, refresh token rotation, cookie configuration, and security rationale is documented in `auth-lld.md`. This section lists endpoint contracts only.

### POST /auth/register
**Auth required:** No

**Request:**
```json
{
  "name": "Abhinav",
  "email": "abhinav@example.com",
  "password": "plaintext_password"
}
```

**Response (201):**
```json
{
  "id": "<uuid>",
  "name": "Abhinav",
  "email": "abhinav@example.com",
  "created_at": "2026-03-20T10:00:00Z"
}
```

**Errors:**
| Code | Reason |
|------|--------|
| `400` | Missing required fields |
| `409` | Email already registered |

---

### POST /auth/login
**Auth required:** No

**Request:**
```json
{
  "email": "abhinav@example.com",
  "password": "plaintext_password"
}
```

**Response (200):**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```
Refresh token is set as an `httpOnly` cookie â€” not in the response body.

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Invalid credentials (same response for wrong email or wrong password â€” never reveal which) |

---

### POST /auth/refresh
**Auth required:** No (uses httpOnly cookie)

**Request:** No body. Refresh token is read automatically from the `httpOnly` cookie.

**Response (200):**
```json
{
  "access_token": "<new_jwt>",
  "token_type": "bearer"
}
```
Old refresh token is revoked. New refresh token is set in cookie. Both tokens are rotated on every call.

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Missing, expired, or revoked refresh token |

---

### POST /auth/logout
**Auth required:** No (uses httpOnly cookie)

**Request:** No body.

**Response:** `204 No Content`

Refresh token is revoked in DB. Cookie is cleared.

---

## 3. User Profile

### GET /users/me
**Auth required:** Yes

Fetch the authenticated user's own profile.

**Response (200):**
```json
{
  "id": "<uuid>",
  "name": "Abhinav",
  "email": "abhinav@example.com",
  "phone_number": "+91XXXXXXXXXX",
  "created_at": "2026-03-20T10:00:00Z"
}
```

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Not authenticated |

> ðŸ“ **Engineering Note:** `/users/me` is the standard pattern for "current user's profile" (used by GitHub, Spotify, Discord). The user never needs to know their own UUID.

---

### PATCH /users/me
**Auth required:** Yes

Update name or phone number. Send only the fields being changed.

**Request:**
```json
{
  "name": "Abhinav Kumar",
  "phone_number": "+91XXXXXXXXXX"
}
```

**Response (200):**
```json
{
  "id": "<uuid>",
  "name": "Abhinav Kumar",
  "email": "abhinav@example.com",
  "phone_number": "+91XXXXXXXXXX",
  "created_at": "2026-03-20T10:00:00Z"
}
```

**Errors:**
| Code | Reason |
|------|--------|
| `400` | Invalid phone number format |
| `401` | Not authenticated |

> ðŸ“ **Engineering Note:** Email and password are not updatable here â€” those require dedicated flows with extra verification steps (e.g. confirm old password before setting new one). Deferred to v2.

---

## 4. Topics

### POST /topics
**Auth required:** Yes

Create a new tracked topic for the authenticated user.

**Request:**
```json
{
  "name": "AI chips",
  "description": "optional keywords or context e.g. NVIDIA, 
                  AMD, semiconductors, AI accelerators",
  "threshold": 0.7
}
```

**Response (201):**
```json
{
  "id": "<uuid>",
  "name": "AI chips",
  "description": null,
  "expanded_description": "Gemini-generated expansion stored here",
  "threshold": 0.7,
  "is_active": true,
  "created_at": "2026-03-20T10:00:00Z"
}
```

**Errors:**
| Code | Reason |
|------|--------|
| `400` | Missing name, or threshold outside 0.0â€“1.0 |
| `401` | Not authenticated |
| `409` | User already has a topic with this name |
| `503` | Gemini API unavailable during topic expansion |

> 📝 **Engineering Note:** On POST /topics, the backend performs three steps automatically:
> 1. Takes name + description (if provided) and calls Gemini to generate expanded_description — a richer semantic description of the topic that produces a more meaningful embedding
> 2. Runs Sentence-BERT on expanded_description to generate the 384-dim embedding
> 3. Stores description, expanded_description, and embedding in PostgreSQL
> The client never sends or receives embeddings directly.

---

### GET /topics
**Auth required:** Yes

List all topics belonging to the authenticated user. Paginated.

**Query params:**
```
?page=1&limit=20
```

**Response (200):**
```json
{
  "data": [
    {
      "id": "<uuid>",
      "name": "AI chips",
      "threshold": 0.7,
      "is_active": true,
      "created_at": "2026-03-20T10:00:00Z"
    },
    {
      "id": "<uuid>",
      "name": "Climate policy",
      "threshold": 0.6,
      "is_active": false,
      "created_at": "2026-03-18T08:00:00Z"
    }
  ],
  "total_count": 2,
  "page": 1,
  "limit": 20
}
```

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Not authenticated |

---

### GET /topics/{topic_id}
**Auth required:** Yes

Fetch a single topic by ID.

**Response (200):**
```json
{
  "id": "<uuid>",
  "name": "AI chips",
  "threshold": 0.7,
  "is_active": true,
  "created_at": "2026-03-20T10:00:00Z"
}
```

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Not authenticated |
| `404` | Not found (or belongs to another user) |

---

### PATCH /topics/{topic_id}
**Auth required:** Yes

Update topic name, threshold, or active status. Send only the fields being changed.

**Request (examples â€” send any combination):**
```json
{
  "name": "AI semiconductors",
  "threshold": 0.75,
  "is_active": false
}
```

**Response (200):** Full topic object with updated values.

**Errors:**
| Code | Reason |
|------|--------|
| `400` | Invalid threshold value |
| `401` | Not authenticated |
| `404` | Not found (or belongs to another user) |

> 📝 **Engineering Note:** When name OR description changes, the backend must:
> 1. Call Gemini with the updated name + description to regenerate expanded_description
> 2. Re-run Sentence-BERT on the new expanded_description to regenerate the embedding
> 3. Update expanded_description and embedding in PostgreSQL
> The client only sends name and/or description — all downstream regeneration is handled server-side automatically.

> ðŸ“ **Engineering Note:** Pausing/resuming a topic (`is_active: false / true`) uses this same endpoint. No separate `/pause` endpoint needed â€” PATCH is flexible enough. Fewer endpoints = less surface area to maintain.

---

### DELETE /topics/{topic_id}
**Auth required:** Yes

Delete a topic and all associated data.

**Response:** `204 No Content`

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Not authenticated |
| `404` | Not found (or belongs to another user) |

> ðŸ“ **Engineering Note:** The `topics` table has `ON DELETE CASCADE` to `topic_channels` and `article_topic_matches`. Deleting a topic automatically removes its channels and match history â€” PostgreSQL handles this, no manual cleanup needed in application code.

---

### PUT /topics/{topic_id}/channels
**Auth required:** Yes

Replace the entire channel configuration for a topic. Send the complete desired list of channels â€” any channels not included are removed.
Note: "Dashboard only" alerts means the user selects the `websocket` channel exclusively.

**Request:**
```json
[
  { "channel": "websocket" },
  { "channel": "email" }
]
```

**Response (200):**
```json
[
  { "channel": "websocket" },
  { "channel": "email" }
]
```

**Errors:**
| Code | Reason |
|------|--------|
| `400` | Invalid channel value (must be `email`, `sms`, or `websocket`) |
| `401` | Not authenticated |
| `404` | Topic not found (or belongs to another user) |


---

## 5. Alerts

### GET /alerts
**Auth required:** Yes

List all alerts for the authenticated user. Supports filtering and pagination. This is the primary endpoint for both the main dashboard feed and the per-topic timeline view.

**Query params:**
```
?topic_id=<uuid>     â€” filter alerts to a specific topic (used for timeline view)
?page=1&limit=20     â€” pagination
```

**Response (200):**
```json
{
  "data": [
    {
      "id": "<uuid>",
      "topic_id": "<uuid>",
      "topic_name": "AI chips",
      "article_id": "<uuid>",
      "headline": "NVIDIA announces H200 chip",
      "summary": "NVIDIA unveiled its next generation H200 chip targeting AI workloads...",
      "source_url": "https://techcrunch.com/...",
      "source_name": "TechCrunch",
      "relevance_score": 0.89,
      "channel": "websocket",
      "created_at": "2026-03-20T10:00:00Z"
    }
  ],
  "total_count": 143,
  "page": 1,
  "limit": 20
}
```

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Not authenticated |

> ðŸ“ **Engineering Note:** `topic_name`, `headline`, `summary`, `source_url`, and `source_name` are not in the `alerts` table â€” the backend joins `topics`, `articles`, and `sources` to assemble this response. This is called **response shaping**: return exactly what the UI needs in one call, avoiding multiple round trips.

> ðŸ“ **Engineering Note:** `?topic_id=<uuid>` is how the per-topic timeline page filters alerts. No separate endpoint needed â€” one flexible endpoint serves both the main feed and the topic timeline.

---

### DELETE /alerts/{alert_id}
**Auth required:** Yes

Delete a single alert from the user's history.

**Response:** `204 No Content`

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Not authenticated |
| `404` | Not found (or belongs to another user) |

---

## 6. Analytics

> **TODO:** Analytics endpoint design is postponed to the analytics design phase.

---

## 7. Articles

### GET /articles/{article_id}
**Auth required:** Yes

Fetch full detail for a single article. Optional endpoint â€” the `GET /alerts` response already includes headline, summary, and source for display. This endpoint is for cases where the frontend needs additional detail (e.g. credibility score, full crawled content).

**Response (200):**
```json
{
  "id": "<uuid>",
  "headline": "NVIDIA announces H200 chip",
  "summary": "NVIDIA unveiled its next generation H200 chip...",
  "source_url": "https://techcrunch.com/...",
  "source_name": "TechCrunch",
  "credibility_score": 0.85,
  "published_at": "2026-03-20T09:00:00Z",
  "crawled_at": "2026-03-20T09:05:00Z"
}
```

**Errors:**
| Code | Reason |
|------|--------|
| `401` | Not authenticated |
| `404` | Not found |

> ðŸ“ **Engineering Note:** Auth is required even though articles feel like "public content." In this system, articles are internal pipeline output â€” not a public feed. Exposing them unauthenticated would allow anyone to enumerate article UUIDs and read pipeline output.

> ðŸ“ **Engineering Note:** The Gemini-generated summary is stored once on the article and reused for every user who receives an alert about it. This is the cost control mechanism â€” ~10-15 Gemini API calls per crawl cycle regardless of how many users match that article.

---

## 8. WebSocket

WebSocket is a persistent, full-duplex connection. Unlike REST, there are no request/response cycles â€” the server pushes messages to the client at any time.

### 8.1 WebSocket Ticket Flow

- WHY: JWT in URL appears in nginx logs, server logs, and browser history Ã¢â‚¬â€ unacceptable security risk
- Step 1: Client calls `POST /ws/ticket` with JWT in `Authorization` header (never in URL)
- Step 2: Server generates a random UUID ticket, stores in Redis as `ws_ticket:{ticket_id} Ã¢â€ â€™ user_id` with 30 second expiry
- Step 3: Server returns `{ "ticket": "<uuid>" }`
- Step 4: Client opens `WS /ws?ticket=<uuid>`
- Step 5: Server looks up ticket in Redis. Not found Ã¢â€ â€™ reject with `4001` close code. Found Ã¢â€ â€™ delete ticket from Redis first (atomic consumption), then extract `user_id`, then establish connection.
- Deletion happens BEFORE connection is established Ã¢â‚¬â€ prevents two simultaneous requests using the same ticket (atomic consumption pattern)

### Connection

```
WS /ws?ticket=<ticket>
```

The client connects using a one-time ticket issued by `POST /ws/ticket`. The backend validates the ticket on connection. Invalid, expired, or already-consumed tickets are rejected immediately with a `4001` close code.

**Connection lifecycle:**
1. Client opens connection with valid token
2. Backend validates ticket against Redis, extracts `user_id`, deletes ticket, registers connection in memory
3. Alert service checks active connections on fan-out â€” pushes to connected users instantly
4. Client closes tab or navigates away â†’ connection closes â†’ backend removes from active connections

---

### Server â†’ Client: New Alert Event

Pushed by the alert service the moment a new matched article is ready for the user.

```json
{
  "event": "new_alert",
  "data": {
    "id": "<uuid>",
    "topic_id": "<uuid>",
    "topic_name": "AI chips",
    "headline": "NVIDIA announces H200 chip",
    "summary": "NVIDIA unveiled its next generation H200 chip...",
    "source_url": "https://techcrunch.com/...",
    "source_name": "TechCrunch",
    "relevance_score": 0.89,
    "created_at": "2026-03-20T10:00:00Z"
  }
}
```

> ðŸ“ **Engineering Note:** The `event` field is intentional. As the system grows, the server may push other event types (e.g. `topic_paused`, `system_notice`). Having an `event` field lets the frontend switch on the type and handle each differently â€” rather than assuming every message is an alert.

---

### 8.2 Connection Management

- All WebSocket connection logic is isolated inside a single `ConnectionManager` class
- `ConnectionManager` maintains an in-memory dictionary: `user_id â†’ websocket connection`
- Four methods: `connect(user_id, websocket)`, `disconnect(user_id)`, `push(user_id, message)`, `broadcast(user_ids: list, message)`
- No other part of the codebase touches WebSocket connections directly

### 8.3 Scaling Strategy (Future â€” Redis Pub/Sub Backplane)

- In-memory connections break when running multiple FastAPI instances
- Solution: Redis Pub/Sub where each FastAPI instance subscribes to all user channels named `"user:{user_id}"`
- Alert service publishes to Redis instead of calling `push()` directly
- Each instance receives the broadcast, checks local dictionary, delivers only if it holds that connection
- Redis is already in the stack as Celery's broker â€” zero new infrastructure required
- To implement: only `ConnectionManager` internals change, nothing else in the codebase is affected

---

## 9. Full Endpoint Index

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `POST` | `/auth/register` | No | Register new user |
| `POST` | `/auth/login` | No | Login, receive access token |
| `POST` | `/auth/refresh` | No (cookie) | Rotate tokens |
| `POST` | `/auth/logout` | No (cookie) | Revoke refresh token |
| `GET` | `/users/me` | Yes | Get own profile |
| `PATCH` | `/users/me` | Yes | Update name / phone |
| `POST` | `/topics` | Yes | Create topic |
| `GET` | `/topics` | Yes | List all topics (paginated) |
| `GET` | `/topics/{id}` | Yes | Get single topic |
| `PATCH` | `/topics/{id}` | Yes | Update name / threshold / active status |
| `DELETE` | `/topics/{id}` | Yes | Delete topic |
| `PUT` | `/topics/{id}/channels` | Yes | Replace channel config |
| `GET` | `/alerts` | Yes | List alerts (filterable, paginated) |
| `DELETE` | `/alerts/{id}` | Yes | Delete alert |
| `GET` | `/analytics/trends` | Yes | Topic trend snapshots |
| `GET` | `/articles/{id}` | Yes | Article detail |
| `POST` | `/ws/ticket` | Yes | Obtain one-time WebSocket connection ticket |
| `WS` | `/ws?ticket=<ticket>` | Yes (query param) | Real-time alert delivery |

---

> This document was produced as part of Phase 3 (Low-Level Design).
> Depends on: `schema.sql`, `auth-lld.md`
> Next LLD section: Pipeline Low-Level Design





