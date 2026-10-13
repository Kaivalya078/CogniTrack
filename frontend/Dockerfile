# Build the React app, then serve the static files with Caddy (infra/Caddyfile is mounted in).
FROM node:22-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2
COPY --from=build /src/dist /srv
