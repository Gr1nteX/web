FROM nginx:1.28-alpine

RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/certs /etc/nginx/dynamic \
    && openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -keyout /etc/nginx/certs/server.key \
        -out /etc/nginx/certs/server.crt

COPY nginx/nginx.conf /etc/nginx/nginx.conf

EXPOSE 443
