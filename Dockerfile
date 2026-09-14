FROM node:24-bookworm-slim AS frontend

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig*.json ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV RADAR_DATA_DIR=/data

RUN mkdir -p /data

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
RUN python -m playwright install chromium

COPY backend ./backend
COPY pricebot ./pricebot
COPY --from=frontend /app/dist ./dist

CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
