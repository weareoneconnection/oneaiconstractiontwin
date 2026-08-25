# syntax=docker/dockerfile:1

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# --ignore-scripts is required: the postinstall step copies Cesium runtime assets with
# scripts/copy-cesium.mjs, which is not part of this stage's build context.
RUN npm ci --ignore-scripts --registry=https://registry.npmjs.org

FROM node:22-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_TENANT_ID
ARG NEXT_PUBLIC_ORGANIZATION_ID
ARG NEXT_PUBLIC_USER_ID
ARG NEXT_PUBLIC_ROLE
# NEXT_PUBLIC_* values are inlined at build time, so they must be present here and not
# only in the runtime environment.
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_TENANT_ID=${NEXT_PUBLIC_TENANT_ID} \
    NEXT_PUBLIC_ORGANIZATION_ID=${NEXT_PUBLIC_ORGANIZATION_ID} \
    NEXT_PUBLIC_USER_ID=${NEXT_PUBLIC_USER_ID} \
    NEXT_PUBLIC_ROLE=${NEXT_PUBLIC_ROLE}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN node scripts/copy-cesium.mjs && npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
RUN mkdir -p /app/.next/cache && chown -R nextjs:nodejs /app/.next
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
