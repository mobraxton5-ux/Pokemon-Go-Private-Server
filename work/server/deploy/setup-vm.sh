#!/usr/bin/env bash
# Run this ONCE on the Oracle Cloud VM after uploading the server to /opt/pogo.
#
#   ssh ubuntu@YOUR_PUBLIC_IP
#   sudo bash /opt/pogo/deploy/setup-vm.sh
#
# It installs Python + s2sphere, opens the local firewall for 53/udp and
# 443/tcp, installs a systemd service, and starts the server pointed at this
# box's public IP.
set -euo pipefail

APP_DIR=/opt/pogo

echo "==> Detecting public IP"
# Oracle instance metadata is the source of truth; fall back to an echo service.
PUBLIC_IP="$(curl -s --max-time 5 http://169.254.169.254/opc/v2/instance/ 2>/dev/null \
              | grep -oE '"publicIp"[^,]*' | grep -oE '[0-9.]+' | head -1 || true)"
if [ -z "${PUBLIC_IP:-}" ]; then
  PUBLIC_IP="$(curl -s --max-time 5 https://api.ipify.org || true)"
fi
if [ -z "${PUBLIC_IP:-}" ]; then
  echo "!! Could not auto-detect public IP. Pass it explicitly:"
  echo "   sudo PUBLIC_IP=203.0.113.7 bash $0"
  exit 1
fi
PUBLIC_IP="${PUBLIC_IP_OVERRIDE:-$PUBLIC_IP}"
echo "    public IP = $PUBLIC_IP"

echo "==> Installing Python + deps"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-pip curl
pip3 install --break-system-packages -r "$APP_DIR/deploy/requirements.txt" \
  || pip3 install -r "$APP_DIR/deploy/requirements.txt"

echo "==> Opening the LOCAL firewall (Oracle images block everything but SSH)"
# Oracle's Ubuntu image ships restrictive iptables rules. Insert allow rules
# for our two ports, ahead of the default REJECT, and persist them.
iptables -I INPUT -p tcp --dport 443 -j ACCEPT
iptables -I INPUT -p udp --dport 53  -j ACCEPT
apt-get install -y iptables-persistent || true
netfilter-persistent save || iptables-save > /etc/iptables/rules.v4 || true

echo "==> Making sure nothing else holds port 53"
# Ubuntu's systemd-resolved listens on 127.0.0.53:53 but NOT on the public
# iface, so it usually does not clash with a 0.0.0.0:53 bind. If your server
# fails to bind 53, uncomment the next two lines to free it:
# systemctl disable --now systemd-resolved || true
# rm -f /etc/resolv.conf && echo "nameserver 8.8.8.8" > /etc/resolv.conf

echo "==> Installing systemd service"
sed "s/REPLACE_WITH_PUBLIC_IP/$PUBLIC_IP/" \
  "$APP_DIR/deploy/pogo-server.service" > /etc/systemd/system/pogo-server.service
systemctl daemon-reload
systemctl enable pogo-server
systemctl restart pogo-server

sleep 2
echo
echo "============================================================"
echo "  Done. Server should be live."
echo "  Point each phone's Wi-Fi DNS at:  $PUBLIC_IP"
echo "  Game server:  https://$PUBLIC_IP:443   (Host-routed)"
echo
echo "  Watch live logs:   journalctl -u pogo-server -f"
echo "  Restart:           sudo systemctl restart pogo-server"
echo "  Stop:              sudo systemctl stop pogo-server"
echo "============================================================"
systemctl --no-pager --lines=15 status pogo-server || true
