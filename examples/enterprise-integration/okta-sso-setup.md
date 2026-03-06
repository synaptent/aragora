# Okta SSO Integration Guide

This guide walks through configuring Okta as an SSO provider for Aragora, enabling enterprise single sign-on with OIDC.

## Prerequisites

- Okta organization with admin access
- Aragora server v2.8.0+ with SSO enabled
- HTTPS endpoint for your Aragora deployment
- Network connectivity between Aragora and Okta

## Architecture Overview

```
User Browser          Aragora Server           Okta
     |                     |                    |
     |--[1] Login-------->|                    |
     |<-[2] Redirect------|                    |
     |--[3] Authenticate---------------------->|
     |<-[4] Auth Code-------------------------|
     |--[5] Callback----->|                    |
     |                    |--[6] Token-------->|
     |                    |<-[7] ID Token------|
     |<-[8] JWT Token-----|                    |
```

---

## Part 1: Okta Configuration

### Step 1: Create OIDC Application

1. Log into your Okta Admin Console
2. Navigate to **Applications > Applications**
3. Click **Create App Integration**
4. Select:
   - Sign-in method: **OIDC - OpenID Connect**
   - Application type: **Web Application**
5. Click **Next**

### Step 2: Configure Application Settings

**General Settings:**
```
App integration name: Aragora
Logo: (optional - upload your logo)
```

**Sign-in redirect URIs:**
```
https://your-aragora-domain.com/api/v1/auth/sso/callback
```

For local development, also add:
```
http://localhost:8080/api/v1/auth/sso/callback
```

**Sign-out redirect URIs:**
```
https://your-aragora-domain.com/
```

**Controlled access:**
- Select "Limit access to selected groups" or "Allow everyone" based on your policy

Click **Save**.

### Step 3: Collect Credentials

After saving, note these values from the **General** tab:

| Setting | Example Value |
|---------|---------------|
| Client ID | `0oa1234567890abcdef` |
| Client Secret | `AbCdEfGhIjKlMnOpQrStUvWxYz123456` |
| Okta Domain | `https://yourcompany.okta.com` |

### Step 4: Configure Claims (Optional)

To pass group memberships to Aragora for role mapping:

1. Go to **Sign On** tab
2. Click **Edit** in OpenID Connect ID Token section
3. Add a Groups claim:
   - Name: `groups`
   - Include in token type: **ID Token** (Always)
   - Value type: **Groups**
   - Filter: Matches regex `.*` (or specific groups)
4. Click **Save**

### Step 5: Assign Users

1. Go to **Assignments** tab
2. Click **Assign > Assign to People** or **Assign to Groups**
3. Select users/groups who should access Aragora
4. Click **Done**

---

## Part 2: Aragora Configuration

### Step 1: Set Environment Variables

Add these to your `.env` or environment:

```bash
# Enable SSO
ARAGORA_SSO_ENABLED=true
ARAGORA_SSO_PROVIDER_TYPE=okta

# Okta Credentials (from Step 3 above)
ARAGORA_SSO_CLIENT_ID=0oa1234567890abcdef
ARAGORA_SSO_CLIENT_SECRET=AbCdEfGhIjKlMnOpQrStUvWxYz123456
ARAGORA_SSO_ISSUER_URL=https://yourcompany.okta.com

# Callback URL (must match Okta redirect URI)
ARAGORA_SSO_CALLBACK_URL=https://your-aragora-domain.com/api/v1/auth/sso/callback

# Optional: Restrict to specific email domains
ARAGORA_SSO_ALLOWED_DOMAINS=yourcompany.com,subsidiary.com

# Optional: Session duration (default 8 hours)
ARAGORA_SSO_SESSION_DURATION=28800

# Optional: Auto-create users on first login
ARAGORA_SSO_AUTO_PROVISION=true
```

### Step 2: Configure Group-to-Role Mapping (Optional)

Map Okta groups to Aragora roles in your configuration:

