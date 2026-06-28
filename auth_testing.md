# MG-VMS — Auth Testing

Auth uses JWT Bearer tokens (returned in login response body), sent as `Authorization: Bearer <token>`.

## Accounts (see /app/memory/test_credentials.md)
- admin@mg-vms.com / Admin@2026 (admin)
- tech@mg-vms.com / Tech@2026 (technician)
- client@mg-vms.com / Client@2026 (client)
- viewer@mg-vms.com / Viewer@2026 (readonly)

## API checks
```
curl -X POST $URL/api/auth/login -H "Content-Type: application/json" -d '{"email":"admin@mg-vms.com","password":"Admin@2026"}'
# -> {access_token, refresh_token, user}
TOKEN=...
curl $URL/api/auth/me -H "Authorization: Bearer $TOKEN"
```
- Wrong password -> 401 "Email ou mot de passe invalide"
- RBAC: readonly cannot POST /api/users (403), admin can.
- 2FA: POST /api/auth/2fa/setup returns secret+otpauth_uri; verify with TOTP code.
