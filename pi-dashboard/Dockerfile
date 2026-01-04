# Pi Dashboard - Lightweight Preact app for Raspberry Pi kiosk
FROM node:20-alpine AS builder

WORKDIR /app

# Build args for Vite environment variables
ARG VITE_API_URL=https://sara-api.avery.cloud
ARG VITE_ASSISTANT_NAME=Sara
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_ASSISTANT_NAME=$VITE_ASSISTANT_NAME

# Install dependencies
COPY package*.json ./
RUN npm ci

# Copy source and build
COPY . .
RUN npm run build

# Production stage
FROM node:20-alpine

WORKDIR /app

# Install serve for static file hosting
RUN npm install -g serve

# Copy built files
COPY --from=builder /app/dist ./dist

# Expose port
EXPOSE 3001

# Run the server
CMD ["serve", "-s", "dist", "-l", "3001"]
