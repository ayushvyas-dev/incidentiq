# JWT Verification Failure and JWKS Key Rotation

When authentication service returns 401 Unauthorized for valid tokens after IdP key rotation, check JWKS cache TTL and outbound network connectivity to identity provider well-known endpoint. Ensure JWKS client supports stale-while-revalidate and caches public keys across transient network errors.
