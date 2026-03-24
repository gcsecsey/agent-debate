### Approach
Whichever auth strategy we choose, the critical concerns are: secure token/session storage, proper HTTPS enforcement, rate limiting on auth endpoints, and audit logging. I lean toward JWT for its explicit security model, but with important caveats.

### Key Decisions
1. **HTTPS-only with HSTS** — All auth endpoints must enforce TLS. No exceptions.
2. **Rate limiting on login/refresh** — Prevent brute force attacks. Use sliding window rate limiter.
3. **Audit logging** — Every auth event (login, logout, token refresh, failed attempt) must be logged with timestamp, IP, and user agent.
4. **JWT with short expiry (15min)** — Limits the damage window if a token is compromised.

### Trade-offs
- Gaining: Defense in depth, audit trail, brute-force protection
- Giving up: More implementation work upfront, slightly more complex request flow

### Concerns
- JWT without server-side revocation is dangerous — if a token leaks, you can't invalidate it until expiry
- Rate limiting needs to be per-user AND per-IP to prevent both targeted and distributed attacks
- Audit logs must not contain tokens themselves (PII/security risk)

### Proposed Changes
Add `src/middleware/rate_limiter.py`, `src/middleware/audit_logger.py`. Modify auth endpoints to emit audit events. Add HSTS headers in `src/middleware/security_headers.py`.
