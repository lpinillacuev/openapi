# Changelog

All notable changes to the MercadoPago OpenAPI Specification are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/):
- **MAJOR** — breaking change (removed field, changed type, removed endpoint, changed auth)
- **MINOR** — additive change (new endpoint, new optional field, new enum value)
- **PATCH** — non-breaking fix (corrected description, fixed example, added missing response code)

Breaking changes are detected automatically via `oasdiff` on every PR.

---

## [1.0.0] — 2026-05-21

### Added — Initial public release

**Authentication**
- `POST /oauth/token` — OAuth 2.0 token creation (authorization_code, refresh_token, client_credentials)

**Pagos Online — Checkout Pro**
- `POST /checkout/preferences` — Create preference
- `GET /checkout/preferences/search` — Search preferences
- `GET /checkout/preferences/{id}` — Get preference
- `PUT /checkout/preferences/{id}` — Update preference
- `GET /merchant_orders`, `GET /merchant_orders/{id}`, `PUT /merchant_orders/{id}` — Merchant Orders
- `PUT /v1/payments/{id}/cancellations` — Cancel payment
- `POST /v1/payments/{id}/refunds`, `GET /v1/payments/{id}/refunds`, `GET .../refunds/{id}` — Refunds
- `GET /v1/chargebacks/{id}`, `PUT /v1/chargebacks/{id}` — Chargebacks

**Pagos Online — Checkout API (Orders)**
- `POST /v1/orders` — Create order (Pix, Boleto, OXXO, SPEI, PSE, card)
- `GET /v1/orders`, `GET /v1/orders/{id}` — Search and retrieve orders
- `POST /v1/orders/{id}/capture`, `POST /v1/orders/{id}/process` — Order lifecycle
- `POST /v1/orders/{id}/transactions`, `PUT .../transactions/{id}`, `DELETE .../transactions/{id}` — Transaction management
- `POST /v1/orders/{id}/cancel`, `POST /v1/orders/{id}/refund` — Cancel and refund
- Customers full CRUD + DELETE + search
- Customer Addresses full CRUD (5 endpoints)
- Cards full CRUD + tokenization
- `GET /v1/payment_methods`, `GET /v1/payment_methods/installments`
- `GET /v1/identification_types`

**Pagos Online — API Payments (Legacy)**
- `POST /v1/payments` — Create payment (marked `x-mp-release-phase: legacy`)
- `GET /v1/payments/{id}`, `PUT /v1/payments/{id}`, `GET /v1/payments/search`

**Suscripciones**
- Subscriptions full CRUD + search + export (`/preapproval`)
- Subscription Plans full CRUD + search (`/preapproval_plan`)
- Authorized Payments (invoices): GET + search

**Pagos Presenciales — Point**
- Stores full CRUD + search
- POS full CRUD + search
- Terminals: list, update operation mode, create/get/cancel print actions
- Point Orders: create, get, cancel, refund, simulate (sandbox)
- Deprecated: device listing + payment intent endpoints (marked `deprecated: true`)

**Pagos Presenciales — QR Code**
- Stores full CRUD + search
- POS full CRUD + search
- QR Orders: create, get, delete, refund
- QR Integrator config: get, update
- Cashout QR confirmation
- Deprecated: V1 in-store orders, V2 in-store orders, Dynamic QR (marked `deprecated: true`)

**Post-Venta — Claims**
- `GET /post-purchase/v1/claims/{id}` — Get claim
- `GET /post-purchase/v1/claims/search` — Search claims
- `GET .../reasons/{id}` — Get claim reason
- `GET .../status_history`, `GET .../evidences` — History and evidence
- `GET .../messages`, `POST .../actions/send-message` — Messaging
- `POST .../attachments`, `GET .../attachments/{file}`, `GET .../attachments/{file}/download` — Files
- `POST .../actions/open-dispute`, `GET .../expected-resolutions` — Mediation
- `POST .../actions/evidences` — Shipping evidence

**Post-Venta — Reports**
- Releases Report: config (POST/PUT/GET), create, search, task status, schedule enable/disable, list, download
- Settlements Report: config (POST/PUT/GET), create, search, task status, schedule enable/disable, list, download

**Payouts**
- Argentina & Mexico: batch payouts, list/cancel transactions
- Brazil Pix: `POST /v1/transaction-intents/process`, `GET /v1/transaction-intents/{id}`
- Chile, Mexico SPEI: `POST /v1/transaction-intents/process`

**Wallet Connect**
- Agreement create, get, delete + payer token creation

### Spec architecture
- Fully self-contained `spec3.yaml` — zero external `$ref` file references
- `spec3.json` — machine-generated JSON twin
- `spec3.sdk.yaml` — SDK variant with `x-mp-sdk-coverage` per operation (source: 7 official SDKs)
- `spec3.sdk.json` — machine-generated JSON twin
- `fixtures3.yaml` — 12 sample response objects
- `schemas/` — 10 human-editable source fragments
- `overlays/` — 7 country overlays (MLA, MLB, MLM, MLC, MCO, MPE, MLU)
- `by-site/` — 7 pre-merged per-site specs

### Stats
- **132 operations** across all products and countries
- **31 tags** aligned to the official developer portal navigation
- **65 schemas** in `components/schemas`
- **7 countries** covered via `x-mp-sites` annotations on every tag and endpoint (MLA, MLB, MLM, MLC, MCO, MPE, MLU)
- **7 deprecated endpoints** marked with `x-mp-migration-guide`
- **SDK coverage**: 38 ops supported by all 7 SDKs, 21 partial, 73 spec-only

---

*Auto-changelog generation via `oasdiff changelog` will populate future entries.*
