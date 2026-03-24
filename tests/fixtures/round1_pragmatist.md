### Approach
Keep it simple: use session-based auth with secure cookies. The app is a monolith serving <10k users. JWT adds complexity we don't need yet. Sessions are battle-tested, easy to debug, and already supported by our framework.

If we outgrow sessions later, we can migrate. But right now, YAGNI applies.

### Key Decisions
1. **Session-based auth with secure cookies** — Framework-native, no additional dependencies. Simple to implement and debug.
2. **Database-backed sessions** — Use the existing PostgreSQL database. No need for Redis.
3. **CSRF protection via SameSite cookies** — Modern browsers handle this well. No custom token management needed.

### Trade-offs
- Gaining: Simplicity, faster implementation, fewer moving parts
- Giving up: Statelessness (sessions are server-side), harder to scale horizontally later

### Concerns
- If the app needs to go multi-service, sessions become harder to share
- But that's a future problem, not a current one

### Proposed Changes
Use the framework's built-in session middleware. Add `src/auth/views.py` for login/logout endpoints. Configure session settings in `src/config/settings.py`.
