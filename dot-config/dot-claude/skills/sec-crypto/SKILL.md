---
name: sec-crypto
description: Use when code encrypts, signs, hashes, derives keys or sets up TLS — vetted libraries, AEAD, nonces.
---
# Cryptography
Hub: `secure-coding`.

- Vetted high-level APIs only: Python `cryptography` (AEAD `AESGCM`, `ChaCha20Poly1305`; `Fernet`), libsodium/PyNaCl (XChaCha20-Poly1305, sealed boxes), RustCrypto AEAD crates or `ring`, Go `crypto/*`, WebCrypto. Protocols: TLS, Noise, age — don't design your own.
- Authenticated encryption only (no ECB, no unauthenticated CBC/CTR). Nonces unique per key: AES-GCM with random 96-bit nonces is limited to 2^32 messages per key; XChaCha20 (192-bit nonces) makes random nonces safe; a repeated GCM nonce leaks the authentication key and plaintext XOR.
- Integrity: SHA-256/SHA-3/BLAKE2/BLAKE3; MACs: HMAC-SHA256; never MD5/SHA-1 for security. Signatures: Ed25519 (or ECDSA P-256 via a vetted library); verify before parsing signed data.
- Keys from a KMS or keychain, one key per purpose (HKDF for derivation), rotation planned; TLS verification always on (no `verify=False`, `InsecureSkipVerify`), TLS 1.2+ (prefer 1.3).
- Randomness and constant-time comparison: `sec-secrets`. Password hashing parameters: `sec-authn-authz`.

```python
from argon2 import PasswordHasher                               # argon2-cffi: argon2id, m=64 MiB, t=3, p=4 by default
ph = PasswordHasher(); stored = ph.hash(password)
ph.verify(stored, attempt)                                      # raises VerifyMismatchError; then ph.check_needs_rehash(stored)

import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key = AESGCM.generate_key(bit_length=256)                       # from a KMS/keychain in real code
nonce = os.urandom(12)                                          # unique per message under this key
ct = AESGCM(key).encrypt(nonce, plaintext, b"context-v1")       # store nonce with ct; AAD binds context
```

## Verify
- [ ] No primitive-level crypto outside a vetted library; grep for `ECB`, `MD5`, `SHA1`, `verify=False`, `InsecureSkipVerify`, `random.` in security paths.
- [ ] Nonce strategy written down per key (random 96-bit with a message cap, counter, or XChaCha20).
- [ ] Round-trip test plus a tamper test (flip one ciphertext byte or AAD → decryption fails).

## Sources
- Verified 2026-10-02 https://argon2-cffi.readthedocs.io/en/stable/api.html — `PasswordHasher` defaults time_cost=3, memory_cost=65536 KiB, parallelism=4 (RFC 9106 low-memory profile).
