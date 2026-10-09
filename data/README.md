# Data

`olist_dataset.zip` holds the 9 files of the public **Brazilian E-Commerce Public Dataset by Olist**
(Kaggle, CC BY-NC-SA 4.0): https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

`python -m scripts.build_database` unpacks it into `data/raw/` automatically when the CSV files are not there.

One change to keep the repository small: the geolocation file (1,000,163 GPS points, 61 MB) is stored as
one median point per zip prefix (19,010 rows), after removing points outside Brazil. That is exactly what
the build script computes from the full file, so every result is identical. If you put the full Kaggle
files in `data/raw/`, they are used instead.

Generated here and not stored in git: `olist.db` (the SQLite database) and `models/` (trained models).
