#!/usr/bin/env python3
"""
NEXORUM testnet load bots.

Test accounts bot0..botN send random amounts of TEST NEXO to each other to check
throughput, fees and stability of the test network. Only for the testnet:
the bots use the unencrypted "test" keyring created by scripts/testnet.sh.

  python3 scripts/loadbots.py --duration 60 --rate 2
  python3 scripts/loadbots.py --duration 600 --rate 5 --bots 10 --node tcp://127.0.0.1:26657

At the end it prints a report: sent / accepted / rejected, transactions that
actually landed in blocks, effective TPS, fees paid, and a balance check that
the bots' total decreased by exactly the fees of their included transactions.
"""
import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DENOM = "unexo"


def default_bin():
    local = os.path.join(ROOT, "build", "nexorumd")
    return local if os.access(local, os.X_OK) else "nexorumd"


class Chain:
    def __init__(self, args):
        self.bin, self.home, self.node, self.chain_id = args.bin, args.home, args.node, args.chain_id
        self.rpc = args.node.replace("tcp://", "http://")
        self.fee = args.fee

    def cli(self, *a, timeout=60):
        r = subprocess.run([self.bin, *a, "--home", self.home, "--keyring-backend", "test"],
                           capture_output=True, text=True, timeout=timeout)
        return r

    def address(self, name):
        r = self.cli("keys", "show", name, "-a")
        if r.returncode != 0:
            sys.exit(f"key {name} not found in {self.home}: {r.stderr.strip()}")
        return r.stdout.strip()

    def has_key(self, name):
        return self.cli("keys", "show", name, "-a").returncode == 0

    def ensure_bots(self, names, fund_unexo):
        """Create missing bot keys; fund every bot that is new or almost empty, in one multi-send."""
        missing = [n for n in names if not self.has_key(n)]
        if missing:
            print(f"creating {len(missing)} new bots ({missing[0]}..{missing[-1]})")
            for n in missing:
                r = self.cli("keys", "add", n)
                if r.returncode != 0:
                    sys.exit(f"cannot create key {n}: {r.stderr.strip()}")
        low = [n for n in names if self.balance(self.address(n)) < 100_000]  # < 0.1 NEXO: cannot pay fees
        if not low:
            return
        print(f"funding {len(low)} bots from the faucet with {fund_unexo / 1e6:,.0f} NEXO each")
        low_addrs = [self.address(n) for n in low]
        r = self.cli("tx", "bank", "multi-send", "faucet", *low_addrs, f"{fund_unexo}{DENOM}",
                     "--chain-id", self.chain_id, "--node", self.node, "--fees", "5000unexo",
                     "--gas", "auto", "--gas-adjustment", "1.5", "-y", "-o", "json")
        try:
            d = json.loads(r.stdout)
        except json.JSONDecodeError:
            sys.exit(f"faucet transfer failed: {(r.stderr or r.stdout).strip()[-300:]}")
        if d.get("code", 1) != 0:
            sys.exit(f"faucet transfer rejected: {d.get('raw_log', '')[:300]}")
        for _ in range(30):  # wait until the funds are in a block
            time.sleep(1)
            if self.balance(low_addrs[-1]) >= 100_000:
                return
        sys.exit("faucet transfer did not land in a block within 30 s")

    def balance(self, addr):
        r = subprocess.run([self.bin, "q", "bank", "balance", addr, DENOM, "--node", self.node, "-o", "json"],
                           capture_output=True, text=True, timeout=30)
        return int(json.loads(r.stdout)["balance"]["amount"])

    def height(self):
        s = json.load(urllib.request.urlopen(f"{self.rpc}/status", timeout=5))
        return int(s["result"]["sync_info"]["latest_block_height"])

    def send(self, frm, to_addr, amount):
        # unordered transactions: a bot can have several txs in flight without sequence conflicts
        r = self.cli("tx", "bank", "send", frm, to_addr, f"{amount}{DENOM}",
                     "--chain-id", self.chain_id, "--node", self.node, "--fees", self.fee,
                     "--unordered", "--timeout-duration", "60s", "-y", "-o", "json")
        try:
            d = json.loads(r.stdout)
            return d.get("code", 1), d.get("txhash"), d.get("raw_log", "")
        except json.JSONDecodeError:
            return -1, None, (r.stderr or r.stdout).strip()[-200:]

    def tx(self, txhash):
        try:
            d = json.load(urllib.request.urlopen(f"{self.rpc}/tx?hash=0x{txhash}", timeout=5))
            return d.get("result")
        except Exception:
            return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--duration", type=int, default=60, help="seconds to run")
    p.add_argument("--rate", type=float, default=2.0, help="transactions per second (total, target)")
    p.add_argument("--bots", type=int, default=10)
    p.add_argument("--home", default=os.environ.get("CLIENT_HOME", os.path.join(ROOT, ".testnet", "client")))
    p.add_argument("--node", default="tcp://127.0.0.1:26657")
    p.add_argument("--chain-id", default="nexorum-testnet-1")
    p.add_argument("--fee", default="500unexo")
    p.add_argument("--max-amount", type=int, default=1_000_000, help="max unexo per transfer (1 NEXO = 1e6)")
    p.add_argument("--bin", default=default_bin())
    p.add_argument("--fund", type=int, default=10_000_000_000,
                   help="unexo the faucet gives each newly created bot (default 10,000 NEXO)")
    args = p.parse_args()

    chain = Chain(args)
    names = [f"bot{i}" for i in range(args.bots)]
    chain.ensure_bots(names, args.fund)
    addrs = {n: chain.address(n) for n in names}
    before = {n: chain.balance(a) for n, a in addrs.items()}
    start_h = chain.height()
    print(f"{len(names)} bots, total {sum(before.values()) / 1e6:,.6f} NEXO, start height {start_h}")
    print(f"running {args.duration}s at ~{args.rate} tx/s ...")

    lock = threading.Lock()
    stats = {"sent": 0, "accepted": 0, "rejected": 0}
    errors = {}
    hashes = []
    stop = time.time() + args.duration
    interval = len(names) / args.rate  # each bot sends every `interval` seconds

    def bot(name):
        time.sleep(random.random() * interval)
        while time.time() < stop:
            t0 = time.time()
            to = random.choice([n for n in names if n != name])
            amount = random.randint(1, args.max_amount)
            code, h, log = chain.send(name, addrs[to], amount)
            with lock:
                stats["sent"] += 1
                if code == 0:
                    stats["accepted"] += 1
                    hashes.append(h)
                else:
                    stats["rejected"] += 1
                    key = (log or "unknown")[:80]
                    errors[key] = errors.get(key, 0) + 1
            time.sleep(max(0.0, interval - (time.time() - t0)))

    threads = [threading.Thread(target=bot, args=(n,), daemon=True) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print("waiting for the last transactions to land in blocks ...")
    time.sleep(8)
    end_h = chain.height()

    included, failed_in_block, fees = 0, 0, 0
    fee_amount = int("".join(c for c in args.fee if c.isdigit()))
    for h in hashes:
        r = chain.tx(h)
        if r is None:
            continue
        # fees are charged even if the message itself fails inside the block
        fees += fee_amount
        if r["tx_result"].get("code", 0) == 0:
            included += 1
        else:
            failed_in_block += 1

    after = {n: chain.balance(a) for n, a in addrs.items()}
    diff = sum(before.values()) - sum(after.values())
    blocks = max(1, end_h - start_h)

    print("\n=== Load test report ===")
    print(f"blocks:               {start_h} -> {end_h} ({blocks} blocks)")
    print(f"sent:                 {stats['sent']}")
    print(f"accepted to mempool:  {stats['accepted']}")
    print(f"rejected:             {stats['rejected']}")
    for e, c in sorted(errors.items(), key=lambda x: -x[1])[:5]:
        print(f"   {c} x {e}")
    print(f"included OK in blocks:{included:>6}")
    print(f"failed inside block:  {failed_in_block}")
    print(f"effective TPS:        {included / args.duration:.2f}")
    print(f"tx per block (avg):   {included / blocks:.2f}")
    print(f"fees paid:            {fees / 1e6:.6f} NEXO")
    ok = diff == fees
    print(f"balance check:        bots lost {diff / 1e6:.6f} NEXO, fees {fees / 1e6:.6f} NEXO -> "
          f"{'OK, no NEXO lost or created' if ok else 'MISMATCH'}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
