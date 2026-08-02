FROM node:24-bookworm-slim

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src

EXPOSE 5173

CMD ["./node_modules/.bin/vite", "--host", "0.0.0.0"]
