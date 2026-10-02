# syntax=docker/dockerfile:1
FROM node:24-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY collab/package.json collab/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm install --no-save tsx@4.23.15
COPY collab/ ./
EXPOSE 1234
CMD ["npx", "tsx", "src/main.ts"]
