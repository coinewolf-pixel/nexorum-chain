// End-to-end test of @ayvia/sdk against a running AYVIA testnet.
//
//   FAUCET_KEY=$(ayviad keys export faucet --unarmored-hex --unsafe --keyring-backend test --home $BASE/client -y) \
//     npm test
//
// RPC defaults to http://127.0.0.1:26657 (override with RPC=...).
import assert from "node:assert/strict";
import {
  AYVIA_TESTNET, withEndpoints, createWallet, connect, AyviaReader,
  fromAyv, toAyv, isAddress, keplrChainInfo,
} from "../dist/index.js";

const net = withEndpoints(process.env.RPC ?? AYVIA_TESTNET.rpc, process.env.REST ?? AYVIA_TESTNET.rest);
const faucetKey = process.env.FAUCET_KEY;
if (!faucetKey) {
  console.error("Set FAUCET_KEY (see the comment at the top of this file)");
  process.exit(1);
}
let passed = 0;
const ok = (name) => { passed++; console.log("  ok  " + name); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- amounts and helpers (no network)
assert.equal(fromAyv("12.5"), "12500000");
assert.equal(fromAyv("0.000001"), "1");
assert.equal(toAyv("12500000"), "12.5");
assert.equal(toAyv("1000000"), "1");
assert.throws(() => fromAyv("1.0000001"), /decimals/);
assert.throws(() => fromAyv("-1"), /Invalid/);
ok("amount conversion");
assert.equal(keplrChainInfo(net).bech32Config.bech32PrefixAccAddr, "ayv");
assert.equal(keplrChainInfo(net).currencies[0].coinMinimalDenom, "uayv");
ok("Keplr chain info");

// --- read-only
const reader = await AyviaReader.connect(net);
assert.equal(await reader.chainId(), "ayvia-testnet-1");
const h = await reader.height();
assert.ok(h > 0);
const vals = await reader.validators();
assert.ok(vals.length >= 1 && vals[0].operator.startsWith("ayvvaloper1"));
ok(`reader: chain ${await reader.chainId()}, height ${h}, ${vals.length} validators, top ${vals[0].moniker} (${toAyv(vals[0].tokens)} AYV)`);

// --- new wallet
const w = await createWallet(net);
assert.equal(w.mnemonic.split(" ").length, 24);
assert.ok(isAddress(w.address, net));
assert.equal(await reader.balance(w.address), "0");
ok(`createWallet: ${w.address}`);

// --- faucet sends 25 AYV to the new wallet
const faucet = await connect({ privateKey: faucetKey, network: net });
const r1 = await faucet.send(w.address, "25", "sdk e2e");
assert.equal(r1.code, 0);
assert.equal(await reader.balance(w.address), fromAyv("25"));
ok(`send: faucet -> new wallet 25 AYV (block ${r1.height}, gas ${r1.gasUsed})`);

// --- new wallet sends 1.5 back and pays the fee itself
const user = await connect({ mnemonic: w.mnemonic, network: net });
assert.equal(user.address, w.address);
const r2 = await user.send(faucet.address, "1.5");
const after = BigInt(await reader.balance(w.address));
const fee = BigInt(fromAyv("23.5")) - after;
assert.ok(fee > 0n && fee < 10000n, `unexpected fee ${fee}`);
ok(`send back 1.5 AYV, fee ${toAyv(fee)} AYV`);
const tx = await reader.tx(r2.transactionHash);
assert.equal(tx?.code, 0);
ok("tx lookup by hash");

// --- staking
const v = vals[0].operator;
await user.delegate(v, "10");
const del = await user.delegations(w.address);
assert.equal(del.find((d) => d.validator === v)?.amount, fromAyv("10"));
ok(`delegate 10 AYV to ${vals[0].moniker}`);
await sleep(6000);
const rew = await user.rewards(w.address);
assert.ok(BigInt(rew) > 0n, "rewards should accrue after a few blocks");
ok(`rewards after ~3 blocks: ${toAyv(rew)} AYV`);
const before = BigInt(await reader.balance(w.address));
await user.claimRewards(v);
assert.ok(BigInt(await reader.balance(w.address)) > before - 10000n);
ok("claimRewards");
await user.undelegate(v, "4");
assert.equal((await user.delegations(w.address)).find((d) => d.validator === v)?.amount, fromAyv("6"));
ok("undelegate 4 AYV (6 remain staked)");

// --- errors
await assert.rejects(user.send("cosmos1notours", "1"), /Not a ayv address/);
await assert.rejects(user.send(faucet.address, "100000"), /insufficient funds/i);
ok("errors: wrong address prefix, insufficient funds");

reader.disconnect(); faucet.disconnect(); user.disconnect();
console.log(`\nAll ${passed} checks passed.`);
