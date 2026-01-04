FROM node:18-alpine AS builder

WORKDIR /app

# Provide Vite build-time envs via build args
ARG VITE_API_URL
ARG VITE_ASSISTANT_NAME
ARG VITE_DOMAIN
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_ASSISTANT_NAME=${VITE_ASSISTANT_NAME}
ENV VITE_DOMAIN=${VITE_DOMAIN}

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Production stage with serve
FROM node:18-alpine

# Install serve globally
RUN npm install -g serve

# Copy built files
COPY --from=builder /app/dist /app/dist

WORKDIR /app

# Expose port
EXPOSE 3000

# Serve with SPA fallback
CMD ["serve", "-s", "dist", "-l", "3000"]
