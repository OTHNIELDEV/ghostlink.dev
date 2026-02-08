# GhostLink - AI SEO Optimization Platform

GhostLink is a production-ready SaaS platform that helps websites optimize for AI agents and search engines. It generates AI-friendly structured data (JSON-LD), llms.txt files, and provides analytics on AI bot traffic.

## Features

### Core Features
- **AI Site Analysis**: Automated crawling and AI-powered analysis of websites
- **JSON-LD Generation**: Automatic structured data generation for better search visibility
- **llms.txt Creation**: AI-friendly site summaries for LLM consumption
- **Bot Analytics**: Track AI agent visits (GPTBot, ClaudeBot, etc.)
- **SEO Optimization**: Comprehensive SEO analysis and recommendations

### SaaS Features
- **Multi-tenant Organizations**: Team collaboration with role-based access
- **Subscription Management**: Tiered plans (Free, Starter, Pro, Business, Enterprise)
- **Global Payments**: Stripe integration with international tax support
- **API Access**: Programmatic access with API keys and rate limiting
- **Usage Tracking**: Monitor quotas and limits per organization
- **Webhook Support**: Real-time event notifications

## Tech Stack

- **Backend**: FastAPI, SQLModel, Async SQLAlchemy
- **Database**: PostgreSQL (Production), SQLite (Development)
- **Cache**: Redis
- **AI**: OpenAI GPT-4o-mini
- **Payments**: Stripe (Checkout, Billing Portal, Webhooks)
- **Frontend**: Jinja2 Templates, Tailwind CSS, HTMX, Alpine.js
- **Deployment**: Docker, Docker Compose, Nginx

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 16+ (or SQLite for dev)
- Redis 7+
- Stripe Account
- OpenAI API Key

### Environment Setup

1. Clone the repository:
```bash
git clone <repo-url>
cd ghostlink
```

2. Copy environment file:
```bash
cp .env.example .env
```

3. Configure your environment variables in `.env`:
```bash
# Required
SECRET_KEY=your-super-secret-key
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/ghostlink
OPENAI_API_KEY=sk-your-openai-key

# Stripe (Required for payments)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# OAuth (Optional)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

### Development Setup

1. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
uvicorn app.main:app --reload
```

The app will be available at `http://localhost:8000`

4. Run minimal smoke checks (routes/billing/security):
```bash
python3 scripts/smoke_billing_security.py
```

5. Run automated core flow tests (phase 1 + approvals + audit logs + auto-optimize + innovation):
```bash
python3 -m pytest -q tests/test_phase1_core_flows.py tests/test_auto_optimize_loop.py tests/test_role_policy_approvals.py tests/test_approval_inbox_and_audit_logs.py tests/test_innovation_phase3.py tests/test_remaining_innovations.py tests/test_core_engine.py
```

### Production Deployment

#### Using Docker Compose

1. Configure production environment variables in `.env`

2. Start services:
```bash
docker-compose up -d
```

3. Access the application at `http://localhost`

#### Manual Deployment

1. Set up PostgreSQL and Redis
2. Configure environment variables
3. Install dependencies: `pip install -r requirements.txt`
4. Run migrations (if using Alembic)
5. Start with Gunicorn:
```bash
gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## Stripe Configuration

### Setting Up Stripe

1. Create a Stripe account at https://stripe.com
2. Get your API keys from the Stripe Dashboard
3. Create products and prices for each plan:
   - Free Plan (no price needed)
   - Starter: $19/month or $199/year
   - Pro: $49/month or $499/year
   - Business: $99/month or $999/year
   - Enterprise (custom pricing)

4. Configure webhook endpoint:
   - URL: `https://your-domain.com/webhooks/stripe`
   - Events to listen for:
     - `checkout.session.completed`
     - `customer.subscription.created`
     - `customer.subscription.updated`
     - `customer.subscription.deleted`
     - `invoice.payment_succeeded`
     - `invoice.payment_failed`

5. Enable Stripe Tax (optional but recommended):
   - Go to Tax settings in Stripe Dashboard
   - Configure tax rates for your regions

### Price IDs

Update your `.env` file with the Stripe Price IDs:
```bash
# Recommended: separate month/year price IDs
STRIPE_PRICE_STARTER_MONTH=price_...
STRIPE_PRICE_STARTER_YEAR=price_...
STRIPE_PRICE_PRO_MONTH=price_...
STRIPE_PRICE_PRO_YEAR=price_...
STRIPE_PRICE_BUSINESS_MONTH=price_...
STRIPE_PRICE_BUSINESS_YEAR=price_...
STRIPE_PRICE_ENTERPRISE_MONTH=price_...
STRIPE_PRICE_ENTERPRISE_YEAR=price_...

# Backward compatibility (single key per plan)
# STRIPE_PRICE_STARTER=price_...
# STRIPE_PRICE_PRO=price_...
# STRIPE_PRICE_BUSINESS=price_...
# STRIPE_PRICE_ENTERPRISE=price_...
```

