# Authentication — Low-Level Design

> **Section:** 3.2 — Authentication & Authorization
> **Phase:** 3 — Low-Level Design
> **Depends on:** schema.sql (users table)

---

## 1. Mechanism: NextAuth (Frontend) + Google OAuth

Rather than building custom login/register flows, authentication is delegated to **NextAuth** running on the Next.js frontend with a Google OAuth provider.

**Why this is simpler and better:**

| Concern | Custom JWT approach | NextAuth + Google |
|---------|--------------------|--------------------|
| Password management | Build register, login, bcrypt, reset | Google handles it |
| Session refresh | Build refresh token rotation | NextAuth handles it |
| Security surface area | Large (hash bugs, timing attacks, enumeration) | Small (just token verification) |
| User experience | Email + password form | "Sign in with Google" |
| Backend complexity | High (4 endpoints, refresh_tokens table) | Low (one verification function) |

The backend's only auth responsibility is **verifying** that a token presented to the API was legitimately issued by NextAuth.

---

## 2. Authentication Flow

```
User clicks "Sign in with Google"
        ↓
Next.js (NextAuth) redirects to Google OAuth consent screen
        ↓
Google authenticates the user, returns an authorization code
        ↓
NextAuth exchanges code for Google ID token, extracts profile (name, email, google_sub)
        ↓
NextAuth issues its own JWT, signed with AUTH_SECRET (shared with FastAPI)
        ↓
Frontend stores the NextAuth JWT (in memory or httpOnly cookie — NextAuth manages this)
        ↓
Frontend includes JWT in every API request:
    Authorization: Bearer <nextauth_jwt>
        ↓
FastAPI verifies the JWT signature using AUTH_SECRET
        ↓
FastAPI extracts user identity (email, google_sub) and looks up or creates the user in DB
        ↓
Request proceeds with injected user_id
```

---

## 3. NextAuth JWT Structure

NextAuth issues its own JWT (not the raw Google ID token). The payload contains:

```json
{
  "sub": "<google_subject_id>",
  "email": "user@gmail.com",
  "name": "Abhinav Dev",
  "iat": 1711234000,
  "exp": 1711320400
}
```

- `sub` — Google's permanent, stable identifier for the user (never changes even if they change email)
- `email` — used as the human-readable identifier
- Signed with `AUTH_SECRET` using HS256 — the same secret must be set in both Next.js and FastAPI

> ⚠️ NextAuth JWT payload is base64 encoded, NOT encrypted. Do not store sensitive data in it.

---

## 4. FastAPI Token Verification

Every protected endpoint uses a FastAPI dependency `get_current_user` that:

```
1. Extract JWT from Authorization header → 401 if missing
2. Verify HS256 signature using AUTH_SECRET → 401 if invalid or tampered
3. Check exp claim → 401 if expired
4. Extract sub (google_sub) and email from payload
5. Look up user in DB by google_sub → if not found, create user (just-in-time provisioning)
6. Return user object — injected into route handler
```

**Library:** `PyJWT` (already available; `python-jose` can be removed from requirements.txt since we no longer need the full JOSE stack).

---

## 5. Just-in-Time User Provisioning

There is no `/auth/register` endpoint. Instead, a user record is auto-created the first time a valid NextAuth token is presented to any protected endpoint.

**Logic:**
```
1. Verify token → extract google_sub, email, name
2. SELECT * FROM users WHERE google_sub = :sub
3. If found → return user
4. If not found → INSERT INTO users (name, email, google_sub) VALUES (:name, :email, :sub)
5. Return newly created user
```

This is a standard pattern for OAuth-based systems (used by GitHub, Linear, Notion). The user never experiences a "registration" step — they just sign in and their account exists.

**Race condition:** Two simultaneous first-requests from the same user could both attempt INSERT. The `UNIQUE` constraint on `google_sub` ensures only one succeeds; the other gets a conflict error. The dependency handles this by falling back to a SELECT on `UniqueViolation`.

---

## 6. WebSocket Authentication (Unchanged)

WebSocket connections cannot use the `Authorization` header — the browser WebSocket API doesn't support custom headers during the handshake. The ticket flow solves this:

- WHY: JWT in URL appears in nginx logs, server logs, and browser history — unacceptable security risk
- Step 1: Client calls `POST /ws/ticket` with JWT in `Authorization` header (never in URL)
- Step 2: Server generates a random UUID ticket, stores in Redis as `ws_ticket:{ticket_id} → user_id` with 30 second expiry
- Step 3: Server returns `{ "ticket": "<uuid>" }`
- Step 4: Client opens `WS /ws?ticket=<uuid>`
- Step 5: Server looks up ticket in Redis. Not found → reject with `4001` close code. Found → delete ticket from Redis first (atomic consumption), then extract `user_id`, then establish connection.
- Deletion happens BEFORE connection is established — prevents two simultaneous requests using the same ticket

---

## 7. Shared Secret Configuration

`AUTH_SECRET` must be set to the **same value** in both services:

| Service | Config key |
|---------|-----------|
| Next.js (NextAuth) | `AUTH_SECRET` in `.env.local` |
| FastAPI | `AUTH_SECRET` in `.env` |

Generate a strong secret once:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> ⚠️ If `AUTH_SECRET` differs between services, FastAPI will reject every token with 401. This is the most common misconfiguration when setting up this pattern.

---

## 8. What Was Removed Compared to the Original Design

| Removed | Reason |
|---------|--------|
| `/auth/register` endpoint | Google handles registration |
| `/auth/login` endpoint | Google handles login |
| `/auth/refresh` endpoint | NextAuth handles session refresh |
| `/auth/logout` endpoint | NextAuth handles logout |
| `refresh_tokens` table | Token rotation managed by NextAuth |
| `password_hash` column on users | No passwords — Google is the identity provider |
| bcrypt / passlib | No passwords to hash |
| `python-jose` library | Replaced by `PyJWT` (lighter, sufficient for HS256) |

---

## 9. Security Summary

| Threat | Mitigation |
|--------|-----------|
| Stolen access token | Short NextAuth JWT expiry (default 24h, configurable) |
| Forged tokens | HS256 signature verification with shared AUTH_SECRET |
| JWT in WebSocket URL | Ticket-based WS auth — JWT never appears in URLs |
| Account enumeration | No register/login endpoints to probe |
| Credential breach | No passwords stored — Google is the identity provider |
| DB breach exposing auth data | Only google_sub and email stored — neither usable for impersonation without Google account access |
