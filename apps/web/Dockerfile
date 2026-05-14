FROM node:22-alpine

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@10 --activate

# Copy workspace config (needed for monorepo resolution)
COPY package.json pnpm-lock.yaml ./
COPY pnpm-workspace.yaml ../../

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy app source
COPY . .

# Development server
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
