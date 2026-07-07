# =============================================================================
# Olympus Engine v9 — Frontend Dockerfile (multi-stage, dev + prod)
# =============================================================================
# Stage 1: install deps + build.
# Stage 2: nginx to serve static files (WASM MIME type required).
# =============================================================================

# ---- Build stage ----
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund --prefer-offline

COPY tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src

RUN npm run build

# ---- Runtime stage ----
FROM nginx:1.27-alpine

# WASM MIME + security headers + SPA fallback.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/olympus.conf

# Static assets.
COPY --from=builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

# Healthcheck against the nginx default port.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