```python
# In aragora/config/sso_mapping.py or via environment

ARAGORA_SSO_ROLE_MAPPING = {
    "Aragora-Admins": "admin",
    "Aragora-Developers": "developer",
    "Aragora-Viewers": "viewer",
    "Everyone": "user"
}
```

Or via environment variable (JSON format):
```bash
ARAGORA_SSO_ROLE_MAPPING='{"Aragora-Admins":"admin","Aragora-Developers":"developer"}'
```

### Step 3: Start Aragora

```bash
# Docker
docker compose up -d

# Or directly
aragora serve --api-port 8080 --ws-port 8765
```

### Step 4: Verify Configuration

Check the SSO configuration endpoint:

```bash
curl https://your-aragora-domain.com/api/v1/auth/sso/providers
```

Expected response:
```json
{
  "providers": [
    {
      "id": "okta",
      "name": "Okta",
      "type": "oidc",
      "enabled": true
    }
  ]
}
```

---

## Part 3: Testing the Integration

### Test Login Flow

1. **Initiate Login:**
   ```bash
   curl -i "https://your-aragora-domain.com/api/v1/auth/sso/login?provider=okta"
   ```

   Response includes `authorization_url` - open in browser.

2. **Complete Okta Login:**
   - Enter your Okta credentials
   - Complete MFA if configured
   - Approve the application access

3. **Handle Callback:**
   - Okta redirects to your callback URL
   - Aragora exchanges the code for tokens
   - User receives JWT token

### Verify Token

```bash
curl -H "Authorization: Bearer <jwt_token>" \
  https://your-aragora-domain.com/api/v1/users/me
```

Expected response:
```json
{
  "id": "user_abc123",
  "email": "user@yourcompany.com",
  "name": "John Doe",
  "roles": ["developer"],
  "sso_provider": "okta"
}
```

---

## Part 4: Frontend Integration

### React Example

```typescript
// src/auth/okta.ts
const SSO_LOGIN_URL = '/api/v1/auth/sso/login';

export async function initiateOktaLogin(redirectPath: string = '/') {
  const params = new URLSearchParams({
    provider: 'okta',
    redirect_url: redirectPath
  });

  const response = await fetch(`${SSO_LOGIN_URL}?${params}`);
  const { authorization_url } = await response.json();

  // Redirect to Okta
  window.location.href = authorization_url;
}

// Handle callback in your router
export async function handleSSOCallback(code: string, state: string) {
  const response = await fetch('/api/v1/auth/sso/callback', {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' }
  });

  const { token, user } = await response.json();

  // Store token
  localStorage.setItem('aragora_token', token);

  return user;
}
```

### Login Button Component

```tsx
// src/components/OktaLoginButton.tsx
import { initiateOktaLogin } from '../auth/okta';

export function OktaLoginButton() {
  return (
    <button
      onClick={() => initiateOktaLogin()}
      className="btn-okta"
    >
      Sign in with Okta
    </button>
  );
}
```

---

## Part 5: Security Considerations

### PKCE (Enabled by Default)

Aragora uses PKCE (Proof Key for Code Exchange) to prevent authorization code interception:

```

  Browser        Aragora        Okta
     |              |             |
     |--Login----->|             |
     |             |--code_challenge----------->|
     |<--auth_url--|             |
     |--authenticate------------>|
     |<--code--------------------|
     |--callback-->|             |
     |             |--code + code_verifier----->|
     |             |<--tokens----|
     |<--jwt-------|             |
```

### Token Validation

Aragora validates all tokens against Okta's JWKS endpoint:

- Signature verification (RS256/ES256)
- Issuer validation
- Audience validation
- Expiration check
- Nonce verification (replay protection)

### Recommended Security Settings

```bash
# Enforce HTTPS
ARAGORA_FORCE_HTTPS=true

# Strict cookie settings
ARAGORA_SECURE_COOKIES=true
ARAGORA_COOKIE_SAMESITE=strict

# Session timeout (8 hours recommended)
ARAGORA_SSO_SESSION_DURATION=28800

# Restrict domains
ARAGORA_SSO_ALLOWED_DOMAINS=yourcompany.com
```

