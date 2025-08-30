FROM node:18-alpine

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

# Expose port
EXPOSE 3000

# Start the application
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "3000"]
