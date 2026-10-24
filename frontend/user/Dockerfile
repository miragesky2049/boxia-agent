ARG NODE_IMAGE=node:24-alpine
FROM ${NODE_IMAGE} AS build

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable && pnpm install --frozen-lockfile

COPY . .

RUN pnpm run build

ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.27-alpine
FROM ${NGINX_IMAGE}

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY nginx/proxy-headers.conf /etc/nginx/snippets/proxy-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-qO-", "http://127.0.0.1:8080/healthz"]
