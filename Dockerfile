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

COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh && mkdir -p services/config

EXPOSE 8080
ENV PORT=8080

ENTRYPOINT ["./entrypoint.sh"]
