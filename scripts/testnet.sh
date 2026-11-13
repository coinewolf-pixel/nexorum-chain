#!/usr/bin/env bash
# AYVIA local testnet: several validator nodes on one machine.
#
#   scripts/testnet.sh init     create a fresh testnet (deletes the old one in $BASE)
#   scripts/testnet.sh start    start all nodes in the background
#   scripts/testnet.sh stop     stop all nodes
#   scripts/testnet.sh status   show height and peers of every node
#
# Settings (environment variables):
#   BASE      where node data lives          (default: ./.testnet)
#   BIN       path to ayviad               (default: ./build/ayviad or ayviad in PATH)
#   NODES     number of validators           (default: 4, the minimum that survives one failed node)
#   CHAIN_ID  chain id                       (default: ayvia-testnet-1)
#   BOTS      number of load-test accounts   (default: 10)
#
# TEST NETWORK ONLY: keys use the unencrypted "test" keyring backend and the
# AYV created here has no monetary value.
set -euo pipefail

cd "$(dirname "$0")/.."
BASE="${BASE:-$PWD/.testnet}"
NODES="${NODES:-4}"
CHAIN_ID="${CHAIN_ID:-ayvia-testnet-1}"
BOTS="${BOTS:-10}"
DENOM="uayv"                       # 1 AYV = 1_000_000 uayv
if [[ -z "${BIN:-}" ]]; then
  if [[ -x ./build/ayviad ]]; then BIN="$PWD/build/ayviad"; else BIN="$(command -v ayviad)"; fi
fi
KR=(--keyring-backend test)

# Test-only amounts (configurable later via the tokenomics proposal, see TOKENOMICS.md)
VAL_BALANCE="1000000000000${DENOM}"     # 1,000,000 AYV per validator
VAL_STAKE="100000000000${DENOM}"        #   100,000 AYV self-delegation
FAUCET_BALANCE="10000000000000${DENOM}" # 10,000,000 AYV for the faucet
BOT_BALANCE="10000000000${DENOM}"       #     10,000 AYV per load-test bot
MIN_GAS="0.0025${DENOM}"

port() { echo $(( $1 + 10 * $2 )); }   # port BASEPORT NODE_INDEX
rpc_port()  { port 26657 "$1"; }
p2p_port()  { port 26656 "$1"; }

# set KEY = VALUE inside [section] of a TOML file ("" = top level, before any section)
toml_set() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import re, sys
path, section, key, value = sys.argv[1:]
lines = open(path).read().split("\n")
cur, done = "", False
for i, line in enumerate(lines):
    m = re.match(r"^\[([^\]]+)\]\s*$", line)
    if m:
        cur = m.group(1)
        continue
    if cur == section and re.match(rf"^{re.escape(key)}\s*=", line):
        lines[i] = f"{key} = {value}"
        done = True
        break
if not done:
    sys.exit(f"key {key} not found in [{section}] of {path}")
open(path, "w").write("\n".join(lines))
PY
}

node_home() { echo "$BASE/node$1"; }

