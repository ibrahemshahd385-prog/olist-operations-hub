"""Central place for paths and business constants.

Everything that a reviewer might want to tweak (file locations, business rules)
lives here so it is never hidden inside the logic.
"""
from pathlib import Path

# backend/app/config.py -> project root is two levels above backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

RAW_DATA_DIR = PROJECT_DIR / "data" / "raw"          # the original Olist CSV files
DB_PATH = PROJECT_DIR / "data" / "olist.db"          # SQLite database built from them
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"     # React production build (optional)
MODELS_DIR = PROJECT_DIR / "data" / "models"         # trained models (Module 2), created by scripts/train_models.py

# ---------------------------------------------------------------------------
# Business rules (each one is backed by the data or by Brazilian practice)
# ---------------------------------------------------------------------------

# Payment methods that exist in the dataset.
PAYMENT_TYPES = ["credit_card", "boleto", "voucher", "debit_card"]

# Payment methods that confirm instantly. In the data, credit-card orders are
# approved in a median of 0.3 hours, while boleto orders take a median of
# 29 hours (the customer has to pay the bank slip first). So boleto orders wait
# in "created" until the payment is confirmed.
INSTANT_PAYMENT_TYPES = {"credit_card", "debit_card", "voucher"}

# Only credit cards can be split into installments ("parcelamento").
# In the data: 1 to 24 installments, and 67% of card payments use more than 1.
MAX_INSTALLMENTS = 24

# Tolerance when checking that payments add up to the order total.
# 99.7% of historical orders match items + freight within one cent.
MONEY_TOLERANCE = 0.01

MAX_QUANTITY_PER_LINE = 20

# NF-e (Brazilian electronic invoice) settings used by the simulator.
NFE_MODEL = "55"         # model 55 = NF-e (model 65 is the NFC-e used in physical stores)
NFE_SERIES = 1
NFE_EMISSION_TYPE = "1"  # 1 = normal emission (not contingency)

# IBGE state codes: the first two digits of every NF-e access key.
IBGE_STATE_CODES = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17",
    "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27",
    "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41",
    "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}

BRAZIL_STATES = sorted(IBGE_STATE_CODES)

