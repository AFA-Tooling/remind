# Use Node.js LTS version
FROM node:20-slim

# Install Python and pip
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install Node dependencies
RUN npm ci --only=production

# Copy Python requirements
COPY services/requirements.txt ./services/requirements.txt

# Install Python dependencies
# Note: --break-system-packages is needed on Debian Bookworm (base of node:20)
RUN pip3 install -r services/requirements.txt --break-system-packages

# Copy application files
COPY . .

# Expose port (GCP Cloud Run will set PORT env var)
EXPOSE 8080

# Use PORT from environment or default to 8080
ENV PORT=8080

# Start the server (pointing to the new src location)
CMD ["node", "src/server.js"]

