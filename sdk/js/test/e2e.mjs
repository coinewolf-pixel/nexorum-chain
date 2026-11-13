// End-to-end test of @nexorum/sdk against a running NEXORUM testnet.
//
//   FAUCET_KEY=$(nexorumd keys export faucet --unarmored-hex --unsafe --keyring-backend test --home $BASE/client -y) \
//     npm test
//
// RPC defaults to http://127.0.0.1:26657 (override with RPC=...).
import assert from "node:assert/strict";
import {
  NEXORUM_TESTNET, withEndpoints, createWallet, connect, NexorumReader,
  fromNexo, toNexo, isAddress, keplrChainInfo,
} from "../dist/index.js";

const net = withEndpoints(process.env.RPC ?? NEXORUM_TESTNET.rpc, process.env.REST ?? NEXORUM_TESTNET.rest);
const faucetKey = process.env.FAUCET_KEY;
if (!faucetKey) {
  console.error("Set FAUCET_KEY (see the comment at the top of this file)");
  process.exit(1);
}
let passed = 0;
const ok = (name) => { passed++; console.log("  ok  " + name); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- amounts and helpers (no network)
assert.equal(fromNexo("12.5"), "12500000");
assert.equal(fromNexo("0.000001"), "1");
assert.equal(toNexo("12500000"), "12.5");
assert.equal(toNexo("1000000"), "1");
assert.throws(() => fromNexo("1.0000001"), /decimals/);
assert.throws(() => fromNexo("-1"), /Invalid/);
ok("amount conversion");
assert.equal(keplrChainInfo(net).bech32Config.bech32PrefixAccAddr, "nexo");
assert.equal(keplrChainInfo(net).currencies[0].coinMinimalDenom, "unexo");
ok("Keplr chain info");

// --- read-only
const reader = await NexorumReader.connect(net);
assert.equal(await reader.chainId(), "nexorum-testnet-1");
const h = await reader.height();
assert.ok(h > 0);
const vals = await reader.validators();
assert.ok(vals.length >= 1 && vals[0].operator.startsWith("nexovaloper1"));
ok(`reader: chain ${await reader.chainId()}, height ${h}, ${vals.length} validators, top ${vals[0].moniker} (${toNexo(vals[0].tokens)} NEXO)`);

// --- new wallet
const w = await createWallet(net);
assert.equal(w.mnemonic.split(" ").length, 24);
assert.ok(isAddress(w.address, net));
assert.equal(await reader.balance(w.address), "0");
ok(`createWallet: ${w.address}`);

// --- faucet sends 25 NEXO to the new wallet
const faucet = await connect({ privateKey: faucetKey, network: net });
const r1 = await faucet.send(w.address, "25", "sdk e2e");
assert.equal(r1.code, 0);
assert.equal(await reader.balance(w.address), fromNexo("25"));
ok(`send: faucet -> new wallet 25 NEXO (block ${r1.height}, gas ${r1.gasUsed})`);

// --- new wallet sends 1.5 back and pays the fee itself
const user = await connect({ mnemonic: w.mnemonic, network: net });
assert.equal(user.address, w.address);
const r2 = await user.send(faucet.address, "1.5");
const after = BigInt(await reader.balance(w.address));
const fee = BigInt(fromNexo("23.5")) - after;
assert.ok(fee > 0n && fee < 10000n, `unexpected fee ${fee}`);
ok(`send back 1.5 NEXO, fee ${toNexo(fee)} NEXO`);
const tx = await reader.tx(r2.transactionHash);
assert.equal(tx?.code, 0);
ok("tx lookup by hash");

// --- staking
const v = vals[0].operator;
await user.delegate(v, "10");
const del = await user.delegations(w.address);
assert.equal(del.find((d) => d.validator === v)?.amount, fromNexo("10"));
ok(`delegate 10 NEXO to ${vals[0].moniker}`);
await sleep(6000);
const rew = await user.rewards(w.address);
assert.ok(BigInt(rew) > 0n, "rewards should accrue after a few blocks");
ok(`rewards after ~3 blocks: ${toNexo(rew)} NEXO`);
const before = BigInt(await reader.balance(w.address));
await user.claimRewards(v);
assert.ok(BigInt(await reader.balance(w.address)) > before - 10000n);
ok("claimRewards");
await user.undelegate(v, "4");
assert.equal((await user.delegations(w.address)).find((d) => d.validator === v)?.amount, fromNexo("6"));
ok("undelegate 4 NEXO (6 remain staked)");

// --- errors
await assert.rejects(user.send("cosmos1notours", "1"), /Not a nexo address/);
await assert.rejects(user.send(faucet.address, "100000"), /insufficient funds/i);
ok("errors: wrong address prefix, insufficient funds");

reader.disconnect(); faucet.disconnect(); user.disconnect();
console.log(`\nAll ${passed} checks passed.`);