cmd_init() {
  echo "Creating $NODES-validator testnet '$CHAIN_ID' in $BASE"
  rm -rf "$BASE"
  mkdir -p "$BASE/logs" "$BASE/gentxs"
  local n0; n0="$(node_home 0)"

  for ((i = 0; i < NODES; i++)); do
    local h; h="$(node_home "$i")"
    "$BIN" init "node$i" --chain-id "$CHAIN_ID" --default-denom "$DENOM" --home "$h" >/dev/null 2>&1
    "$BIN" keys add "val$i" "${KR[@]}" --home "$h" >/dev/null 2>&1
  done

  # client keyring with the faucet and load-test bots
  local ck="$BASE/client"
  "$BIN" keys add faucet "${KR[@]}" --home "$ck" >/dev/null 2>&1
  for ((b = 0; b < BOTS; b++)); do
    "$BIN" keys add "bot$b" "${KR[@]}" --home "$ck" >/dev/null 2>&1
  done

  # genesis accounts are added on node0, then the genesis is shared
  for ((i = 0; i < NODES; i++)); do
    local addr; addr="$("$BIN" keys show "val$i" -a "${KR[@]}" --home "$(node_home "$i")")"
    "$BIN" genesis add-genesis-account "$addr" "$VAL_BALANCE" --home "$n0"
  done
  "$BIN" genesis add-genesis-account "$("$BIN" keys show faucet -a "${KR[@]}" --home "$ck")" "$FAUCET_BALANCE" --home "$n0"
  for ((b = 0; b < BOTS; b++)); do
    "$BIN" genesis add-genesis-account "$("$BIN" keys show "bot$b" -a "${KR[@]}" --home "$ck")" "$BOT_BALANCE" --home "$n0"
  done

  # faster blocks and short governance periods are convenient on a testnet
  python3 - "$n0/config/genesis.json" <<'PY'
import json, sys
p = sys.argv[1]
g = json.load(open(p))
gov = g["app_state"]["gov"]["params"]
gov["voting_period"] = "300s"
gov["expedited_voting_period"] = "120s"
gov["max_deposit_period"] = "600s"
json.dump(g, open(p, "w"), indent=1)
PY

  # every validator signs its own gentx with the shared genesis
  for ((i = 0; i < NODES; i++)); do
    local h; h="$(node_home "$i")"
    [[ $i -gt 0 ]] && cp "$n0/config/genesis.json" "$h/config/genesis.json"
    "$BIN" genesis gentx "val$i" "$VAL_STAKE" --chain-id "$CHAIN_ID" "${KR[@]}" --home "$h" \
      --moniker "ayvia-validator-$i" --output-document "$BASE/gentxs/val$i.json" >/dev/null 2>&1
  done
  mkdir -p "$n0/config/gentx"
  cp "$BASE"/gentxs/*.json "$n0/config/gentx/"
  "$BIN" genesis collect-gentxs --home "$n0" >/dev/null 2>&1
  "$BIN" genesis validate-genesis --home "$n0"

  # peers
  local peers=""
  for ((i = 0; i < NODES; i++)); do
    local id; id="$("$BIN" comet show-node-id --home "$(node_home "$i")")"
    peers+="${peers:+,}$id@127.0.0.1:$(p2p_port "$i")"
  done

  for ((i = 0; i < NODES; i++)); do
    local h; h="$(node_home "$i")"
    [[ $i -gt 0 ]] && cp "$n0/config/genesis.json" "$h/config/genesis.json"
    local c="$h/config/config.toml" a="$h/config/app.toml"
    toml_set "$c" "" proxy_app "\"tcp://127.0.0.1:$(port 26658 "$i")\""
    toml_set "$c" rpc laddr "\"tcp://127.0.0.1:$(rpc_port "$i")\""
    toml_set "$c" rpc pprof_laddr "\"localhost:$((6060 + i))\""
    toml_set "$c" p2p laddr "\"tcp://0.0.0.0:$(p2p_port "$i")\""
    toml_set "$c" p2p persistent_peers "\"$peers\""
    toml_set "$c" p2p addr_book_strict false
    toml_set "$c" p2p allow_duplicate_ip true
    toml_set "$c" consensus timeout_commit '"2s"'
    toml_set "$a" "" minimum-gas-prices "\"$MIN_GAS\""
    toml_set "$a" api enable true
    toml_set "$a" api address "\"tcp://127.0.0.1:$((1317 + i))\""
    toml_set "$a" grpc address "\"127.0.0.1:$((9090 + i))\""
  done
  echo "Done. Validators: $NODES, bots: $BOTS. Start with: scripts/testnet.sh start"
}

cmd_start() {
  if [[ ! -f "$(node_home 0)/config/genesis.json" ]]; then
    echo "No testnet in $BASE. Run 'scripts/testnet.sh init' first (and check the BASE variable)." >&2
    exit 1
  fi
  for ((i = 0; i < NODES; i++)); do
    local h; h="$(node_home "$i")"
    if [[ -f "$BASE/node$i.pid" ]] && kill -0 "$(cat "$BASE/node$i.pid")" 2>/dev/null; then
      echo "node$i already running"; continue
    fi
    nohup "$BIN" start --home "$h" >>"$BASE/logs/node$i.log" 2>&1 &
    echo $! >"$BASE/node$i.pid"
    echo "node$i started (pid $!, rpc http://127.0.0.1:$(rpc_port "$i"), api http://127.0.0.1:$((1317 + i)))"
  done
}

cmd_stop() {
  for ((i = 0; i < NODES; i++)); do
    local f="$BASE/node$i.pid"
    if [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null; then
      kill "$(cat "$f")" && echo "node$i stopped"
    fi
    rm -f "$f"
  done
}

cmd_status() {
  for ((i = 0; i < NODES; i++)); do
    python3 - "$(rpc_port "$i")" "$i" <<'PY'
import json, sys, urllib.request
port, i = sys.argv[1], sys.argv[2]
try:
    s = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3))["result"]
    n = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/net_info", timeout=3))["result"]
    si = s["sync_info"]
    print(f"node{i}: height {si['latest_block_height']}  peers {n['n_peers']}  catching_up {si['catching_up']}")
except Exception as e:
    print(f"node{i}: not responding ({e.__class__.__name__})")
PY
  done
}

case "${1:-}" in
  init) cmd_init ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac
