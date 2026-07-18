# ---- frontend build ----
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-fund --no-audit
COPY frontend/ ./
# vite.config outDir points at ../backend/static; keep it inside /build
RUN npm run build -- --outDir /build/static

# ---- backend runtime ----
FROM python:3.12-slim
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/nextpanel ./nextpanel
RUN pip install --no-cache-dir .

COPY --from=frontend /build/static ./static

ENV NEXTPANEL_DATA_DIR=/config \
    NEXTPANEL_HOST=0.0.0.0 \
    NEXTPANEL_PORT=6995

VOLUME ["/config"]
EXPOSE 6995

CMD ["uvicorn", "nextpanel.main:app", "--host", "0.0.0.0", "--port", "6995"]
