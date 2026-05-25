# Contributing to MercadoPago OpenAPI

Thank you for helping improve the spec. This guide covers how to report issues,
propose changes, and run validation locally before opening a PR.

---

## How to report a missing or incorrect endpoint

Open a GitHub Issue with the label `spec-bug` or `spec-gap` and include:

- **Endpoint**: HTTP method + path (e.g. `POST /v1/payments`)
- **Problem**: What is wrong or missing (wrong field type, missing parameter, undocumented response code)
- **Evidence**: Link to the official developer portal page or API response that proves the correct behavior
- **Country scope**: Which `site_id` values are affected (if country-specific)

Do not open a PR without an issue first for new endpoints — the team needs to confirm the
endpoint is GA and not an internal-only path.

---

## Editing the spec

### Key rules

1. **`spec3.yaml` must always be self-contained** — zero external `$ref` file references.
   All schemas live in `components/schemas` inside `spec3.yaml` itself.

2. **Edit schemas in `schemas/*.yaml`**, then run `bundle.py` to merge them into `spec3.yaml`.
   Never edit `spec3.yaml`'s `components/schemas` block directly for schema definitions —
   edit the source fragment and re-bundle.

3. **Never edit `spec3.json`** — it is machine-generated from `spec3.yaml`.

4. **No real credentials** in any example or fixture. Use `YOUR_ACCESS_TOKEN` as placeholder.

5. **No raw card data** (PAN, CVV) in any example.

### Adding a new endpoint

1. Find the source file in `fury_devsite-docs/reference/api-json/` for the description and schema
2. Add the path operation to the correct section of `spec3.yaml` under `paths:`
3. Add required schemas to the matching `schemas/*.yaml` fragment
4. Run `python3 openapi/scripts/bundle.py` to merge and fix refs
5. Add a sample response to `fixtures3.yaml` keyed by the resource name
6. Run `bash openapi/scripts/validate.sh`

### Adding a new schema

Edit the appropriate `schemas/*.yaml` file:

| File | Contains |
|---|---|
| `schemas/common.yaml` | Error, Address, Payer, Pagination, Store, POS, Money |
| `schemas/payments.yaml` | Payment, PaymentRequest, Refund |
| `schemas/orders.yaml` | Order, OrderRequest, OrderPayment |
| `schemas/checkout.yaml` | Preference, PreferenceItem |
| `schemas/customers.yaml` | Customer, Card, CardToken |
| `schemas/subscriptions.yaml` | Subscription, SubscriptionPlan, AuthorizedPayment |
| `schemas/webhooks.yaml` | WebhookNotification, MerchantOrder |
| `schemas/oauth.yaml` | OAuthTokenRequest, OAuthTokenResponse |
| `schemas/claims.yaml` | Claim, ClaimMessage, ClaimEvidence |
| `schemas/reports.yaml` | ReportConfig, ReportRequest, ReportTask |

After editing, run the bundler: `python3 openapi/scripts/bundle.py`

---

## Running validation locally

```bash
# 1. Install dependencies (once)
pip install pyyaml openapi-spec-validator
npm install -g @stoplight/spectral-cli

# 2. Bundle (merge schemas into spec3.yaml)
python3 openapi/scripts/bundle.py

# 3. Validate
bash openapi/scripts/validate.sh

# 4. Check for breaking changes vs main
bash openapi/scripts/diff.sh main
```

All three must pass before opening a PR.

---

## PR checklist

- [ ] Issue linked
- [ ] `spec3.yaml` has zero external `$ref`s (`grep -c '$ref: "schemas/' openapi/spec3.yaml` → 0)
- [ ] New endpoint has `x-mp-sites`, `x-mp-release-phase`, `security`, and all standard response codes
- [ ] New schema added to the correct `schemas/*.yaml` fragment and bundled
- [ ] `fixtures3.yaml` updated if a new resource was added
- [ ] `bash openapi/scripts/validate.sh` passes
- [ ] No real credentials or raw card data in any example

---

## SLA for spec updates

| Event | Target |
|---|---|
| New GA endpoint | Spec updated within 5 business days of API release |
| Breaking API change | Spec updated same day; deprecation notice 30 days prior |
| Bug in spec (wrong field/type) | Fix within 2 business days |
| Community-reported issue | First response within 3 business days |

---

MercadoPago Developer Experience