---

## Part 6: Troubleshooting

### Common Issues

#### "Invalid redirect_uri"
**Cause:** Callback URL mismatch between Aragora and Okta.

**Solution:** Ensure `ARAGORA_SSO_CALLBACK_URL` exactly matches the redirect URI in Okta, including protocol (https) and path.

#### "Client authentication failed"
**Cause:** Invalid client credentials.

**Solution:** Verify `ARAGORA_SSO_CLIENT_ID` and `ARAGORA_SSO_CLIENT_SECRET` match Okta application settings.

#### "Token validation failed"
**Cause:** Clock skew or invalid issuer.

**Solution:**
1. Sync server time with NTP
2. Verify `ARAGORA_SSO_ISSUER_URL` matches your Okta domain exactly

#### "User not authorized"
**Cause:** User not assigned to application in Okta.

**Solution:** Assign user or their group to the Okta application.

#### Groups not appearing in token
**Cause:** Groups claim not configured.

**Solution:** Configure groups claim in Okta (see Step 4 in Part 1).

### Debug Mode

Enable SSO debug logging:

```bash
ARAGORA_LOG_LEVEL=DEBUG
ARAGORA_SSO_DEBUG=true
```

View logs:
```bash
docker compose logs aragora | grep -i "sso\|oidc\|okta"
```

### Test Token Locally

```python
from aragora.auth.oidc import OIDCConfig, OIDCProvider

config = OIDCConfig.for_okta(
    org_url="https://yourcompany.okta.com",
    client_id="your-client-id",
    client_secret="your-client-secret",
    callback_url="http://localhost:8080/api/v1/auth/sso/callback"
)

provider = OIDCProvider(config)

# Get authorization URL
auth_url = await provider.get_authorization_url(
    state="test-state",
    nonce="test-nonce"
)
print(f"Auth URL: {auth_url}")
```

---

## Part 7: Production Checklist

- [ ] HTTPS enabled on Aragora endpoint
- [ ] Client secret stored securely (not in code)
- [ ] Callback URLs use production domain
- [ ] Email domain restrictions configured
- [ ] Group-to-role mapping configured
- [ ] Session duration appropriate for security policy
- [ ] Audit logging enabled
- [ ] Tested with multiple user accounts
- [ ] Tested logout flow
- [ ] Documented for end users

---

## API Reference

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/auth/sso/login` | Initiate SSO login |
| GET | `/api/v1/auth/sso/callback` | Handle OAuth callback |
| POST | `/api/v1/auth/sso/refresh` | Refresh access token |
| POST | `/api/v1/auth/sso/logout` | Logout user |
| GET | `/api/v1/auth/sso/providers` | List configured providers |

### Login Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `provider` | Yes | SSO provider ID (`okta`) |
| `redirect_url` | No | URL to redirect after login |

### Callback Response

```json
{
  "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 28800,
  "token_type": "Bearer",
  "user": {
    "id": "user_abc123",
    "email": "user@example.com",
    "name": "John Doe",
    "roles": ["developer"]
  }
}
```

---

## Next Steps

- [Configure SAML SSO](./saml-sso-setup.md) (alternative to OIDC)
- [Multi-tenant SSO](./multi-tenant-sso.md) (per-tenant IdP configuration)
- [SSO with MFA](./sso-mfa.md) (enforcing MFA via Okta)
- [User Provisioning](./scim-provisioning.md) (SCIM for user sync)

---

## Support

For issues with Aragora SSO integration:
- Check [Aragora GitHub Issues](https://github.com/aragora/aragora/issues)
- Review [SSO documentation](https://docs.aragora.ai/enterprise/sso)

For Okta-specific issues:
- [Okta Developer Documentation](https://developer.okta.com/docs/)
- [Okta Community](https://devforum.okta.com/)
