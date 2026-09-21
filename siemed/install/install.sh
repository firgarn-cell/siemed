#!/bin/bash
# SIEMED Station — инсталлятор для Debian 12 (Bookworm).
# Запуск: sudo bash install/install.sh
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Запустите инсталлятор от root: sudo bash install/install.sh"
  exit 1
fi

. /etc/os-release
if [[ "${ID:-}" != "debian" ]]; then
  echo "Ожидается Debian. Обнаружено: ${ID:-unknown}"
  exit 1
fi

SRC="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX=/opt/siemed
DATA=/var/lib/siemed
ETC=/etc/siemed
USER_NAME=siemed

echo "==> пакеты Debian"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip python3-dev \
  ffmpeg mpv rsync tzdata \
  adduser ca-certificates

if ! id -u "$USER_NAME" >/dev/null 2>&1; then
  adduser --system --group --home "$DATA" --shell /usr/sbin/nologin "$USER_NAME"
fi
usermod -aG video,audio "$USER_NAME" 2>/dev/null || true

echo "==> файлы в $PREFIX"
mkdir -p "$PREFIX" "$DATA/archive" "$DATA/lessons" "$ETC" /run/siemed
rsync -a --delete --exclude '.venv' --exclude 'var' --exclude '__pycache__' "$SRC/" "$PREFIX/"
python3 -m venv "$PREFIX/.venv"
"$PREFIX/.venv/bin/pip" install --upgrade pip
"$PREFIX/.venv/bin/pip" install -r "$PREFIX/requirements.txt"

if [[ ! -f "$ETC/station.env" ]]; then
  SECRET="$("$PREFIX/.venv/bin/python" -c 'import secrets; print(secrets.token_hex(24))')"
  ADMIN_PWD="$("$PREFIX/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(10))')"
  cat > "$ETC/station.env" <<EOF
SIEMED_STATION_NAME=Кабинет сестринского дела
SIEMED_TIMEZONE=Asia/Yekaterinburg
SIEMED_SECRET=$SECRET
SIEMED_LAN_HOST=0.0.0.0
SIEMED_LAN_PORT=8080
SIEMED_TABLET_HOST=0.0.0.0
SIEMED_TABLET_PORT=8070
SIEMED_PUBLIC_HOST=0.0.0.0
SIEMED_PUBLIC_PORT=9080
SIEMED_PUBLIC_URL=http://$(hostname -I | awk '{print $1}'):9080
SIEMED_DATA_DIR=$DATA
SIEMED_NVR_HOST=192.168.0.99
SIEMED_NVR_USER=admin
SIEMED_NVR_PASSWORD=12345
SIEMED_MPV_SCREEN=1
SIEMED_MPV_IPC=/run/siemed/mpv.sock
DISPLAY=:0
EOF
  echo "$ADMIN_PWD" > "$ETC/admin.initial"
  chmod 600 "$ETC/admin.initial" "$ETC/station.env"
else
  ADMIN_PWD=""
fi

chown -R "$USER_NAME:$USER_NAME" "$PREFIX" "$DATA" /run/siemed
chmod 750 "$ETC"
chown root:"$USER_NAME" "$ETC" "$ETC/station.env" 2>/dev/null || true

install -m 644 "$SRC/install/siemed-station.service" /etc/systemd/system/siemed-station.service

# первичная БД и пароль администратора
if [[ -n "${ADMIN_PWD:-}" ]]; then
  cd "$PREFIX"
  set -a
  # shellcheck disable=SC1091
  source "$ETC/station.env"
  set +a
  sudo -u "$USER_NAME" env PYTHONPATH="$PREFIX" \
    "$PREFIX/.venv/bin/python" -c "from app.bootstrap import init_db; init_db('$ADMIN_PWD')"
fi

systemctl daemon-reload
systemctl enable --now siemed-station.service

LAN_IP="$(hostname -I | awk '{print $1}')"
echo
echo "=============================================="
echo " SIEMED Station установлен"
echo " Рабочее место (админка + ответственный): http://${LAN_IP}:8080/"
echo " Планшет поста: http://${LAN_IP}:8070/"
echo " Публичный сайт записи (NAT сюда): http://${LAN_IP}:9080/"
echo " Логин администратора: admin"
if [[ -f "$ETC/admin.initial" ]]; then
  echo " Пароль администратора (сохраните и удалите файл):"
  cat "$ETC/admin.initial"
fi
echo " Конфиг: $ETC/station.env"
echo " Данные и архив: $DATA"
echo " Проброс на фаерволе: ТОЛЬКО порт 9080, не 8070 и не 8080."
echo "=============================================="
