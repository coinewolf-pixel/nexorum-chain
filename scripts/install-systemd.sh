#!/usr/bin/env bash
# Install systemd services so the testnet nodes and the monitor start with the server.
#
#   sudo BASE=/data/ayvia/.testnet scripts/install-systemd.sh
#
# Creates:
#   ayvia-node@0 .. ayvia-node@N-1   one service per validator node
#   ayvia-monitor                      network monitor (alerts + AI explanations)
# Settings: BASE (testnet data, default <repo>/.testnet), NODES (default 4),
#           RUN_USER (default: the user who called sudo).
# Telegram: put TELEGRAM_BOT_TOKEN=... and TELEGRAM_CHAT_ID=... into /etc/ayvia/monitor.env
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${BASE:-$REPO/.testnet}"
NODES="${NODES:-4}"
RUN_USER="${RUN_USER:-${SUDO_USER:-root}}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
BIN="$(command -v ayviad || echo "$REPO/build/ayviad")"
[[ -x "$BIN" ]] || { echo "ayviad not found: run 'make install' first"; exit 1; }
[[ -d "$BASE/node0" ]] || { echo "no testnet in $BASE: run 'BASE=$BASE scripts/testnet.sh init' first"; exit 1; }

# nodes started by scripts/testnet.sh must not run twice
BASE="$BASE" NODES="$NODES" sudo -u "$RUN_USER" "$REPO/scripts/testnet.sh" stop || true

cat >/etc/systemd/system/ayvia-node@.service <<EOF
[Unit]
Description=AYVIA testnet validator node %i
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
ExecStart=$BIN start --home $BASE/node%i
Restart=on-failure
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

mkdir -p /etc/ayvia
[[ -f /etc/ayvia/monitor.env ]] || printf 'TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n' >/etc/ayvia/monitor.env
chmod 600 /etc/ayvia/monitor.env

NODE_LIST=""
for ((i = 0; i < NODES; i++)); do NODE_LIST+="${NODE_LIST:+,}127.0.0.1:$((26657 + 10 * i))"; done

cat >/etc/systemd/system/ayvia-monitor.service <<EOF
[Unit]
Description=AYVIA network monitor
After=network-online.target ayvia-node@0.service

[Service]
User=$RUN_USER
Environment=AI_PY=$RUN_HOME/ai.py
EnvironmentFile=/etc/ayvia/monitor.env
ExecStart=/usr/bin/python3 $REPO/scripts/monitor.py --nodes $NODE_LIST --log $BASE/monitor.log
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# control panel; the password is generated once and kept in /etc/ayvia/panel.env
if [[ ! -f /etc/ayvia/panel.env ]]; then
  printf 'PANEL_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')" >/etc/ayvia/panel.env
fi
chmod 600 /etc/ayvia/panel.env

cat >/etc/systemd/system/ayvia-panel.service <<EOF
[Unit]
Description=AYVIA control panel
After=network-online.target ayvia-node@0.service

[Service]
User=$RUN_USER
Environment=BASE=$BASE
Environment=NODES=$NODES
Environment=BIN=$BIN
EnvironmentFile=/etc/ayvia/panel.env
ExecStart=/usr/bin/python3 $REPO/panel/panel.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
for ((i = 0; i < NODES; i++)); do systemctl enable --now "ayvia-node@$i"; done
systemctl enable --now ayvia-monitor ayvia-panel
echo "Installed. Check: systemctl status 'ayvia-node@*' ayvia-monitor ayvia-panel --no-pager"
echo "Panel: http://$(hostname -I | awk '{print $1}'):8100"
echo "Panel password: sudo cat /etc/ayvia/panel.env"
