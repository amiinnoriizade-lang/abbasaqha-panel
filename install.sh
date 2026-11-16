#!/bin/bash
set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

clear
echo -e "${GREEN}"
echo "=========================================================="
echo "      🧔🏻‍♂️  نصب‌کننده خودکار پنل مدیریت عباس آقا (AbbasAgha)     "
echo "=========================================================="
echo -e "${NC}"

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}لطفاً اسکریپت را با دسترسی root اجرا کنید (sudo su).${NC}"
  exit 1
fi

echo -e "${CYAN}[1/5] در حال به‌روزرسانی سیستم و نصب پیش‌نیازها...${NC}"
apt-get update -y
apt-get install -y curl wget git unzip jq ufw wireguard-tools iproute2

if ! command -v docker &> /dev/null; then
    echo -e "${CYAN}[2/5] در حال نصب Docker و Docker Compose...${NC}"
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
else
    echo -e "${GREEN}[2/5] Docker از قبل نصب است.${NC}"
fi

INSTALL_DIR="/opt/abbasagha-panel"
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/docker-compose.yml" ] && [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    cp -r "$SCRIPT_DIR/"* $INSTALL_DIR/
elif [ ! -f "$INSTALL_DIR/docker-compose.yml" ]; then
    echo -e "${YELLOW}آدرس مخزن گیت‌هاب را وارد کنید (یا Enter بزنید برای پیش‌فرض):${NC}"
    read -p "GitHub Repo URL: " REPO_URL
    REPO_URL=${REPO_URL:-"https://github.com/YOUR_USERNAME/abbasagha-panel.git"}
    git clone "$REPO_URL" $INSTALL_DIR
fi

echo -e "${CYAN}[3/5] پیکربندی اولیه پنل عباس آقا...${NC}"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    read -p "نام کاربری ادمین پنل [پیش‌فرض: admin]: " ADMIN_USER
    ADMIN_USER=${ADMIN_USER:-admin}
    read -p "رمز عبور ادمین پنل [پیش‌فرض: Abbas@1405]: " ADMIN_PASS
    ADMIN_PASS=${ADMIN_PASS:-Abbas@1405}
    read -p "پورت ورود به پنل وب [پیش‌فرض: 8080]: " PANEL_PORT
    PANEL_PORT=${PANEL_PORT:-8080}
    read -p "توکن ربات تلگرام (اختیاری - می‌توانید بعداً در پنل وارد کنید): " BOT_TOKEN
    read -p "آیدی عددی ادمین تلگرام (اختیاری): " ADMIN_TG_ID

    SECRET_KEY=$(openssl rand -hex 32)
    SERVER_IP=$(curl -s4 ifconfig.me || hostname -I | awk '{print $1}')

    cat <<EOF > $INSTALL_DIR/.env
PANEL_NAME=AbbasAgha
ADMIN_USERNAME=${ADMIN_USER}
ADMIN_PASSWORD=${ADMIN_PASS}
PANEL_PORT=${PANEL_PORT}
SECRET_KEY=${SECRET_KEY}
SERVER_IP=${SERVER_IP}
DATABASE_URL=sqlite+aiosqlite:///./data/abbasagha.db

# Telegram Bot & Gateways
BOT_TOKEN=${BOT_TOKEN}
ADMIN_TG_ID=${ADMIN_TG_ID}
CARD_NUMBER=6037-9975-0000-0000
CARD_HOLDER=عباس آقا
ZARINPAL_MERCHANT=
ABANGATE_API_KEY=
CRYPTO_API_KEY=
EOF
fi

echo -e "${CYAN}[4/5] فعال‌سازی IP Forwarding برای WireGuard / OpenVPN / L2TP...${NC}"
sysctl -w net.ipv4.ip_forward=1
grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf

echo -e "${CYAN}[5/5] راه‌اندازی سرویس‌ها با Docker Compose...${NC}"
mkdir -p $INSTALL_DIR/data $INSTALL_DIR/tunnels
docker compose up -d --build

source $INSTALL_DIR/.env
echo -e "${GREEN}"
echo "=========================================================="
echo "   ✅ نصب پنل عباس آقا با موفقیت به پایان رسید!            "
echo "----------------------------------------------------------"
echo -e "   🌐 آدرس پنل:   http://${SERVER_IP}:${PANEL_PORT}"
echo -e "   👤 نام کاربری:  ${ADMIN_USER}"
echo -e "   🔑 رمز عبور:    ${ADMIN_PASS}"
echo "----------------------------------------------------------"
echo "   دستور مدیریت سریع: abbasagha"
echo "=========================================================="
echo -e "${NC}"

cat << 'EOF' > /usr/local/bin/abbasagha
#!/bin/bash
cd /opt/abbasagha-panel
case "$1" in
  start) docker compose up -d ;;
  stop) docker compose down ;;
  restart) docker compose restart ;;
  logs) docker compose logs -f --tail=100 ;;
  update) git pull && docker compose up -d --build ;;
  *) echo "استفاده: abbasagha {start|stop|restart|logs|update}" ;;
esac
EOF
chmod +x /usr/local/bin/abbasagha
