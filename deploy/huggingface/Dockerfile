# Olist Operations Hub - live demo on Hugging Face Spaces (free CPU Space).
#
# The Space itself only holds this Dockerfile and README.md. Everything else
# (code + data/olist_dataset.zip) is cloned from the GitHub repository below,
# so updating the demo = pushing to GitHub, then Settings -> "Factory rebuild" in the Space
# (a factory rebuild ignores Docker's cache, so it always takes the latest code).
#
# Code is cloned from github.com/ibrahemshahd385-prog/olist-operations-hub (must be public).

# ---------- 1. build the React app ----------
FROM node:20-slim AS frontend
ARG REPO=https://github.com/ibrahemshahd385-prog/olist-operations-hub.git
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 ${REPO} /src
WORKDIR /src/frontend
RUN npm install && npm run build

# ---------- 2. API + database + models ----------
FROM python:3.12-slim
ARG REPO=https://github.com/ibrahemshahd385-prog/olist-operations-hub.git
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Spaces run the container as user 1000: build everything as that user so the
# database stays writable (visitors can register orders; the demo resets on restart).
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" PYTHONUNBUFFERED=1
RUN git clone --depth 1 ${REPO} /home/user/app
WORKDIR /home/user/app/backend
RUN pip install --no-cache-dir --user -r requirements.txt
# builds data/olist.db from data/olist_dataset.zip, then trains every model (about 1 minute)
RUN python -m scripts.build_database && python -m scripts.train_models
COPY --from=frontend --chown=user /src/frontend/dist /home/user/app/frontend/dist

EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
