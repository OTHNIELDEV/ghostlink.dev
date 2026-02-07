# GhostLink RBAC Policy Matrix (2026-02-07)

## Organization Roles
- `owner`: full control over org billing, approvals, members, API keys, optimization approval actions.
- `admin`: operational control similar to owner for day-to-day management.
- `member`: read/manage own workload, but sensitive changes require approval.

## Policy Summary
| Capability | Owner | Admin | Member | Enforcement |
|---|---|---|---|---|
| View org-scoped resources | Allow | Allow | Allow | Org membership check |
| Change billing directly | Allow | Allow | Deny | `/billing/*` + role check |
| Request billing change approval | Allow (optional) | Allow (optional) | Allow | Approval request API |
| Approve/Reject approval requests | Allow | Allow | Deny | `/api/v1/approvals/{id}/approve|reject` |
| Create/Revoke API keys | Allow | Allow | Deny | `/api/api-keys` |
| View audit logs | Allow | Allow | Deny | `/api/v1/audit-logs` |
| Generate optimization actions | Allow | Allow | Allow | Org membership check |
| Apply/Reject optimization actions | Allow | Allow | Allow | Org membership check |

## Endpoint Mapping
- `GET /api/v1/approvals`: any org member can list requests.
- `POST /api/v1/approvals`: any org member can submit requests.
- `POST /api/v1/approvals/{request_id}/approve`: owner/admin only.
- `POST /api/v1/approvals/{request_id}/reject`: owner/admin only.
- `GET /api/v1/audit-logs`: owner/admin only.
- `POST /billing/checkout|cancel|reactivate`: owner/admin direct execution; member requires `request_approval=true`.
- `POST /api/api-keys`, `DELETE /api/api-keys/{id}`: owner/admin only.

## UI Conventions
- Sidebar shows `Approvals` menu with pending request count badge for current org.
- Dashboard shows `Pending Approval Inbox` when pending requests exist.
- Dedicated inbox page: `GET /approvals?org_id=<id>`.

## Notes
- All org-scoped calls must pass `org_id` and are validated against `Membership`.
- Audit events are appended for approval, billing, API key, and optimization actions.
