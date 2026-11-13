#!/usr/bin/env python3
"""
NEXORUM network monitor with an AI explanation of problems.

Watches every node over its RPC and raises an alert when:
  - a node stops responding;
  - the chain stops producing blocks;
  - a node falls behind the others;
  - a node loses its peers;
  - a validator stops signing blocks.
When the problem goes away, it reports the recovery.

Alerts are printed, appended to a log file and, if configured, sent to Telegram.
If the local AI (ai.py with Ollama) is available, it adds a short explanation of
what probably happened and what to check.

  python3 scripts/monitor.py                       # nodes from the local testnet (4 nodes)
  python3 scripts/monitor.py --nodes 127.0.0.1:26657,127.0.0.1:26667
  python3 scripts/monitor.py --once                # one check, print the state, exit

Telegram (optional):  TELEGRAM_BOT_TOKEN=...  TELEGRAM_CHAT_ID=...
Local AI (optional):  path to ai.py via AI_PY (default ~/ai.py), Ollama must be running.
"""
import argparse
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def rpc(node, path, timeout=4):
    with urllib.request.urlopen(f"http://{node}{path}", timeout=timeout) as r:
        return json.load(r)["result"]


def load_ai():
    path = os.environ.get("AI_PY", os.path.expanduser("~/ai.py"))
    if not os.path.isfile(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location("ai", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


class Notifier:
    def __init__(self, log_path, use_ai):
        self.log_path = log_path
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        self.ai = load_ai() if use_ai else None

    def telegram(self, text):
        if not (self.token and self.chat):
            return
        data = urllib.parse.urlencode({"chat_id": self.chat, "text": text[:4000]}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{self.token}/sendMessage", data=data, timeout=15)
        except Exception as e:
            print(f"  (telegram failed: {e})", file=sys.stderr)

    def emit(self, text):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}"
        print(line, flush=True)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        self.telegram(f"NEXORUM: {text}")

    def explain(self, problem, snapshot):
        """Ask the local model in the background: the alert itself is never delayed by it."""
        if not self.ai:
            return

        def run():
            prompt = (
                "Ты дежурный инженер блокчейна NEXORUM (Cosmos SDK + CometBFT, тестовая сеть из нескольких "
                "валидаторов на одном сервере). Произошла проблема:\n"
                f"{problem}\n\nСостояние узлов:\n{snapshot}\n\n"
                "Кратко, 3-5 пунктов: что скорее всего случилось и какие команды проверить "
                "(например scripts/testnet.sh status, логи в .testnet/logs/, systemctl). Без воды."
            )
            try:
                answer = self.ai.chat([{"role": "user", "content": prompt}]).strip()
                self.emit(f"AI-разбор «{problem[:60]}»:\n{answer}")
            except Exception as e:
                print(f"  (AI explanation failed: {e})", file=sys.stderr)

        threading.Thread(target=run, daemon=True).start()


class Monitor:
    def __init__(self, nodes, args, notifier):
        self.nodes = nodes
        self.args = args
        self.n = notifier
        self.active = {}          # problem key -> text
        self.last_height = None
        self.last_progress = time.time()
        self.val_names = {}       # validator hex address -> node name

    def check(self):
        state = {}
        for name, node in self.nodes.items():
            try:
                s = rpc(node, "/status")
                ni = rpc(node, "/net_info")
                state[name] = {
                    "up": True,
                    "height": int(s["sync_info"]["latest_block_height"]),
                    "catching_up": s["sync_info"]["catching_up"],
                    "peers": int(ni["n_peers"]),
                }
                addr = s["validator_info"]["address"]
                if int(s["validator_info"]["voting_power"]) > 0:
                    self.val_names[addr] = name
            except Exception as e:
                state[name] = {"up": False, "error": e.__class__.__name__}

        problems = {}
        up = {k: v for k, v in state.items() if v["up"]}
        for name, v in state.items():
            if not v["up"]:
                problems[f"down:{name}"] = f"узел {name} ({self.nodes[name]}) не отвечает"
            elif v["peers"] == 0 and len(self.nodes) > 1:
                problems[f"peers:{name}"] = f"у узла {name} нет соединений с другими узлами"

        if up:
            top = max(v["height"] for v in up.values())
            for name, v in up.items():
                if top - v["height"] > self.args.lag:
                    problems[f"lag:{name}"] = f"узел {name} отстаёт на {top - v['height']} блоков (высота {v['height']} из {top})"
            if self.last_height is None or top > self.last_height:
                self.last_height, self.last_progress = top, time.time()
            elif time.time() - self.last_progress > self.args.stall:
                problems["stall"] = (f"сеть не создаёт блоки уже {int(time.time() - self.last_progress)} с "
                                     f"(застряла на высоте {top})")
            problems.update(self.missed_signatures(self.nodes[next(iter(up))], top))
        else:
            problems["all_down"] = "не отвечает ни один узел"

        for key, text in problems.items():
            if key not in self.active:
                self.n.emit("ПРОБЛЕМА: " + text)
                self.n.explain(text, self.snapshot(state))
        for key in list(self.active):
            if key not in problems:
                self.n.emit("ИСПРАВЛЕНО: " + self.active[key])
        self.active = problems
        return state

    def missed_signatures(self, node, top):
        """Validators that did not sign the last few blocks."""
        if top < 3:
            return {}
        missed = {}
        try:
            vals = rpc(node, f"/validators?height={top - 1}")["validators"]
            window = range(max(2, top - self.args.sign_window + 1), top + 1)
            signed = {}
            for h in window:
                sigs = rpc(node, f"/commit?height={h}")["signed_header"]["commit"]["signatures"]
                for sg in sigs:
                    if sg.get("block_id_flag") == 2 and sg.get("validator_address"):
                        signed[sg["validator_address"]] = signed.get(sg["validator_address"], 0) + 1
            for v in vals:
                if signed.get(v["address"], 0) == 0:
                    who = self.val_names.get(v["address"], v["address"][:12])
                    missed[f"sign:{v['address']}"] = (f"валидатор {who} не подписал ни одного из последних "
                                                     f"{len(window)} блоков")
        except Exception:
            pass
        return missed

    @staticmethod
    def snapshot(state):
        return "\n".join(
            f"- {k}: " + (f"высота {v['height']}, соседей {v['peers']}, догоняет={v['catching_up']}"
                          if v["up"] else f"не отвечает ({v['error']})")
            for k, v in state.items()
        )


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nodes", default="", help="comma-separated host:rpcport (default: 4 local testnet nodes)")
    p.add_argument("--interval", type=int, default=10, help="seconds between checks")
    p.add_argument("--stall", type=int, default=30, help="alert if no new block for this many seconds")
    p.add_argument("--lag", type=int, default=5, help="alert if a node is this many blocks behind")
    p.add_argument("--sign-window", type=int, default=5, help="blocks to check for validator signatures")
    p.add_argument("--log", default=os.path.join(os.path.dirname(HERE), ".testnet", "monitor.log"))
    p.add_argument("--no-ai", action="store_true", help="do not ask the local AI for explanations")
    p.add_argument("--once", action="store_true", help="check once, print the state and exit")
    args = p.parse_args()

    if args.nodes:
        addrs = [a.strip() for a in args.nodes.split(",") if a.strip()]
    else:
        addrs = [f"127.0.0.1:{26657 + 10 * i}" for i in range(4)]
    nodes = {f"node{i}": a for i, a in enumerate(addrs)}
    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    notifier = Notifier(args.log, use_ai=not args.no_ai)
    mon = Monitor(nodes, args, notifier)

    if args.once:
        state = mon.check()
        print(Monitor.snapshot(state))
        print("problems:", "none" if not mon.active else "; ".join(mon.active.values()))
        sys.exit(1 if mon.active else 0)

    notifier.emit(f"мониторинг запущен: {len(nodes)} узлов, AI-разбор "
                  f"{'включён' if notifier.ai else 'выключен'}, Telegram "
                  f"{'включён' if notifier.token and notifier.chat else 'не настроен'}")
    while True:
        mon.check()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
