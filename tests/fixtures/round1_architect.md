### Approach
I recommend implementing the authentication module using JWT tokens with a refresh token rotation strategy. The tokens should be stored server-side in Redis for revocation support, with the JWT containing minimal claims (user ID, roles).

The API gateway should handle token validation as middleware, keeping auth concerns out of individual services. This centralizes the security boundary.

### Key Decisions
1. **JWT with Redis-backed revocation** — Stateless verification for performance, with server-side revocation list for security. Trade-off: adds Redis dependency.
2. **Refresh token rotation** — Each refresh generates a new refresh token, invalidating the old one. Prevents replay attacks.
3. **Middleware-based validation** — Auth logic lives in the API gateway, not individual services. Reduces duplication and attack surface.

### Trade-offs
- Gaining: Centralized auth, stateless verification, revocation support
- Giving up: Added complexity from Redis dependency, token rotation logic

### Concerns
- Redis becoming a single point of failure for auth
- Token size growing if too many claims are added
- Need clear migration path from current session-based auth

### Proposed Changes
Add `src/middleware/auth.py` with JWT validation. Add `src/services/token_service.py` for token lifecycle management. Update `src/config/settings.py` with JWT configuration.
