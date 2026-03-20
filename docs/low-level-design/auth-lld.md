# Authentication — Low-Level Design

> **Section:** 3.2 — Authentication & Authorization
> **Phase:** 3 — Low-Level Design
> **Depends on:** schema.sql (users, refresh_tokens tables)

---

## 1. Mechanism: JWT with Refresh Token Rotation

HTTP is stateless — the server has no memory of previous requests. After login, every request must prove identity. We use **JSON Web Tokens (JWT)** over session-based auth for one primary reason: access token verification requires no database lookup — just cryptographic signature verification. At 10,000 concurrent users this matters.

**Two-token strategy:**

| Token | Lifetime | Storage | Purpose |
|-------|----------|---------|---------|
| `access_token` | 15 minutes | JS memory | Authenticates every API request |
| `refresh_token` | 7 days | httpOnly cookie | Obtains new access tokens silently |

The short access token lifetime limits the damage window if a token is compromised. The refresh token's httpOnly cookie storage means JavaScript cannot read it — XSS attacks cannot steal it.

---

## 2. JWT Structure

A JWT has three base64-encoded parts separated by dots:

```
header.payload.signature
```

**Header:**
```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

**Payload (access token):**
```json
{
  "sub": "<user_uuid>",
  "exp": 1711234567,
  "iat": 1711234567
}
```

- `sub` — subject: the user's UUID. Only identifier needed.
- `exp` — expiry: Unix timestamp 15 minutes from issue time.
- `iat` — issued at: Unix timestamp of creation.

> ⚠️ JWT payload is base64 encoded, NOT encrypted. Never store sensitive data (passwords, PII) in a JWT.

**Signature:**
```
HMAC_SHA256(base64(header) + "." + base64(payload), SECRET_KEY)
```

The server verifies this signature on every request. Tampered tokens fail verification instantly — no DB lookup needed.

---

## 3. Refresh Token Design

> ℹ️ The refresh_tokens table below is part of schema.sql.
> It was identified as a gap during LLD cross-review and added
> in a later revision of the schema.

Refresh tokens are **random UUIDs**, not JWTs. They have no embedded data — they are looked up in the database on use.

**Storage rule:** Only the hash of the refresh token is stored in the DB. If the database is breached, raw tokens are useless to an attacker.

```sql
CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    is_revoked  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
```

---

## 4. Cookie Configuration

The refresh token is delivered and stored via an httpOnly cookie:

```
Set-Cookie: refresh_token=<token>;
            HttpOnly;
            Secure;
            SameSite=Strict;
            Path=/auth;
            Max-Age=604800
```

| Flag | Purpose |
|------|---------|
| `HttpOnly` | JS cannot read the cookie — XSS proof |
| `Secure` | Transmitted over HTTPS only |
| `SameSite=Strict` | Never sent from a different domain — CSRF proof |
| `Path=/auth` | Cookie only sent to `/auth/*` routes — minimises exposure |
| `Max-Age=604800` | 7 days in seconds |

---

## 5. API Endpoints

### POST /auth/register
**Request:**
```json
{
  "name": "Abhinav",
  "email": "abhinav@example.com",
  "password": "plaintext_password"
}
```
**Logic:**
1. Check email uniqueness — return `409` if duplicate
2. Hash password with bcrypt (cost factor 12)
3. Insert into `users`
4. Return `201` with user object (no tokens — require explicit login)

**Response (201):**
```json
{
  "id": "<uuid>",
  "name": "Abhinav",
  "email": "abhinav@example.com",
  "created_at": "2026-03-17T10:00:00Z"
}
```

---

### POST /auth/login
**Request:**
```json
{
  "email": "abhinav@example.com",
  "password": "plaintext_password"
}
```
**Logic:**
1. Fetch user by email — return `401` if not found
2. Verify bcrypt hash — return `401` if mismatch
3. Generate access_token (JWT, 15 min)
4. Generate refresh_token (UUID v4, 7 days)
5. Hash refresh_token, insert into `refresh_tokens`
6. Set refresh_token as httpOnly cookie
7. Return access_token in response body

> ⚠️ Always return `401` for both "user not found" and "wrong password". Never reveal which one failed — that leaks whether an email is registered.

**Response (200):**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

---

### POST /auth/refresh
**Request:** No body. Refresh token read from httpOnly cookie automatically.

**Logic:**
1. Read refresh_token from cookie — return `401` if missing
2. Hash it, look up in `refresh_tokens`
3. Not found → `401`
4. `is_revoked = true` → `401`
5. `expires_at` < now → `401`
6. Valid → issue new access_token
7. **Rotate:** revoke old refresh_token, generate + store new one, set new cookie

**Response (200):**
```json
{
  "access_token": "<new_jwt>",
  "token_type": "bearer"
}
```

---

### POST /auth/logout
**Request:** No body. Refresh token read from httpOnly cookie.

**Logic:**
1. Read refresh_token from cookie
2. Hash it, set `is_revoked = true` in DB
3. Clear the cookie (Set-Cookie with Max-Age=0)
4. Return `204`

**Response:** `204 No Content`

---

## 6. Request Authentication Flow

Every protected endpoint requires the access_token in the Authorization header:

```
Authorization: Bearer <access_token>
```

FastAPI dependency (applied to all protected routes):
```
1. Extract token from Authorization header → 401 if missing
2. Verify JWT signature using SECRET_KEY → 401 if invalid
3. Check exp claim → 401 if expired
4. Extract sub (user_id) from payload
5. Inject user_id into route handler
```

No database query in this flow. Pure cryptographic verification. ✅

---

## 7. Token Rotation — Why It Matters

On every `/auth/refresh` call, both tokens are rotated:
- Old refresh_token → `is_revoked = true`
- New refresh_token → issued and stored

**Why:** If an attacker steals a refresh_token and uses it before the legitimate user does, the legitimate user's next refresh attempt will fail (their token was already consumed). This is a signal of compromise. The system can then revoke all tokens for that user.

Without rotation, a stolen refresh_token silently grants access for its full 7-day lifetime.

---

## 8. Password Hashing

bcrypt with cost factor 12.

- Cost factor 12 = ~300ms per hash on modern hardware
- Slow enough to make brute force impractical
- Fast enough to be imperceptible to users
- bcrypt automatically salts each hash — no manual salt management needed

Never store plain text passwords. Never use MD5 or SHA-256 for passwords — they are too fast (designed for speed, not security).

---

## 9. Security Summary

| Threat | Mitigation |
|--------|-----------|
| XSS stealing refresh token | httpOnly cookie — JS cannot read it |
| CSRF using refresh token | SameSite=Strict cookie flag |
| Stolen access token | 15-minute expiry limits damage window |
| Stolen refresh token | Token rotation detects and limits reuse |
| DB breach exposing tokens | refresh_token stored as hash only |
| DB breach exposing passwords | bcrypt with cost factor 12 |
| User enumeration | Same 401 response for wrong email or password |
