#!/usr/bin/env python3
"""
AYVIA control panel: one web page for the whole testnet.

  PANEL_KEY="long-password" BASE=/data/ayvia/testnet python3 panel/panel.py
  open http://SERVER_IP:8100

Shows: server load and services, chain height and block time, validators, latest
blocks and transactions, wallets and balances, monitor log. Lets you start/stop the
load bots, send test AYV from the faucet, and connect the Keplr wallet.

Everything except the Keplr proxy (/rpc, /rest) requires the panel password.
The proxy exposes the node RPC/REST of node0 so a wallet in the browser can talk to the
chain; on a public server put the panel behind HTTPS (e.g. Tailscale serve).
Standard library only.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
KEY = os.environ.get("PANEL_KEY", "")
PORT = int(os.environ.get("PANEL_PORT", "8100"))
HOST = os.environ.get("PANEL_HOST", "0.0.0.0")
BASE = os.environ.get("BASE", os.path.join(REPO, ".testnet"))
NODES = int(os.environ.get("NODES", "4"))
CHAIN_ID = os.environ.get("CHAIN_ID", "ayvia-testnet-1")
RPC = os.environ.get("RPC", "http://127.0.0.1:26657")
REST = os.environ.get("REST", "http://127.0.0.1:1317")
BIN = os.environ.get("BIN") or (os.path.join(REPO, "build", "ayviad")
                                if os.access(os.path.join(REPO, "build", "ayviad"), os.X_OK)
                                else (shutil.which("ayviad") or "ayviad"))
CLIENT_HOME = os.path.join(BASE, "client")
SERVICES = [f"ayvia-node@{i}" for i in range(NODES)] + ["ayvia-monitor", "ollama", "myai", "docker"]
FAUCET_MAX_AYV = 1000
FAUCET_LOCK = threading.Lock()
BOTS = {"proc": None, "started": None, "params": None, "log": os.path.join(BASE, "bots.log")}
BOTS_STATE = os.path.join(BASE, "bots.json")  # remembers continuous bots across panel restarts / reboots
BOTS_LOCK = threading.Lock()


# ---------------------------------------------------------------- data sources

def get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def rpc(path):
    return get_json(RPC + path)["result"]


def rest(path):
    return get_json(REST + path)


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:  # a stopped node must not break the whole page
        return default if default is not None else {"error": f"{e.__class__.__name__}: {e}"[:200]}


def system_info():
    mem = {}
    try:
        for line in open("/proc/meminfo"):
            k, v = line.split(":")
            mem[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    disks = []
    for path in ("/", "/data"):
        if os.path.isdir(path):
            u = shutil.disk_usage(path)
            disks.append({"path": path, "total": u.total, "used": u.used, "free": u.free})
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    return {"load": [round(x, 2) for x in load], "cpus": os.cpu_count(),
            "mem_total": mem.get("MemTotal", 0), "mem_available": mem.get("MemAvailable", 0),
            "disks": disks}


def services():
    out = []
    for s in SERVICES:
        try:
            r = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True, timeout=5)
            state = r.stdout.strip()
            if state not in ("active", "inactive", "failed", "activating", "deactivating", "reloading"):
                state = "unknown"  # no systemd, or the service is not installed
        except (OSError, subprocess.TimeoutExpired):
            state = "unknown"
        out.append({"name": s, "state": state})
    return out


def nodes():
    res = []
    for i in range(NODES):
        port = 26657 + 10 * i
        try:
            s = get_json(f"http://127.0.0.1:{port}/status", 3)["result"]
            n = get_json(f"http://127.0.0.1:{port}/net_info", 3)["result"]
            res.append({"name": f"node{i}", "up": True, "height": int(s["sync_info"]["latest_block_height"]),
                        "peers": int(n["n_peers"]), "catching_up": s["sync_info"]["catching_up"]})
        except Exception:
            res.append({"name": f"node{i}", "up": False})
    return res


def cons_address(pubkey_b64):
    """CometBFT validator address = first 20 bytes of sha256(ed25519 pubkey), hex upper."""
    return hashlib.sha256(base64.b64decode(pubkey_b64)).digest()[:20].hex().upper()


def validators():
    vals = rest("/cosmos/staking/v1beta1/validators?pagination.limit=200")["validators"]
    pool = safe(lambda: rest("/cosmos/staking/v1beta1/pool")["pool"], {})
    total = sum(int(v["tokens"]) for v in vals if v["status"] == "BOND_STATUS_BONDED") or 1
    out = []
    for v in vals:
        out.append({
            "moniker": v["description"]["moniker"], "operator": v["operator_address"],
            "cons": cons_address(v["consensus_pubkey"]["key"]) if v.get("consensus_pubkey") else "",
            "status": v["status"].replace("BOND_STATUS_", "").lower(), "jailed": v["jailed"],
            "tokens": int(v["tokens"]), "share": int(v["tokens"]) / total if v["status"] == "BOND_STATUS_BONDED" else 0,
            "commission": float(v["commission"]["commission_rates"]["rate"]),
        })
    out.sort(key=lambda x: -x["tokens"])
    return {"validators": out, "bonded": int(pool.get("bonded_tokens", 0) or 0)}


def chain():
    st = rpc("/status")
    h = int(st["sync_info"]["latest_block_height"])
    metas = rpc(f"/blockchain?minHeight={max(1, h - 19)}&maxHeight={h}")["block_metas"]
    names = {}
    try:
        for v in validators()["validators"]:
            names[v["cons"]] = v["moniker"]
    except Exception:
        pass
    blocks = [{"height": int(m["header"]["height"]), "time": m["header"]["time"], "txs": int(m["num_txs"]),
               "proposer": names.get(m["header"]["proposer_address"], m["header"]["proposer_address"][:10])}
              for m in metas]
    avg = None
    if len(blocks) > 1:
        t = [time.mktime(time.strptime(b["time"][:19], "%Y-%m-%dT%H:%M:%S")) for b in blocks]
        avg = round((t[0] - t[-1]) / (len(t) - 1), 2)
    supply = safe(lambda: int(rest("/cosmos/bank/v1beta1/supply/by_denom?denom=uayv")["amount"]["amount"]), 0)
    inflation = safe(lambda: float(rest("/cosmos/mint/v1beta1/inflation")["inflation"]), 0)
    mempool = safe(lambda: int(rpc("/num_unconfirmed_txs")["n_txs"]), 0)
    return {"chain_id": st["node_info"]["network"], "version": st["node_info"]["version"], "height": h,
            "time": st["sync_info"]["latest_block_time"], "block_time": avg, "blocks": blocks,
            "supply": supply, "inflation": inflation, "mempool": mempool}


def txs(limit=25):
    st = rpc("/status")
    h = int(st["sync_info"]["latest_block_height"])
    q = urllib.parse.quote(f"tx.height>={max(1, h - 500)}")
    d = rest(f"/cosmos/tx/v1beta1/txs?query={q}&order_by=ORDER_BY_DESC&page=1&limit={limit}")
    out = []
    for t in d.get("tx_responses", [])[:limit]:
        msgs = t["tx"]["body"]["messages"]
        m = msgs[0] if msgs else {}
        amount = sum(int(c["amount"]) for c in m.get("amount", []) if isinstance(c, dict) and c.get("denom") == "uayv")
        fee = sum(int(c["amount"]) for c in t["tx"]["auth_info"]["fee"]["amount"] if c["denom"] == "uayv")
        out.append({"hash": t["txhash"], "height": int(t["height"]), "type": m.get("@type", "").split(".")[-1],
                    "from": m.get("from_address", ""), "to": m.get("to_address", ""), "amount": amount,
                    "fee": fee, "code": t["code"], "time": t["timestamp"], "log": t.get("raw_log", "")[:120]})
    return out


def cli(*args, timeout=60):
    return subprocess.run([BIN, *args], capture_output=True, text=True, timeout=timeout)


def accounts():
    r = cli("keys", "list", "--keyring-backend", "test", "--home", CLIENT_HOME, "--output", "json")
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout).strip()[-200:]}
    out = []
    for k in json.loads(r.stdout or "[]"):
        bal = safe(lambda: int(rest(f"/cosmos/bank/v1beta1/balances/{k['address']}/by_denom?denom=uayv")
                               ["balance"]["amount"]), -1)
        out.append({"name": k["name"], "address": k["address"], "balance": bal})
    order = lambda a: (a["name"] != "faucet", int(re.sub(r"\D", "", a["name"]) or 0))  # noqa: E731
    return sorted(out, key=order)


def tail(path, n=40):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()[-n:]
    except OSError:
        return []


# ---------------------------------------------------------------- actions

def bots_state():
    with BOTS_LOCK:
        p = BOTS["proc"]
        running = p is not None and p.poll() is None
        return {"running": running, "started": BOTS["started"], "params": BOTS["params"],
                "exit_code": None if (p is None or running) else p.returncode,
                "log": [line.rstrip("\n") for line in tail(BOTS["log"], 30)]}


def save_bots_state(running, params):
    try:
        with open(BOTS_STATE, "w") as f:
            json.dump({"running": running, "params": params}, f)
    except OSError:
        pass


def bots_start(b):
    duration = int(b.get("duration", 60))  # 0 = without stopping
    rate = float(b.get("rate", 2))
    count = int(b.get("bots", 10))
    if not ((duration == 0 or 5 <= duration <= 3600) and 0.1 <= rate <= 50 and 2 <= count <= 100):
        raise ValueError("Длительность 5–3600 с (или без остановки), скорость 0.1–50 tx/s, ботов 2–100")
    with BOTS_LOCK:
        if BOTS["proc"] is not None and BOTS["proc"].poll() is None:
            raise ValueError("Боты уже работают. Сначала остановите их.")
        os.makedirs(BASE, exist_ok=True)
        log = open(BOTS["log"], "a" if duration == 0 else "w")
        BOTS["proc"] = subprocess.Popen(
            [sys.executable, "-u", os.path.join(REPO, "scripts", "loadbots.py"), "--home", CLIENT_HOME,
             "--duration", str(duration), "--rate", str(rate), "--bots", str(count), "--bin", BIN,
             "--chain-id", CHAIN_ID, "--node", RPC.replace("http://", "tcp://"), "--cycle", "300"],
            stdout=log, stderr=subprocess.STDOUT, cwd=REPO)
        BOTS["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
        BOTS["params"] = {"duration": duration, "rate": rate, "bots": count}
        save_bots_state(duration == 0, BOTS["params"])
    return bots_state()


def bots_resume():
    """After a panel restart or a reboot, start continuous bots again if they were running."""
    try:
        st = json.load(open(BOTS_STATE))
    except (OSError, ValueError):
        return
    if st.get("running") and st.get("params", {}).get("duration") == 0:
        time.sleep(float(os.environ.get("PANEL_RESUME_DELAY", "20")))  # let the nodes start after a reboot
        # bots left over from a panel that was killed by hand must not run twice
        subprocess.run(["pkill", "-f", f"loadbots.py --home {CLIENT_HOME}"], capture_output=True)
        try:
            bots_start(st["params"])
            print("continuous bots resumed", flush=True)
        except ValueError as e:
            print(f"could not resume bots: {e}", flush=True)


def bots_stop():
    save_bots_state(False, BOTS["params"])
    with BOTS_LOCK:
        p = BOTS["proc"]
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
    return bots_state()


def faucet(b):
    addr = str(b.get("address", "")).strip()
    if not re.fullmatch(r"ayv1[02-9ac-hj-np-z]{38,58}", addr):
        raise ValueError("Адрес должен начинаться с ayv1")
    try:
        ayv = float(b.get("amount", 0))
    except (TypeError, ValueError):
        raise ValueError("Сумма должна быть числом")
    if not 0 < ayv <= FAUCET_MAX_AYV:
        raise ValueError(f"Сумма от 0 до {FAUCET_MAX_AYV} AYV")
    amount = int(round(ayv * 1_000_000))
    with FAUCET_LOCK:
        r = cli("tx", "bank", "send", "faucet", addr, f"{amount}uayv", "--fees", "500uayv",
                "--chain-id", CHAIN_ID, "--node", RPC.replace("http://", "tcp://"),
                "--keyring-backend", "test", "--home", CLIENT_HOME, "-y", "-o", "json")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise ValueError((r.stderr or r.stdout).strip()[-200:] or "ошибка ayviad")
    if d.get("code", 1) != 0:
        raise ValueError(d.get("raw_log", "транзакция отклонена")[:200])
    return {"txhash": d["txhash"], "amount": amount, "to": addr}


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s  %s\n" % (self.address_string(), fmt % args))

    def send(self, code, obj=None, body=None, ctype="application/json; charset=utf-8", extra=None):
        data = body if body is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if not KEY:
            return False
        got = self.headers.get("Authorization", "")
        cands = []
        if got.startswith("Bearer "):
            cands += [got[7:], urllib.parse.unquote(got[7:])]
        try:
            c = SimpleCookie(self.headers.get("Cookie", ""))
            if "nxpanel" in c:
                cands.append(urllib.parse.unquote(c["nxpanel"].value))
        except Exception:
            pass
        return any(hmac.compare_digest(x.encode(), KEY.encode()) for x in cands if x)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("Слишком большой запрос")
        raw = self.rfile.read(n) if n else b""
        return raw

    # ---- Keplr proxy: /rpc/... -> node0 RPC, /rest/... -> node0 REST (no password, read + broadcast)
    def proxy(self, method, raw=None):
        path = self.path
        if path == "/rpc" or path.startswith("/rpc/") or path.startswith("/rpc?"):
            target = RPC + (path[4:] or "/")
        else:
            target = REST + (path[5:] or "/")
        req = urllib.request.Request(target, data=raw if method == "POST" else None, method=method,
                                     headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        cors = {"Access-Control-Allow-Origin": "*"}
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                self.send(r.status, body=r.read(), ctype=r.headers.get("Content-Type", "application/json"), extra=cors)
        except urllib.error.HTTPError as e:
            self.send(e.code, body=e.read(), ctype=e.headers.get("Content-Type", "application/json"), extra=cors)
        except Exception as e:
            self.send(502, {"error": f"узел недоступен: {e.__class__.__name__}"}, extra=cors)

    def is_proxy(self):
        p = self.path
        return p == "/rpc" or p.startswith(("/rpc/", "/rpc?", "/rest/"))

    def do_OPTIONS(self):
        self.send(204, body=b"", extra={"Access-Control-Allow-Origin": "*",
                                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                        "Access-Control-Allow-Headers": "Content-Type"})

    def do_GET(self):
        if self.is_proxy():
            return self.proxy("GET")
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return self.send(200, body=PAGE.encode(), ctype="text/html; charset=utf-8")
        if path == "/api/health":
            return self.send(200, {"ok": True})
        if not self.authorized():
            return self.send(401, {"error": "Неверный пароль панели"})
        routes = {
            "/api/overview": lambda: {"system": system_info(), "services": services(), "nodes": nodes(),
                                      "chain": safe(chain)},
            "/api/validators": lambda: safe(validators),
            "/api/txs": lambda: {"txs": safe(txs, [])},
            "/api/accounts": lambda: {"accounts": safe(accounts, [])},
            "/api/bots": bots_state,
            "/api/monitor": lambda: {"lines": [x.rstrip("\n") for x in tail(os.path.join(BASE, "monitor.log"), 40)]},
            "/api/config": lambda: {"chain_id": CHAIN_ID, "faucet_max": FAUCET_MAX_AYV},
        }
        if path in routes:
            return self.send(200, routes[path]())
        self.send(404, {"error": "нет такого адреса"})

    def do_POST(self):
        raw = self.body()
        if self.is_proxy():
            return self.proxy("POST", raw)
        if not self.authorized():
            return self.send(401, {"error": "Неверный пароль панели"})
        try:
            b = json.loads(raw.decode() or "{}")
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/bots/start":
                return self.send(200, bots_start(b))
            if path == "/api/bots/stop":
                return self.send(200, bots_stop())
            if path == "/api/faucet":
                return self.send(200, faucet(b))
            self.send(404, {"error": "нет такого адреса"})
        except (ValueError, json.JSONDecodeError) as e:
            self.send(400, {"error": str(e)})
        except Exception as e:
            self.send(500, {"error": f"внутренняя ошибка: {e}"})


PAGE = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AYVIA — панель</title>
<style>
:root{--bg:#070b14;--card:#0e1524;--line:#1c2740;--text:#dbe4f3;--muted:#7d8ba6;--acc:#4f8cff;--ok:#2fbf71;--warn:#e6a23c;--bad:#e5484d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:5;background:#070b14ee;border-bottom:1px solid var(--line);padding:10px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header b{letter-spacing:.12em;color:#fff}header nav a{color:var(--muted);text-decoration:none;margin-right:12px}header nav a:hover{color:#fff}
#key{margin-left:auto;background:var(--card);border:1px solid var(--line);color:var(--text);padding:6px 10px;border-radius:8px;width:200px}
main{max-width:1200px;margin:0 auto;padding:20px;display:grid;gap:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;overflow:auto}
h2{font-size:15px;font-weight:600;margin:0 0 12px;color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.stat{background:#0a101d;border:1px solid var(--line);border-radius:10px;padding:10px}.stat div:first-child{color:var(--muted);font-size:12px}.stat div:last-child{font-size:18px;color:#fff}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);font-weight:500}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
.ok{color:var(--ok);border-color:#1f5c3c}.warn{color:var(--warn);border-color:#6b5222}.bad{color:var(--bad);border-color:#6b2427}
input,button{font:inherit}input[type=text],input[type=number]{background:#0a101d;border:1px solid var(--line);color:var(--text);padding:7px 10px;border-radius:8px}
button{background:var(--acc);color:#fff;border:0;padding:7px 14px;border-radius:8px;cursor:pointer}button.sec{background:#1c2740}button:disabled{opacity:.5}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}.muted{color:var(--muted)}pre{background:#0a101d;border:1px solid var(--line);border-radius:8px;padding:10px;max-height:300px;overflow:auto;font-size:12px;white-space:pre-wrap;margin:8px 0 0}
.copy{cursor:pointer;border-bottom:1px dotted var(--muted)}
</style></head><body>
<header><b>AYVIA</b><span class="muted" id="netid">testnet</span>
<nav><a href="#overview">Обзор</a><a href="#chain">Блоки</a><a href="#vals">Валидаторы</a><a href="#txs">Транзакции</a><a href="#wallets">Кошельки</a><a href="#bots">Боты</a><a href="#faucet">Кран</a><a href="#keplr">Keplr</a><a href="#monitor">Наблюдатель</a></nav>
<input id="key" type="password" placeholder="Пароль панели"></header>
<main>
<div id="auth" class="muted"></div>
<section id="overview"><h2>Обзор</h2><div class="grid" id="stats"></div><h2 style="margin-top:16px">Узлы и службы</h2><div class="grid" id="nodes"></div></section>
<section id="chain"><h2>Последние блоки</h2><table><thead><tr><th>Высота</th><th>Время</th><th>Транзакций</th><th>Предложил</th></tr></thead><tbody id="blocks"></tbody></table></section>
<section id="vals"><h2>Валидаторы</h2><table><thead><tr><th>Имя</th><th>Статус</th><th>Застейкано</th><th>Доля</th><th>Комиссия</th><th>Адрес</th></tr></thead><tbody id="valtab"></tbody></table></section>
<section id="txs"><h2>Последние транзакции</h2><table><thead><tr><th>Блок</th><th>Тип</th><th>От</th><th>Кому</th><th>Сумма</th><th>Комиссия</th><th>Итог</th><th>Хеш</th></tr></thead><tbody id="txtab"></tbody></table></section>
<section id="wallets"><h2>Кошельки тестовой сети</h2><p class="muted">Кран и боты. Ключи хранятся на сервере без шифрования — только для тестовой сети.</p><table><thead><tr><th>Имя</th><th>Адрес</th><th>Баланс</th></tr></thead><tbody id="acctab"></tbody></table></section>
<section id="bots"><h2>Боты нагрузки</h2>
<div class="row"><label><input type="checkbox" id="bforever"> без остановки</label>
Длительность, с <input type="number" id="bdur" value="60" min="5" max="3600" style="width:90px">
Скорость, tx/s <input type="number" id="brate" value="2" min="0.1" max="50" step="0.1" style="width:80px">
Ботов <input type="number" id="bnum" value="10" min="2" max="100" style="width:70px">
<button id="bstart">Запустить</button><button id="bstop" class="sec">Остановить</button></div>
<div id="bstate" class="muted"></div><pre id="blog">—</pre></section>
<section id="faucet"><h2>Кран тестовых AYV</h2><div class="row"><input type="text" id="faddr" placeholder="ayv1..." style="flex:1;min-width:260px">
<input type="number" id="famt" value="10" min="0.000001" step="any" style="width:110px"> AYV <button id="fsend">Отправить</button></div><div id="fres" class="muted"></div></section>
<section id="keplr"><h2>Кошелёк Keplr</h2><p class="muted">Добавляет сеть AYVIA Testnet в расширение Keplr и показывает ваш адрес и баланс. Переводы и стейкинг делаются в самом Keplr. Экспериментально: если Keplr не подключается по http, откройте панель через https (Tailscale serve).</p>
<div class="row"><button id="kconnect">Подключить Keplr</button></div><div id="kres" class="muted"></div></section>
<section id="monitor"><h2>Журнал наблюдателя</h2><pre id="mlog">—</pre></section>
</main>
<script>
const $=id=>document.getElementById(id);
const AYV=u=>(u/1e6).toLocaleString("ru-RU",{maximumFractionDigits:6});
const short=s=>s?s.slice(0,12)+"…"+s.slice(-6):"";
const bytes=n=>n>1e12?(n/1e12).toFixed(1)+" ТБ":(n/1e9).toFixed(1)+" ГБ";
function cookie(){document.cookie="nxpanel="+encodeURIComponent($("key").value.trim())+"; path=/; max-age=31536000; SameSite=Strict";}
try{$("key").value=localStorage.getItem("nxpanel")||"";}catch(e){}
cookie();
$("key").onchange=()=>{try{localStorage.setItem("nxpanel",$("key").value)}catch(e){} cookie(); refresh(true);};
async function api(path,body){
  const r=await fetch(path,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});
  const j=await r.json().catch(()=>({error:"сервер вернул не JSON"}));
  if(!r.ok) throw new Error(j.error||("ошибка "+r.status)); return j;
}
function td(text,cls){const t=document.createElement("td");t.textContent=text;if(cls)t.className=cls;return t;}
function tr(cells){const r=document.createElement("tr");cells.forEach(c=>r.appendChild(c));return r;}
function pill(text,kind){const s=document.createElement("span");s.className="pill "+kind;s.textContent=text;const t=document.createElement("td");t.appendChild(s);return t;}
function copyTd(full,shown){const t=td(shown,"mono copy");t.title="Нажмите, чтобы скопировать: "+full;t.onclick=()=>navigator.clipboard&&navigator.clipboard.writeText(full);return t;}
function stat(label,val){const d=document.createElement("div");d.className="stat";const a=document.createElement("div");a.textContent=label;const b=document.createElement("div");b.textContent=val;d.append(a,b);return d;}
async function overview(){
  const j=await api("/api/overview"); const s=j.system,c=j.chain||{};
  $("netid").textContent=c.chain_id||"сеть недоступна";
  const st=$("stats");st.textContent="";
  st.append(stat("Высота блока",c.height??"—"),stat("Время блока",c.block_time?c.block_time+" с":"—"),
    stat("Всего AYV",c.supply?AYV(c.supply):"—"),stat("Инфляция",c.inflation?(c.inflation*100).toFixed(2)+" %":"—"),
    stat("В очереди tx",c.mempool??"—"),stat("Нагрузка CPU",s.load[0]+" / "+s.cpus+" ядер"),
    stat("Память свободно",bytes(s.mem_available)+" из "+bytes(s.mem_total)));
  for(const d of s.disks) st.append(stat("Диск "+d.path+" свободно",bytes(d.free)+" из "+bytes(d.total)));
  const nd=$("nodes");nd.textContent="";
  for(const n of j.nodes){const e=stat(n.name,n.up?("высота "+n.height+", соседей "+n.peers):"не отвечает");e.lastChild.className=n.up?"ok":"bad";nd.append(e);}
  const names={active:"работает",inactive:"остановлена",failed:"ошибка",activating:"запускается",unknown:"не установлена"};
  for(const v of j.services){const e=stat(v.name,names[v.state]||v.state);
    e.lastChild.className=v.state==="active"?"ok":(v.state==="failed"?"bad":"muted");nd.append(e);}
  const tb=$("blocks");tb.textContent="";
  for(const b of (c.blocks||[])) tb.append(tr([td(b.height,"mono"),td(new Date(b.time).toLocaleTimeString("ru-RU")),td(b.txs),td(b.proposer)]));
  if(c.error) tb.append(tr([td("Узел недоступен: "+c.error)]));
}
async function vals(){
  const j=await api("/api/validators");const tb=$("valtab");tb.textContent="";
  if(j.error){tb.append(tr([td(j.error)]));return;}
  for(const v of j.validators) tb.append(tr([td(v.moniker),pill(v.jailed?"в тюрьме":(v.status==="bonded"?"активен":v.status),v.jailed?"bad":(v.status==="bonded"?"ok":"warn")),
    td(AYV(v.tokens)+" AYV"),td((v.share*100).toFixed(1)+" %"),td((v.commission*100).toFixed(0)+" %"),copyTd(v.operator,short(v.operator))]));
}
async function txs(){
  const j=await api("/api/txs");const tb=$("txtab");tb.textContent="";
  if(!j.txs.length){tb.append(tr([td("Пока нет транзакций","muted")]));return;}
  for(const t of j.txs) tb.append(tr([td(t.height,"mono"),td(t.type),copyTd(t.from,short(t.from)),copyTd(t.to,short(t.to)),
    td(t.amount?AYV(t.amount)+" AYV":"—"),td(AYV(t.fee)),pill(t.code===0?"успех":"ошибка",t.code===0?"ok":"bad"),copyTd(t.hash,t.hash.slice(0,10)+"…")]));
}
async function accounts(){
  const j=await api("/api/accounts");const tb=$("acctab");tb.textContent="";
  for(const a of j.accounts) tb.append(tr([td(a.name),copyTd(a.address,a.address),td(a.balance>=0?AYV(a.balance)+" AYV":"—")]));
}
async function bots(){
  const j=await api("/api/bots");
  $("bstate").textContent=j.running?("Работают с "+j.started+": "+j.params.bots+" ботов, "+j.params.rate+" tx/s, "+(j.params.duration?j.params.duration+" с":"без остановки (отчёт каждые 5 минут, после перезагрузки запустятся сами)"))
    :(j.started?("Остановлены. Последний запуск "+j.started+(j.exit_code===0?", баланс сошёлся":j.exit_code===2?", РАСХОЖДЕНИЕ баланса":"")):"Не запускались");
  $("blog").textContent=j.log.length?j.log.join("\n"):"—";
  $("bstart").disabled=j.running;$("bstop").disabled=!j.running;
}
async function monitor(){const j=await api("/api/monitor");$("mlog").textContent=j.lines.length?j.lines.join("\n"):"Журнал пуст. Наблюдатель: python3 scripts/monitor.py или служба ayvia-monitor.";}
let busy=false, tick=0;
async function refresh(all){
  if(busy) return; busy=true;
  try{ await overview(); await bots(); $("auth").textContent="";
    if(all||(++tick%3===0)){ await vals(); await txs(); await accounts(); await monitor(); } }
  catch(e){ $("auth").textContent=e.message.includes("пароль")?"Введите пароль панели вверху справа.":"Ошибка: "+e.message; }
  busy=false;
}
$("bforever").onchange=()=>{$("bdur").disabled=$("bforever").checked;};
$("bstart").onclick=async()=>{try{await api("/api/bots/start",{duration:$("bforever").checked?0:+$("bdur").value,rate:+$("brate").value,bots:+$("bnum").value});bots();}catch(e){$("bstate").textContent=e.message;}};
$("bstop").onclick=async()=>{try{await api("/api/bots/stop",{});bots();}catch(e){$("bstate").textContent=e.message;}};
$("fsend").onclick=async()=>{$("fres").textContent="Отправляю…";$("fsend").disabled=true;
  try{const j=await api("/api/faucet",{address:$("faddr").value,amount:+$("famt").value});$("fres").textContent="Отправлено "+AYV(j.amount)+" AYV, транзакция "+j.txhash.slice(0,16)+"…";}
  catch(e){$("fres").textContent="Ошибка: "+e.message;} $("fsend").disabled=false;};
$("kconnect").onclick=async()=>{
  const out=$("kres");
  if(!window.keplr){out.textContent="Расширение Keplr не найдено. Установите его в браузер с keplr.app и обновите страницу.";return;}
  const o=location.origin, id=($("netid").textContent||"ayvia-testnet-1");
  const cur={coinDenom:"AYV",coinMinimalDenom:"uayv",coinDecimals:6};
  try{
    await window.keplr.experimentalSuggestChain({chainId:id,chainName:"AYVIA Testnet",rpc:o+"/rpc",rest:o+"/rest",
      bip44:{coinType:118},bech32Config:{bech32PrefixAccAddr:"ayv",bech32PrefixAccPub:"ayvpub",bech32PrefixValAddr:"ayvvaloper",
      bech32PrefixValPub:"ayvvaloperpub",bech32PrefixConsAddr:"ayvvalcons",bech32PrefixConsPub:"ayvvalconspub"},
      currencies:[cur],feeCurrencies:[{...cur,gasPriceStep:{low:0.0025,average:0.005,high:0.01}}],stakeCurrency:cur});
    await window.keplr.enable(id); const k=await window.keplr.getKey(id);
    const r=await fetch("/rest/cosmos/bank/v1beta1/balances/"+k.bech32Address+"/by_denom?denom=uayv").then(x=>x.json());
    out.textContent="Подключено: "+k.bech32Address+" — баланс "+AYV(+r.balance.amount)+" AYV. Пополнить можно краном выше.";
    $("faddr").value=k.bech32Address;
  }catch(e){out.textContent="Не удалось подключить: "+e.message;}
};
refresh(true); setInterval(()=>refresh(false),5000); setInterval(()=>refresh(true),20000);
</script></body></html>"""


def main():
    if len(KEY) < 12:
        sys.exit('Задайте пароль панели от 12 символов:\n  PANEL_KEY="длинный-пароль" python3 panel/panel.py')
    print(f"AYVIA panel: http://{HOST}:{PORT}  (BASE={BASE}, nodes={NODES})")
    threading.Thread(target=bots_resume, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