## API Documentation

### Authentication

API requests require an API key in the Authorization header:
```bash
Authorization: Bearer gl_your_api_key
```

### Endpoints

#### Sites
- `POST /api/sites` - Add a new site
- `DELETE /api/sites/{id}` - Delete a site
- `POST /api/sites/{id}/generate` - Regenerate AI assets

#### Organizations
- `GET /api/organizations` - List user's organizations
- `POST /api/organizations` - Create organization
- `GET /api/organizations/{id}` - Get organization details
- `GET /api/organizations/{id}/members` - List members
- `POST /api/organizations/{id}/members` - Invite member

#### Billing
- `GET /billing/plans` - List available plans
- `GET /billing/current` - Get current subscription
- `POST /billing/checkout` - Start checkout session
- `POST /billing/portal` - Open billing portal
- `POST /billing/cancel` - Cancel subscription

#### API Keys
- `GET /api/api-keys` - List API keys
- `POST /api/api-keys` - Create new API key
- `DELETE /api/api-keys/{id}` - Revoke API key

#### Auto-Optimize Loop (v1)
- `POST /api/v1/optimizations/sites/{site_id}/actions/generate` - Generate actionable optimization tasks
- `GET /api/v1/optimizations/sites/{site_id}/actions` - List actions for a site
- `POST /api/v1/optimizations/actions/{action_id}/approve` - Approve, apply instruction, and trigger re-scan
- `POST /api/v1/optimizations/actions/{action_id}/reject` - Reject action

#### Auto-Optimize Loop v2 (Bandit)
- `POST /api/v1/optimizations/sites/{site_id}/actions/decide-v2` - Select next action with bandit strategy (`thompson`/`ucb`)
- `GET /api/v1/optimizations/sites/{site_id}/bandit/arms` - List bandit arm stats
- `POST /api/v1/optimizations/actions/{action_id}/feedback` - Record reward feedback (0.0-1.0)

#### Approval Flow (v1)
- `GET /api/v1/approvals` - List approval requests by org (`org_id` required)
- `POST /api/v1/approvals` - Create approval request
- `POST /api/v1/approvals/{request_id}/approve` - Owner/Admin approves and executes request
- `POST /api/v1/approvals/{request_id}/reject` - Owner/Admin rejects request
- `GET /approvals` - Web approval inbox page for reviewing requests

#### Audit Logs (v1)
- `GET /api/v1/audit-logs` - List org audit events (`org_id` required, owner/admin only)

#### Answer Capture Lab (v1)
- `GET /api/v1/answer-capture/query-sets` - List question sets
- `POST /api/v1/answer-capture/query-sets` - Create question set (owner/admin)
- `GET /api/v1/answer-capture/query-sets/{query_set_id}/queries` - List question items
- `POST /api/v1/answer-capture/query-sets/{query_set_id}/queries` - Create question item (owner/admin)
- `POST /api/v1/answer-capture/runs` - Create run and ingest response results
- `GET /api/v1/answer-capture/runs` - List runs
- `GET /api/v1/answer-capture/runs/{run_id}` - Get run with results

#### AI Attribution (v1)
- `POST /api/v1/attribution/events` - Record attribution event
- `GET /api/v1/attribution/snapshot` - Compute current attribution snapshot
- `POST /api/v1/attribution/snapshot` - Persist snapshot (owner/admin)
- `GET /api/v1/attribution/snapshots` - List saved snapshots

#### Onboarding OS (v1)
- `GET /api/v1/onboarding/status` - Get org activation progress
- `POST /api/v1/onboarding/complete-step` - Mark a step completed

#### Proof Center (v1)
- `GET /api/v1/proof/overview` - Compute measured proof KPIs (ACR/Citation/AI Assist)
- `GET /api/v1/proof/before-after` - Compare baseline vs latest answer results
- `POST /api/v1/proof/snapshots` - Persist proof snapshot (owner/admin)
- `GET /api/v1/proof/snapshots` - List saved proof snapshots

#### Knowledge Graph + Schema Copilot (v1)
- `GET /api/v1/knowledge-graph/entities` - List entities
- `POST /api/v1/knowledge-graph/entities` - Create entity (owner/admin)
- `GET /api/v1/knowledge-graph/relations` - List relations
- `POST /api/v1/knowledge-graph/relations` - Create relation (owner/admin)
- `POST /api/v1/knowledge-graph/sites/{site_id}/schema-drafts` - Generate schema draft for site (owner/admin)
- `GET /api/v1/knowledge-graph/sites/{site_id}/schema-drafts` - List schema drafts
- `POST /api/v1/knowledge-graph/schema-drafts/{draft_id}/apply` - Apply draft to site (owner/admin)

