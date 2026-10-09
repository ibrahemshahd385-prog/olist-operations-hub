"""Build data/olist.db from the original Olist CSV files.

Run once from the backend folder:
    python -m scripts.build_database

What it does, step by step:
  1. Creates an empty database from app/schema.sql
  2. Loads each CSV, applies small, documented cleaning steps
  3. Pre-computes reference tables used for suggestions
  4. Prints a short report so you can check the row counts
"""
import hashlib
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import snapshot  # noqa: E402
from app.config import DB_PATH, RAW_DATA_DIR  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "app" / "schema.sql"
DATA_ZIP = RAW_DATA_DIR.parent / "olist_dataset.zip"   # compact copy of the dataset shipped with the repo
MIGRATIONS_FILE = Path(__file__).resolve().parent.parent / "app" / "migrations.sql"

FILES = {
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def unpack_dataset_if_needed() -> None:
    """If the CSV files are not in data/raw yet, take them from data/olist_dataset.zip."""
    missing = [f for f in FILES.values() if not (RAW_DATA_DIR / f).exists()]
    if missing and DATA_ZIP.exists():
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(DATA_ZIP) as z:
            for f in missing:
                z.extract(f, RAW_DATA_DIR)
        print(f"Unpacked {len(missing)} file(s) from {DATA_ZIP.name}")


def read(name: str, **kwargs) -> pd.DataFrame:
    path = RAW_DATA_DIR / FILES[name]
    if not path.exists():
        sys.exit(f"Missing file: {path}\nPut the 9 Olist CSV files in {RAW_DATA_DIR}")
    # utf-8-sig removes the invisible BOM character at the start of the translation file
    return pd.read_csv(path, encoding="utf-8-sig", **kwargs)


def zip5(series: pd.Series) -> pd.Series:
    """Zip prefixes must stay text: '01037' would become 1037 as a number."""
    return series.astype(str).str.zfill(5)


def simulated_cnpj(seller_id: str) -> str:
    """The dataset hides sellers' identities. The NF-e needs a 14-digit issuer id,
    so we derive a stable fake one from the seller_id (same seller -> same number)."""
    digest = int(hashlib.sha256(seller_id.encode()).hexdigest(), 16)
    return str(digest % 10**14).zfill(14)


def build(db_path: Path = DB_PATH) -> None:
    start = time.time()
    unpack_dataset_if_needed()
    snapshot.clear()   # saved numbers from an older database must not survive a rebuild
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    conn.executescript(MIGRATIONS_FILE.read_text(encoding="utf-8"))

    def insert(table: str, df: pd.DataFrame) -> None:
        df.to_sql(table, conn, if_exists="append", index=False, chunksize=20_000)
        print(f"  {table:<22} {len(df):>9,} rows")

    print("Loading tables...")

    # --- category translation
    cat = read("category_translation")
    insert("category_translation", cat)

    # --- customers
    customers = read("customers", dtype={"customer_zip_code_prefix": str})
    customers["customer_zip_code_prefix"] = zip5(customers["customer_zip_code_prefix"])
    insert("customers", customers)

    # --- sellers
    sellers = read("sellers", dtype={"seller_zip_code_prefix": str})
    sellers["seller_zip_code_prefix"] = zip5(sellers["seller_zip_code_prefix"])
    sellers["cnpj_simulated"] = sellers["seller_id"].map(simulated_cnpj)
    insert("sellers", sellers)

    # --- products: fix column typos and attach the English category name
    products = read("products").rename(columns={
        "product_name_lenght": "product_name_length",
        "product_description_lenght": "product_description_length",
    })
    products = products.merge(cat, on="product_category_name", how="left")
    insert("products", products)

    # --- orders
    orders = read("orders")
    orders["source"] = "historical"
    insert("orders", orders)

    # --- order items, payments, reviews (loaded as they are)
    insert("order_items", read("order_items"))
    insert("order_payments", read("order_payments"))
    insert("order_reviews", read("order_reviews"))

    # --- geolocation: ~1M raw points -> one median point per zip prefix,
    #     dropping points outside Brazil's bounding box (bad GPS records)
    geo = read("geolocation", dtype={"geolocation_zip_code_prefix": str})
    geo["geolocation_zip_code_prefix"] = zip5(geo["geolocation_zip_code_prefix"])
    inside = geo["geolocation_lat"].between(-34, 5.5) & geo["geolocation_lng"].between(-74, -34)
    dropped = int((~inside).sum())
    geo = geo[inside]
    geo_ref = geo.groupby("geolocation_zip_code_prefix").agg(
        lat=("geolocation_lat", "median"),
        lng=("geolocation_lng", "median"),
        city=("geolocation_city", lambda s: s.mode().iat[0]),
        state=("geolocation_state", lambda s: s.mode().iat[0]),
    ).reset_index().rename(columns={"geolocation_zip_code_prefix": "zip_code_prefix"})
    insert("geolocation", geo_ref)
    print(f"    (dropped {dropped:,} points outside Brazil)")

    # --- reference: promised vs actual delivery days per customer state
    o = orders[orders["order_status"] == "delivered"].merge(
        customers[["customer_id", "customer_state"]], on="customer_id")
    purchase = pd.to_datetime(o["order_purchase_timestamp"])
    o["promised"] = (pd.to_datetime(o["order_estimated_delivery_date"]) - purchase).dt.total_seconds() / 86400
    o["actual"] = (pd.to_datetime(o["order_delivered_customer_date"]) - purchase).dt.total_seconds() / 86400
    ref = o.groupby("customer_state").agg(
        median_promised_days=("promised", "median"),
        median_actual_days=("actual", "median"),
        orders=("order_id", "count"),
    ).round(1).reset_index()
    insert("ref_state_delivery", ref)

    conn.commit()
    conn.execute("ANALYZE")   # lets SQLite pick the best index for each query
    conn.close()
    size_mb = db_path.stat().st_size / 1e6
    print(f"\nDone: {db_path} ({size_mb:.0f} MB) in {time.time() - start:.0f}s")


if __name__ == "__main__":
    build()
