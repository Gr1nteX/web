FROM python:3.13-slim AS python
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "psycopg[binary]==3.3.8" "docker==7.1.0"
WORKDIR /app
COPY api.py worker.py scaler.py ./

FROM nginx:1.28-alpine AS nginx
RUN apk add --no-cache openssl && openssl req -x509 -nodes -newkey rsa:2048 -days 365 -subj "/CN=localhost" -keyout /etc/nginx/key.pem -out /etc/nginx/cert.pem
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html
