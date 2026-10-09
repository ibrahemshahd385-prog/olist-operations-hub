# Olist Operations Hub

An order-to-cash system for Olist sellers, built on the public Olist dataset (99,441 real orders, 2016–2018).
HVIA Data & AI Solutions, training task, Batch 2.

**Status:** all four modules are built: orders & NF-e invoices, smart logistics, seller performance, analytics & AI.

**Live demo:** runs on Render's free plan, built from the `Dockerfile` in this repository. The free server sleeps after 15 minutes without visitors: the first visit wakes it in about a minute. Orders registered on the demo are cleared each time it sleeps.

---

## Why the system starts at the invoice

Olist now gets every new client through its ERP (Tiny, bought in 2021). The ERP is where a seller registers a sale and issues the invoice, and products like the marketplace hub, payments, credit and the AI assistant sit on top of it ([Startups, Oct 2026](https://startups.com.br/negocios/estrategia/no-azul-olist-acelera-expansao-e-mira-mercado-de-maquininhas/)).

In Brazil, the invoice is a legal step. Every shipped sale needs an authorised **NF-e** (Nota Fiscal Eletrônica), and its printed summary, the **DANFE**, has to travel with the package ([Nuvemshop](https://www.nuvemshop.com.br/blog/o-que-e-danfe/)). So a system "from invoice registration onwards" means the whole journey of an order:

```
register sale -> payment -> seller processing -> NF-e -> carrier -> delivery -> review
|------------------------- Module 1: orders & invoices -------------------------|
       Module 2: smart logistics   (promise date, late risk, freight check)
       Module 3: seller performance (health score, key accounts, alerts)
       Module 4: analytics & AI    (management view, review intelligence)
```

Each module answers a finding from Task 1:

| Task 1 finding | Where the system acts on it |
|---|---|
| Late orders drop the review from 4.28 to 2.26 | Module 2 predicts late risk at checkout; Module 4 shows the review collapse day by day |
| 6.77% of orders arrive late | Module 2 risk queue; Module 3 on-time component of the health score |
| Top 10% of sellers = 67.5% of revenue | Module 3 key accounts and their alerts |
| Freight averages 16.6% of the product price; 4,124 items cost more to ship than to buy | Module 1 warning; Module 2 freight model flags overpriced freight |
| Repeat purchase rate is 3.12% | Module 4 headline; review intelligence shows what drives unhappy customers away |

## Module 1: orders & invoices

Every rule below comes from the data or from Brazilian practice. Nothing is decorative.

| Feature | Why (evidence) |
|---|---|
| **Order lifecycle as a state machine:** created → approved → processing → invoiced → shipped → delivered, with canceled / unavailable exits | These are the 8 statuses in the dataset. The order comes from checking which timestamps are filled for each status. |
| **Card payments are approved instantly; boleto waits** in "Awaiting payment" | Median approval time: **0.3 h** for credit card vs **29 h** for boleto. |
| **Installments only on credit card**, 1 to 24 | In the data, only cards have more than 1 installment (max 24), and **67%** of card payments use installments. |
| **Payments must add up to the order total** | **99.7%** of historical orders match items + freight to the cent. |
| **One NF-e per seller** in multi-seller orders | **1,278** orders have items from more than one seller. Each seller is a separate legal issuer. |
| **Cannot ship without an NF-e** | Brazilian rule: the DANFE travels with the goods. |
| **Real NF-e access key:** 44 digits, módulo-11 check digit, sequential numbering per seller | The official layout ([Focus NFe](https://focusnfe.com.br/blog/como-e-formada-a-chave-de-acesso-de-nf-e-nfc-e-ct-e-e-mdf-e/)). The DANFE page shows a scannable Code 128 barcode, as on real invoices. |
| **NF-e can be canceled only within 24 h**; after that, a return invoice is needed | The general NF-e cancellation window. |
| **Warning when freight costs more than the product** | **4,124** items in the dataset had this (found in Task 1). |
| **Promised delivery date** copied from Olist's historical promise per state | Olist promised a median of **23 days** while orders arrived in a median of **10**: **74%** of orders arrived more than a week early. Module 1 copies the old promise on purpose; Module 2 replaces it with a model. |
| **Audit trail:** every status change is logged with time and note | Needed in any operational system; the dataset has no history. |
| **Dataset orders are read-only** | Keeps the analysis truthful. New orders are marked `system`, old ones `historical`. |

### Screens

- **Orders:** work queue for orders registered here (awaiting payment → to process → to invoice → to ship → in transit), then every order with filters.
- **Register order:** customer (returning or new) → items from a seller's real catalogue (pre-filled with that seller's average price and freight) → payment, with a live summary and warnings.
- **Order page:** the lifecycle drawn as a route, the next actions, items, NF-e per seller, payments, review and activity log.
- **DANFE:** a printable invoice in the official layout, marked *SEM VALOR FISCAL* (it is never sent to SEFAZ, the tax authority).

---

## Architecture

```
frontend/  React 19 + Vite        screens, calls /api/...
   │  (Vite forwards /api to :8000 during development)
backend/   FastAPI                routers/   HTTP only: read the request, call a service
                                  services/  all business rules (workflow, invoices, orders)
                                  db.py      sqlite3 connection, plain SQL
data/      olist.db (SQLite)      the 9 original tables + invoices + order_events
```

- **Plain SQL with Python's built-in `sqlite3`**: every query can be read as it is, with nothing extra to install. Moving to PostgreSQL later changes `db.py` and a few SQL details.
- **The original tables and column names are kept**, so every number traces back to the Kaggle files. The only rename fixes the typo `lenght` → `length`.
- **Business errors map to HTTP codes in one place** (`main.py`): not found → 404, broken rule → 409, invalid data → 422 with every problem listed.

### Data cleaning (scripts/build_database.py)

- Zip prefixes are kept as text (`01037`, not `1037`).
- Geolocation: 1,000,163 raw points → one median point per zip prefix (19,010 rows), after dropping 42 points outside Brazil.
- `review_id` is not unique in the source, so reviews use SQLite's row id.
- Sellers are anonymised, so each one gets a stable fake 14-digit id for the NF-e (derived from the seller_id).
- Note: the order items file provided for this task has no `shipping_limit_date` column (the public Kaggle version does). Seller handling time is measured from approval to carrier hand-over instead.

---

## Module 2: smart logistics

Three models, trained only on what is known at checkout, tested on orders they never saw.

**Honest testing.** Train on orders placed before April 2018, tune in April–May, test on June–August 2018 (18,603 orders). Never a random split: that would let the model learn from orders placed after the ones it is tested on.

| Model | What it does | Test result |
|---|---|---|
| **Delivery promise** (gradient boosting on log-days) | Predicts the delivery time, then adds a safety margin tuned so that 95% of orders arrive on time | Promise of **19.1 days instead of Olist's 21.4**, keeping the same share of promises (96.7% vs 96.7%). Average error 3.4 days, against 13.3 for Olist's date |
| **Late risk** (gradient boosting classifier) | Probability that an order misses its promise | ROC AUC **0.77**. The riskiest 10% of orders contain **32%** of the late ones (11.7% late vs 3.6% overall) |
| **Freight check** (gradient boosting) | Expected freight for the weight, volumetric weight, distance and states | Error **R$ 5.55** per item, against R$ 8.15 for the route average |

What makes it work:

- **Anchored on the network's recent speed.** Deliveries got about 25% faster during 2018. The ETA model predicts how much faster or slower an order is than the last 30 days of deliveries, so it follows the network instead of remembering old speeds.
- **Seller track record without peeking.** Each training order only sees the seller's deliveries completed *before* it was placed.
- **Explainable flags.** Each risky order lists plain reasons (long route, seller's past late rate, slow hand-over, boleto, peak month, several sellers).

In the app: the order form shows the promise, risk and expected freight while you type; the order page keeps the prediction; the Logistics page shows the test results, promise vs reality by state, the busiest routes and the open orders ranked by risk.

## Module 3: seller performance

The seller is Olist's real customer, and 10% of sellers bring 67.5% of revenue.

- **Health score 0–100** with four parts anyone can check: on-time delivery (35%), rating (30%), shipping speed (20%), reliability (15%). Delivery weighs most because of the review collapse above. Tiers A (85+), B (70+), C (55+), D. Sellers with fewer than 10 orders are not scored.
- **Key accounts:** the top 309 sellers by revenue.
- **Alerts an account manager acts on:** key account at risk (61), stopped selling (374), revenue down 50%+ in 90 days (82), slow to ship (270), low rating (38).
- **Ready for a credit offer (220 sellers):** healthy, steady sellers with recent sales. A first screen for Olist's credit offer (financial products, credit included, are half of Olist's 2026 growth); not a credit decision.
- **Seller page:** score breakdown, plain next steps, monthly revenue, late rate by destination, top categories, latest orders.

## Module 4: analytics & AI

- **Management view:** revenue by month, on-time rate, review average, repeat rate, top categories and states, payment mix.
- **One late delivery costs the review:** average review by days early or late. Early: about 4.3. From 4 days late: around 1.7–2.1, with most reviews one-star.
- **Review intelligence** on 43,309 written comments in Portuguese:
  - **Topics** by transparent keyword rules: not received, late, wrong item, damaged, missing items, quality, service, invoice, and praise. **38% of negative reviews are about an order that did not arrive or arrived late.**
  - **Sentiment model** (TF-IDF + logistic regression) learned from the stars; tested on 12,084 reviews written from May 2018: **ROC AUC 0.98, 94.8% accuracy**.
  - **Hidden complaints:** 353 reviews with 4–5 stars whose text reads like a complaint (for example, five stars and "não recebi o produto"). Star averages never show them.
  - **Try it:** paste any review and see topics, sentiment and the words that weighed most.

---

## Run it

You need **Python 3.10+** and **Node 18+**. The dataset is included (`data/olist_dataset.zip`) and unpacked automatically.

**1. Backend** (first terminal)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m scripts.build_database   # builds data/olist.db, about 15 seconds
python -m scripts.train_models     # trains every model, about 30 seconds
uvicorn app.main:app --reload
```

Already ran Module 1 before? Keep your database: just run `pip install -r requirements.txt`, then `python -m scripts.train_models`, then start the API. New tables are added automatically on start-up, and your orders stay.

API docs: http://localhost:8000/docs

**2. Frontend** (second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

**One-server option:** run `npm run build` in `frontend/`, then only the backend. FastAPI serves the built app at http://localhost:8000.

**Tests:** `cd backend` then `python -m pytest` (33 tests: access-key rules, the full order flow, leakage checks and model quality, seller scores, analytics numbers that must match Task 1, Portuguese topic rules). They run on an in-memory copy of the real data.

To start over with a clean database, run `python -m scripts.build_database` again.

**Docker (the live demo):** `docker build -t olist-ops .` then `docker run -p 8000:8000 -e PORT=8000 olist-ops`, and open http://localhost:8000. The build creates the database, trains the models and runs `python -m scripts.precompute`, which saves the heavy history numbers (analytics, seller scores, busiest routes) so the small free server answers at once instead of computing them on the first visit.

---

## API

| Method | Path | What it does |
|---|---|---|
| GET | `/api/orders` | List with filters: `status`, `state`, `source`, `seller_id`, `q`, `date_from`, `date_to`, `page` |
| GET | `/api/orders/summary` | Totals, status counts, work queue |
| POST | `/api/orders` | Register an order (customer, items, payments) |
| GET | `/api/orders/{id}` | Full order: items, payments, invoices, timeline, allowed actions |
| POST | `/api/orders/{id}/actions/{action}` | `approve_payment`, `start_processing`, `ship`, `deliver`, `cancel`, `mark_unavailable` |
| POST | `/api/orders/{id}/invoices` | Issue an NF-e for one seller of the order |
| GET | `/api/invoices/{id}` | Everything the DANFE needs |
| GET | `/api/customers/search`, `/api/sellers/search`, `/api/sellers/{id}/products` | Look-ups for the order form |
| GET | `/api/delivery-reference/{state}` | Promised vs actual delivery days for a state |
| GET | `/api/logistics/overview` | Model test results and busiest routes |
| POST | `/api/logistics/quote` | Promise, late risk and freight estimate for an order being typed |
| GET | `/api/logistics/at-risk` | Open orders, riskiest first |
| GET | `/api/sellers`, `/api/sellers/summary`, `/api/sellers/{id}` | Seller list with filters, tiers and alerts, one seller's scorecard |
| GET | `/api/analytics/overview` | Management numbers and charts |
| GET | `/api/analytics/reviews` | Complaint topics, hidden complaints, model results |
| POST | `/api/analytics/reviews/analyze` | Analyze one review text |

## Project structure

```
backend/
  app/
    main.py            app, error handling, routers
    config.py          paths and business constants
    db.py              sqlite3 connection, upgrades an existing database
    snapshot.py        saved history numbers for the live demo (optional)
    schema.sql         the original tables, invoices and order events
    migrations.sql     tables added by modules 2-4 (safe to run again)
    schemas.py         request validation (Pydantic)
    errors.py          business error types
    routers/           orders, catalog, logistics, sellers, analytics
    services/          workflow, invoices, orders, catalog, logistics, sellers, analytics
    ml/                features.py (shared by training and live use), predictor.py, reviews.py
  scripts/build_database.py, scripts/train_models.py, scripts/precompute.py
  tests/
Dockerfile             one container for the live demo (Render)
frontend/
  src/
    pages/             Orders, NewOrder, OrderDetail, Invoice, Logistics, Sellers, SellerDetail, Analytics
    components/        Layout, LifecycleRoute, Barcode128, charts (hand-made SVG), ui
    lib/               api, router, format, useAsync, flash
docs/
  module-1-explained-ar.md
  modules-2-4-explained-ar.md
```
