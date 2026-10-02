# syntax=docker/dockerfile:1
FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY shared/package.json shared/package.json
COPY collab/package.json collab/package.json
COPY frontend/package.json frontend/package.json
RUN npm ci --no-audit --no-fund --workspace frontend --workspace shared
COPY shared/ shared/
COPY frontend/ frontend/
RUN npm run build -w frontend

FROM nginx:1.29-alpine
COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
