FROM node:20-slim

# Install Python (needed for welcome email subprocess)
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

# Install Python dependencies for the email service
COPY services/requirements.txt ./services/requirements.txt
RUN pip3 install -r services/requirements.txt --break-system-packages

COPY src/ ./src/
COPY public/ ./public/
COPY services/email-service/ ./services/email-service/
COPY services/shared/ ./services/shared/

# Create config directory for secret symlinks
RUN mkdir -p services/config

EXPOSE 8080
ENV PORT=8080

# Symlink mounted secrets to where settings.py expects them, then start Node
CMD ln -sf /secrets/oauth/oauth_client_secret.json /app/services/config/oauth_client_secret.json && \
    ln -sf /secrets/firebase_sa/firebase_service_account.json /app/services/config/firebase_service_account.json && \
    ln -sf /secrets/gmail/token.json /app/services/config/token.json && \
    exec node src/server.js
