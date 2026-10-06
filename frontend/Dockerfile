FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine
ENV APP_API_URL=http://localhost:8000 \
    AUTH_MODE=entra \
    ENTRA_CLIENT_ID="" \
    ENTRA_AUTHORITY="" \
    API_SCOPE=""

USER root
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker/40-config-json.sh /docker-entrypoint.d/40-config-json.sh
COPY --from=build /app/dist /usr/share/nginx/html
RUN chmod 0755 /docker-entrypoint.d/40-config-json.sh \
    && chown -R 101:0 /usr/share/nginx/html \
    && chmod -R g+w /usr/share/nginx/html
USER 101

EXPOSE 8080