#### Compliance Gate (v1)
- `GET /api/v1/compliance/policies` - List compliance policies
- `POST /api/v1/compliance/policies` - Create policy (owner/admin)
- `POST /api/v1/compliance/sites/{site_id}/check` - Run a policy check for site
- `GET /api/v1/compliance/sites/{site_id}/checks` - List site compliance checks
- `POST /api/v1/compliance/sites/{site_id}/enforce` - Enforce policy (returns 409 on blocking failure)

#### Edge Runtime Delivery (v1)
- `POST /api/v1/edge/sites/{site_id}/artifacts/build` - Build deployable artifact (`bridge_script`/`jsonld`/`llms_txt`)
- `POST /api/v1/edge/sites/{site_id}/deployments` - Deploy artifact to `staging` or `production`
- `GET /api/v1/edge/sites/{site_id}/deployments` - List deployments
- `POST /api/v1/edge/sites/{site_id}/deployments/{deployment_id}/rollback` - Roll back to prior deployment

#### Product Pages
- `GET /dashboard` - Org dashboard with onboarding and visibility scoreboards
- `GET /report/{site_id}` - Site-level AIO report + optimization loop + integration status
- `GET /proof` - Proof Center (ACR/Citation/AI Assist + before/after)
- `GET /docs/integration-guide` - Customer integration guide for bridge script deployment

## Architecture

### Operational Docs
- `docs/ROUTING_CONTRACT.md` - Public route contract and validation checklist
- `docs/RBAC_POLICY_MATRIX.md` - Role policy matrix and endpoint permissions
- `docs/STRIPE_EVENT_STATE_TRANSITIONS.md` - Stripe event/state transition reference
- `docs/PHASE3_TOP2_EXECUTION_PLAN.md` - Priority innovation execution plan and API spec
- `docs/CUSTOMER_SITE_INTEGRATION_GUIDE.md` - Customer site integration decision guide
- `docs/CUSTOMER_CLARITY_AND_AI_EFFICIENCY_INNOVATION_PLAN_2026-02-08.md` - Product innovation roadmap

### Multi-tenant Design

- **Organization-centric**: All billable resources belong to an Organization
- **Membership-based access**: Users join orgs with roles (owner, admin, member)
- **Subscription per org**: Each org has one subscription controlling feature access
- **Usage tracking**: Metrics tracked per org for quota enforcement

### Quota Enforcement

Quota checks happen at the service layer:
```python
allowed, current, limit = await subscription_service.check_quota(
    session, org_id, "site_scans_per_month"
)
if not allowed:
    raise HTTPException(403, "Quota exceeded")
```

### Payment Flow

1. User selects plan and clicks "Upgrade"
2. Backend creates Stripe Checkout Session
3. User completes payment on Stripe
4. Stripe webhook updates local subscription
5. User is redirected back to app with new plan active

## Plan Tiers

| Feature | Free | Starter | Pro | Business | Enterprise |
|---------|------|---------|-----|----------|------------|
| Sites | 1 | 3 | 10 | 50 | Unlimited |
| Monthly Scans | 5 | 50 | 500 | 2000 | Unlimited |
| API Calls | 100 | 1,000 | 10,000 | 100,000 | Unlimited |
| Team Members | 1 | 2 | 5 | 20 | Unlimited |
| Analytics Retention | 30 days | 90 days | 365 days | 730 days | Unlimited |
| API Access | ❌ | ✅ | ✅ | ✅ | ✅ |
| Webhooks | ❌ | 1 | 5 | 20 | Unlimited |
| Priority Support | ❌ | ❌ | ✅ | ✅ | ✅ |
| White-label | ❌ | ❌ | ❌ | ✅ | ✅ |
| Custom Contracts | ❌ | ❌ | ❌ | ❌ | ✅ |

## Monitoring & Observability

### Logging
- Structured JSON logging in production
- Log levels: DEBUG (dev), INFO (staging), WARNING (prod)
- Key events logged: payments, quota violations, errors

### Metrics to Track
- Monthly Recurring Revenue (MRR)
- Customer Acquisition Cost (CAC)
- Churn rate
- API usage per organization
- Site scan success/failure rates

## Security

- API keys use SHA-256 hashing (raw keys shown only once)
- Stripe webhooks verified with signature
- CORS configured for production domains
- SQL injection prevention via SQLModel
- XSS protection via Jinja2 auto-escaping

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

[Your License Here]

## Support

- Documentation: [docs.ghostlink.io](https://docs.ghostlink.io)
- Email: support@ghostlink.io
- Enterprise: enterprise@ghostlink.io
