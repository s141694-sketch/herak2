# syntax=docker/dockerfile:1
FROM node:24-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
# The JavaScript workspace installs from the root so yjs exists exactly once (decision D28).
COPY package.json package-lock.json ./
COPY shared/package.json shared/package.json
COPY collab/package.json collab/package.json
COPY frontend/package.json frontend/package.json
RUN npm ci --no-audit --no-fund --workspace collab --workspace shared
COPY shared/ shared/
COPY collab/ collab/
WORKDIR /app/collab
EXPOSE 1234
CMD ["npx", "tsx", "src/main.ts"]
