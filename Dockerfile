# Olist Operations Hub: the whole system in one container
# (React screens + FastAPI API + SQLite database + trained models).
#
# The live demo runs on Render's free plan, which builds this file straight from GitHub:
# every push to main redeploys it. To try it locally with Docker:
#   docker build -t olist-ops .
#   docker run -p 8000:8000 -e PORT=8000 olist-ops      -> http://localhost:8000

# ---------- 1. build the React app ----------
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. API + database + models ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY data/olist_dataset.zip /app/data/

# Build the database from the dataset, train every model, save the heavy history numbers
# (app/snapshot.py), then delete the raw files: the server only needs data/olist.db,
# data/models and data/cache. Takes about 2 minutes.
RUN python -m scripts.build_database \
 && python -m scripts.train_models \
 && python -m scripts.precompute \
 && rm -rf /app/data/raw /app/data/olist_dataset.zip

COPY --from=frontend /src/frontend/dist /app/frontend/dist

# Render gives the port in $PORT (10000 by default).
ENV PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]
