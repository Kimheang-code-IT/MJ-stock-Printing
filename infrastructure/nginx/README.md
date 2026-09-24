# Host reverse proxy (production)

Use this folder for **host-level** Nginx configuration that sits in front of
Docker Compose (TLS termination, public HTTP entry).

The frontend container already ships its own SPA nginx config at
`frontend/nginx.conf` (static files + `/api` → API). Do not move that file
here — Docker builds it from the `frontend/` context.

## Recommended production shape

```text
Internet → host Nginx (this folder) → frontend:80 → /api → api:8000
```

## `mj.conf`

`mj.conf` is a ready-to-use HTTPS reverse proxy for the Docker stack:

1. Replace `CHANGE_ME.example.com` with your domain (3 places).
2. Point the `ssl_certificate` / `ssl_certificate_key` paths at your cert.
   The defaults are the Let's Encrypt locations that `certbot` writes.
3. Install and reload:

   ```bash
   sudo cp mj.conf /etc/nginx/conf.d/mj.conf
   sudo nginx -t && sudo systemctl reload nginx
   ```

4. In `infrastructure/.env` keep the frontend published on loopback:

   ```
   FRONTEND_BIND=127.0.0.1
   FRONTEND_PORT=80
   ```

   Set `FRONTEND_BIND=0.0.0.0` (and change the `upstream` server address) only
   when nginx runs on a different machine than Docker.

### First-time certificate (Let's Encrypt)

```bash
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d CHANGE_ME.example.com
```

`certbot` renews automatically via its systemd timer. The HTTP server block in
`mj.conf` already serves `/.well-known/acme-challenge/` for the webroot method.

### HTTP-only (no TLS yet)

If you are not terminating TLS yet (e.g. an upstream load balancer already
does), use a plain server block instead of the HTTPS one:

```nginx
server {
    listen 80;
    server_name CHANGE_ME.example.com;
    client_max_body_size 32m;
    location / {
        proxy_pass http://mj_frontend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Caddy alternative

```text
CHANGE_ME.example.com {
    reverse_proxy 127.0.0.1:80
}
```

Caddy provisions and renews certificates automatically, so it is the smallest
option if you prefer not to manage certbot.
