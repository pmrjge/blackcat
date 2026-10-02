---
name: sec-authn-authz
description: Use when building login, sessions, JWTs, OAuth/OIDC, authorization checks or password storage.
---
# Authentication and authorization
Hub: `secure-coding`.

- Use proven identity providers and libraries; no home-grown auth protocols.
- **Sessions:** server-side, ≥ 128-bit random IDs, rotated at login and privilege change, idle and absolute timeouts, cookies `__Host-` prefixed with `Secure; HttpOnly; SameSite=Lax` (or `Strict`); logout invalidates server-side.
- **JWTs:** verify with an algorithm allowlist (`jwt.decode(token, key, algorithms=["RS256"], audience=AUD, issuer=ISS)` in PyJWT), reject `none` and HS/RS confusion, check `exp`/`nbf`/`aud`/`iss`, short lifetimes, refresh-token rotation with reuse detection; long-lived tokens do not belong in `localStorage`.
- **OAuth 2.0 / OIDC** (RFC 9700 is the security BCP; unverified as of 2026-10-02): authorization code + PKCE (S256) for every client, exact redirect-URI matching, `state` and OIDC `nonce` validated, no implicit or password grants, minimal scopes, audience-restricted tokens — never forward a token issued for one service to another.
- **Authorization:** deny by default; enforce server-side on every request at object level (IDOR/BOLA: does this caller own object 123?), function level and field level; one central policy function; tests with two users and one admin.
- **Passwords** (OWASP): argon2id (e.g. m = 19 MiB, t = 2, p = 1 or m = 46 MiB, t = 1, p = 1), bcrypt cost ≥ 10 (72-byte input limit; legacy systems), scrypt N = 2^17, r = 8, p = 1, or PBKDF2-HMAC-SHA256 with 600,000 iterations where FIPS applies; rehash on login when parameters change; rate limiting; MFA (passkeys/WebAuthn over TOTP over SMS). Hashing code: `sec-crypto`.
- **Least privilege:** scoped service accounts, separate read and write credentials, short-lived federated cloud credentials over static keys, containers as non-root with read-only filesystems and dropped capabilities (`sec-hardening`).

## Verify
- [ ] Two-user test: user A cannot read, update or delete user B's object through any route (IDOR/BOLA).
- [ ] Tampered, expired, wrong-audience and `alg: none` tokens are rejected by tests.
- [ ] Session ID changes at login; logout invalidates the server-side session (replay the old cookie).
- [ ] Password hash parameters match the values above or stronger.

## Sources
- Verified 2026-10-02 https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html — argon2id m=19 MiB t=2 p=1 (or m=46 MiB t=1 p=1), bcrypt ≥ 10 (legacy, 72 bytes), scrypt N=2^17 r=8 p=1, PBKDF2-HMAC-SHA256 600,000.
