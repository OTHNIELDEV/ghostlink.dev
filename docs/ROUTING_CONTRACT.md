# GhostLink Public Routing Contract (v1)

Updated: 2026-02-07

## Purpose
- Keep frontend, backend, and integrations aligned on stable public URLs.
- Prevent duplicated prefixes (example: `/billing/billing/*`, `/webhooks/webhooks/*`) from reappearing.

## Rule
- Prefix is declared in exactly one place:
  - either in `APIRouter(prefix=...)`
  - or in `app.include_router(..., prefix=...)`
- Never duplicate both for the same segment.

## Public Web Pages
- `GET /`
- `GET /dashboard`
- `GET /report/{site_id}`
- `GET /settings`
- `GET /billing`
- `GET /approvals`
- `GET /features`
- `GET /users/profile`

## Public API Routes
- Sites: `/api/sites`
- Organizations: `/api/organizations`
- API Keys: `/api/api-keys`
- Billing: `/billing/*`
- Webhooks: `/webhooks/stripe`
- Optimizations: `/api/v1/optimizations/*`
- Approvals: `/api/v1/approvals/*`
- Audit Logs: `/api/v1/audit-logs`

## Ownership Matrix
| Route Group | Source File |
|---|---|
| `/api/sites` | `app/routers/sites.py` |
| `/api/dashboard` | `app/routers/dashboard.py` |
| `/api/bridge` | `app/routers/bridge.py` |
| `/billing` | `app/routers/billing.py` |
| `/api/organizations` | `app/routers/organizations.py` |
| `/api/api-keys` | `app/routers/api_keys.py` |
| `/webhooks` | `app/routers/webhooks.py` |
| `/api/v1/optimizations` | `app/routers/optimizations.py` |
| `/api/v1/approvals` | `app/routers/approvals.py` |
| `/api/v1/audit-logs` | `app/routers/audit_logs.py` |

## Validation Checklist
- `GET /billing/plans` returns `200`.
- `GET /billing/billing/plans` returns `404`.
- `POST /webhooks/stripe` is reachable.
- `POST /webhooks/webhooks/stripe` returns `404`.
- `GET /api/api-keys?org_id=<id>` returns `401` when unauthenticated.

## Change Procedure
1. Update this contract first when introducing route changes.
2. Update `README.md` endpoint sections.
3. Add/adjust route smoke tests before merge.
