#!/usr/bin/env bash
# deploy.sh — Set up Hermes on a fresh Ubuntu 24.04 droplet
#
# Usage: scp deploy.sh root@<ip>: && ssh root@<ip> bash deploy.sh
#
# Optional: HERMES_DOMAIN=143-198-1-1.sslip.io bash deploy.sh  (for HTTPS)

set -euo pipefail

HERMES_HOME="$HOME/.hermes"
REPO_DIR="$HOME/hermes"
DOMAIN="${HERMES_DOMAIN:-}"

echo "==> [1/5] System packages"
apt update -qq
PACKAGES="python3 python3-pip python3-venv git"
[ -n "$DOMAIN" ] && PACKAGES="$PACKAGES nginx certbot python3-certbot-nginx"
apt install -y -qq $PACKAGES

echo "==> [2/5] Clone hermes (your fork)"
if [ -d "$REPO_DIR" ]; then
    cd "$REPO_DIR" && git pull --ff-only
else
    git clone git@github.com:stevekfrey/hermes.git "$REPO_DIR"
fi

echo "==> [3/5] Install Hermes + deps"
cd "$REPO_DIR"
pip install --break-system-packages -e . httpx
mkdir -p "$HERMES_HOME/plugins"

echo "==> [4/5] Symlink plugin + auto-pull cron"
ln -sfn "$REPO_DIR/plugins/agi-phone" "$HERMES_HOME/plugins/agi-phone"

CRON_CMD="* * * * * cd $REPO_DIR && git pull --ff-only 2>&1 | logger -t hermes-sync"
( crontab -l 2>/dev/null | grep -v hermes-sync; echo "$CRON_CMD" ) | crontab -

echo "==> [5/5] Networking"
if [ -n "$DOMAIN" ]; then
    cat > /etc/nginx/sites-available/hermes <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8642;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
}
NGINX
    ln -sf /etc/nginx/sites-available/hermes /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "${CERT_EMAIL:-admin@$DOMAIN}"
    ENDPOINT="https://$DOMAIN/v1/chat/completions"
else
    ENDPOINT="http://$(curl -s ifconfig.me):8642/v1/chat/completions"
fi

IP=$(curl -s ifconfig.me)
echo ""
echo "==> Done!"
echo ""
echo "    Next steps:"
echo "    1. hermes setup                    # configure LLM provider + API keys"
echo "    2. echo 'HERMES_API_KEY=changeme' >> $HERMES_HOME/.env"
echo "    3. echo 'PHONE_RELAY_URL=https://mobile-claw-mcp-server.vercel.app' >> $HERMES_HOME/.env"
echo "    4. hermes gateway                  # start"
echo ""
echo "    Server IP:  $IP"
echo "    Phone endpoint: $ENDPOINT"
echo "    Auth: Authorization: Bearer <HERMES_API_KEY>"
