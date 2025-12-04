# Use Node.js LTS version
FROM node:20-slim

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy application files
COPY . .

# Expose port (GCP Cloud Run will set PORT env var)
EXPOSE 8080

# Use PORT from environment or default to 8080
ENV PORT=8080

# Start the server
CMD ["node", "server.js"]

