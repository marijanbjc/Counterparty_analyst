FROM node:24-alpine AS ui-build

WORKDIR /build
COPY src/ui/package*.json ./
RUN npm ci
COPY src/ui/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY config/ config/
COPY src/ src/
COPY scripts/ scripts/
COPY docs/internal_files/contractors_audit.snapshot.json docs/internal_files/contractors_audit.snapshot.json
COPY --from=ui-build /build/dist/ src/ui/dist/

CMD ["python", "app.py", "serve"]
