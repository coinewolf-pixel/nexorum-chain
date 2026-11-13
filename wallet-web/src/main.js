// AYVIA network page: wallet, balance, transfers, staking, history, charts.
// Keys never leave the browser. Built with esbuild (see build.mjs).
import {
  AYVIA_TESTNET, withEndpoints, createWallet, walletFromMnemonic, connect, connectBrowserWallet,
  AyviaReader, toAyv, fromAyv, isAddress,
} from "@ayvia/sdk";
import QRCode from "qrcode";

const $ = (id) => document.getElementById(id);
const SYMBOL = AYVIA_TESTNET.symbol;
const STORE = { net: "ayv_net", wallet: "ayv_wallet", kind: "ayv_kind" };
const fmt = (u) => Number(toAyv(u)).toLocaleString("ru-RU", { maximumFractionDigits: 6 });
const short = (s) => (s ? s.slice(0, 10) + "…" + s.slice(-6) : "");
const ls = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  del: (k) => { try { localStorage.removeItem(k); } catch { /* private mode */ } },
};

// ------------------------------------------------------------------ network settings

function netSettings() {
  const saved = JSON.parse(ls.get(STORE.net) || "null");
  const def = window.AYVIA_NETWORK || {};
  return { rpc: saved?.rpc || def.rpc || AYVIA_TESTNET.rpc, rest: saved?.rest || def.rest || AYVIA_TESTNET.rest };
}
let NET = withEndpoints(netSettings().rpc, netSettings().rest);
let reader = null;
let client = null;      // signing client when a wallet is open
let address = null;

function setMsg(id, text, kind) {
  const el = $(id);
  el.textContent = text || "";
  el.className = "msg" + (kind ? " " + kind : "");
}

async function rest(path) {
  const r = await fetch(NET.rest + path);
  if (!r.ok) throw new Error(`REST ${r.status}`);
  return r.json();
}
async function rpc(path) {
  const r = await fetch(NET.rpc + path);
  if (!r.ok) throw new Error(`RPC ${r.status}`);
  return (await r.json()).result;
}

// ------------------------------------------------------------------ encrypted local wallet

const enc = new TextEncoder();
const dec = new TextDecoder();
const b64 = (u8) => btoa(String.fromCharCode(...u8));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function deriveKey(password, salt) {
  const base = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 310000, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
async function saveEncrypted(mnemonic, password, addr) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(password, salt);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, enc.encode(mnemonic)));
  ls.set(STORE.wallet, JSON.stringify({ v: 1, salt: b64(salt), iv: b64(iv), ct: b64(ct), address: addr }));
}
async function loadEncrypted(password) {
  const w = JSON.parse(ls.get(STORE.wallet) || "null");
  if (!w) throw new Error("Кошелёк не найден");
  const key = await deriveKey(password, unb64(w.salt));
  try {
    return dec.decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(w.iv) }, key, unb64(w.ct)));
  } catch {
    throw new Error("Неверный пароль");
  }
}

// ------------------------------------------------------------------ connect / open

async function openWithSigner(signer, kind) {
  client = await connect({ signer, network: NET });
  address = client.address;
  ls.set(STORE.kind, kind);
  $("walletKind").textContent = { keplr: "Keplr", leap: "Leap", local: "Кошелёк в этом браузере" }[kind] || "Кошелёк";
  $("address").textContent = address;
  $("connectCard").classList.add("hidden");
  $("setupCard").classList.add("hidden");
  $("walletArea").classList.remove("hidden");
  $("qrBox").classList.add("hidden");
  await refreshWallet();
  loadValidators();
  loadHistory();
}

async function connectExtension(kind) {
  setMsg("connectMsg", "");
  const ext = kind === "leap" ? window.leap : window.keplr;
  if (!ext) {
    setMsg("connectMsg", `Расширение ${kind === "leap" ? "Leap" : "Keplr"} не найдено. Установите его в браузер и обновите страницу.`, "err");
    return;
  }
  try {
    const signer = await connectBrowserWallet(ext, NET);
    await openWithSigner(signer, kind);
  } catch (e) {
    setMsg("connectMsg", "Не удалось подключить: " + e.message, "err");
  }
}

function showConnect() {
  client?.disconnect?.();
  client = null;
  address = null;
  $("walletArea").classList.add("hidden");
  $("setupCard").classList.add("hidden");
  $("connectCard").classList.remove("hidden");
  $("unlockBox").classList.toggle("hidden", !ls.get(STORE.wallet));
}

let pendingMnemonic = null;
async function startCreate() {
  const w = await createWallet(NET);
  pendingMnemonic = w.mnemonic;
  $("setupTitle").textContent = "Новый кошелёк";
  $("createBox").classList.remove("hidden");
  $("importBox").classList.add("hidden");
  const box = $("words");
  box.textContent = "";
  w.mnemonic.split(" ").forEach((word, i) => {
    const s = document.createElement("span");
    const n = document.createElement("i");
    n.textContent = i + 1;
    s.append(n, word);
    box.append(s);
  });
  $("savedCheck").checked = false;
  showSetup();
}
function startImport() {
  pendingMnemonic = null;
  $("setupTitle").textContent = "Вход по секретной фразе";
  $("createBox").classList.add("hidden");
  $("importBox").classList.remove("hidden");
  $("importPhrase").value = "";
  showSetup();
}
function showSetup() {
  $("newPass").value = "";
  $("newPass2").value = "";
  setMsg("setupMsg", "");
  $("connectCard").classList.add("hidden");
  $("setupCard").classList.remove("hidden");
}

async function saveWallet() {
  const p1 = $("newPass").value, p2 = $("newPass2").value;
  const creating = !$("createBox").classList.contains("hidden");
  const phrase = creating ? pendingMnemonic : $("importPhrase").value.trim().toLowerCase().replace(/\s+/g, " ");
  if (creating && !$("savedCheck").checked) return setMsg("setupMsg", "Сначала запишите секретную фразу и отметьте галочку.", "err");
  if (!creating && ![12, 24].includes(phrase.split(" ").length)) return setMsg("setupMsg", "Фраза должна содержать 12 или 24 слова.", "err");
  if (p1.length < 8) return setMsg("setupMsg", "Пароль должен быть не короче 8 символов.", "err");
  if (p1 !== p2) return setMsg("setupMsg", "Пароли не совпадают.", "err");
  try {
    const signer = await walletFromMnemonic(phrase, NET);
    const [acc] = await signer.getAccounts();
    await saveEncrypted(phrase, p1, acc.address);
    pendingMnemonic = null;
    $("words").textContent = "";
    await openWithSigner(signer, "local");
  } catch (e) {
    setMsg("setupMsg", "Ошибка: " + e.message, "err");
  }
}

async function unlock() {
  setMsg("connectMsg", "Открываю…");
  try {
    const phrase = await loadEncrypted($("unlockPass").value);
    $("unlockPass").value = "";
    await openWithSigner(await walletFromMnemonic(phrase, NET), "local");
    setMsg("connectMsg", "");
  } catch (e) {
    setMsg("connectMsg", e.message, "err");
  }
}

// ------------------------------------------------------------------ wallet data

async function refreshWallet() {
  if (!client) return;
  try {
    const [bal, dels, rew] = await Promise.all([client.balance(address), client.delegations(address), client.rewards(address)]);
    $("balance").textContent = fmt(bal);
    $("staked").textContent = fmt(dels.reduce((s, d) => s + BigInt(d.amount), 0n));
    $("rewards").textContent = fmt(rew);
    renderDelegations(dels);
  } catch (e) {
    $("balance").textContent = "—";
  }
}

let validatorsCache = [];
async function loadValidators() {
  try {
    validatorsCache = await reader.validators();
    const box = $("validators");
    box.textContent = "";
    for (const v of validatorsCache) {
      const it = document.createElement("div");
      it.className = "item";
      const l = document.createElement("div");
      l.className = "l";
      const t = document.createElement("div");
      t.className = "t";
      t.textContent = `${v.moniker} ${v.jailed ? "(в тюрьме)" : ""}`;
      const s = document.createElement("div");
      s.className = "s";
      s.textContent = `${fmt(v.tokens)} ${SYMBOL} · комиссия ${(Number(v.commission) * 100).toFixed(0)}%`;
      l.append(t, s);
      const r = document.createElement("div");
      r.className = "row";
      const inp = document.createElement("input");
      inp.placeholder = SYMBOL;
      inp.style.width = "110px";
      inp.inputMode = "decimal";
      const b = document.createElement("button");
      b.className = "btn";
      b.textContent = "Застейкать";
      b.onclick = () => stakeAction("delegate", v.operator, inp.value, b);
      r.append(inp, b);
      it.append(l, r);
      box.append(it);
    }
  } catch (e) {
    $("validators").textContent = "Не удалось загрузить валидаторов: " + e.message;
  }
}

function renderDelegations(dels) {
  const box = $("myDelegations");
  box.textContent = "";
  if (!dels.length) {
    const d = document.createElement("div");
    d.className = "sub";
    d.textContent = "Пока нет. Выберите валидатора ниже.";
    box.append(d);
    return;
  }
  for (const d of dels) {
    const v = validatorsCache.find((x) => x.operator === d.validator);
    const it = document.createElement("div");
    it.className = "item";
    const l = document.createElement("div");
    l.className = "l";
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = `${v ? v.moniker : short(d.validator)}: ${fmt(d.amount)} ${SYMBOL}`;
    l.append(t);
    const r = document.createElement("div");
    r.className = "row";
    const inp = document.createElement("input");
    inp.placeholder = SYMBOL;
    inp.style.width = "110px";
    inp.inputMode = "decimal";
    const b = document.createElement("button");
    b.className = "btn ghost";
    b.textContent = "Вывести";
    b.onclick = () => stakeAction("undelegate", d.validator, inp.value, b);
    r.append(inp, b);
    it.append(l, r);
    box.append(it);
  }
}

async function stakeAction(kind, validator, amount, btn) {
  amount = String(amount || "").trim().replace(",", ".");
  try {
    fromAyv(amount);
    if (Number(amount) <= 0) throw new Error();
  } catch {
    return setMsg("stakeMsg", "Введите сумму, например 10 или 2.5", "err");
  }
  btn.disabled = true;
  setMsg("stakeMsg", "Подтвердите и подождите несколько секунд…");
  try {
    const r = kind === "delegate" ? await client.delegate(validator, amount) : await client.undelegate(validator, amount);
    setMsg("stakeMsg", (kind === "delegate" ? "Застейкано " : "Вывод начат: ") + amount + " " + SYMBOL + " (блок " + r.height + ")", "ok");
    await refreshWallet();
    loadHistory();
  } catch (e) {
    setMsg("stakeMsg", "Ошибка: " + e.message, "err");
  }
  btn.disabled = false;
}

async function claimAll() {
  const dels = await client.delegations(address);
  if (!dels.length) return setMsg("stakeMsg", "Нет делегирований — нечего забирать.", "err");
  $("btnClaim").disabled = true;
  setMsg("stakeMsg", "Забираю награды…");
  try {
    for (const d of dels) await client.claimRewards(d.validator);
    setMsg("stakeMsg", "Награды зачислены на баланс.", "ok");
    await refreshWallet();
    loadHistory();
  } catch (e) {
    setMsg("stakeMsg", "Ошибка: " + e.message, "err");
  }
  $("btnClaim").disabled = false;
}

async function send() {
  const to = $("sendTo").value.trim();
  const amount = $("sendAmt").value.trim().replace(",", ".");
  if (!isAddress(to, NET)) return setMsg("sendMsg", `Адрес должен начинаться с ${NET.prefix}1`, "err");
  try {
    fromAyv(amount);
    if (Number(amount) <= 0) throw new Error();
  } catch {
    return setMsg("sendMsg", "Введите сумму, например 10 или 2.5", "err");
  }
  $("btnSend").disabled = true;
  setMsg("sendMsg", "Подтвердите и подождите несколько секунд…");
  try {
    const r = await client.send(to, amount, $("sendMemo").value.trim());
    setMsg("sendMsg", `Отправлено ${amount} ${SYMBOL}. Транзакция ${short(r.transactionHash)} в блоке ${r.height}.`, "ok");
    $("sendAmt").value = "";
    $("sendMemo").value = "";
    await refreshWallet();
    loadHistory();
  } catch (e) {
    setMsg("sendMsg", "Ошибка: " + e.message.replace(/^.*insufficient funds.*$/i, "недостаточно средств"), "err");
  }
  $("btnSend").disabled = false;
}

// ------------------------------------------------------------------ history + balance chart

function balanceDelta(tx, addr) {
  // coin_spent / coin_received cover every balance change inside a tx: transfers, fees, staking, rewards
  let d = 0n;
  for (const ev of tx.events || []) {
    if (ev.type !== "coin_spent" && ev.type !== "coin_received") continue;
    const a = Object.fromEntries(ev.attributes.map((x) => [x.key, x.value]));
    const who = ev.type === "coin_spent" ? a.spender : a.receiver;
    if (who !== addr || !a.amount) continue;
    for (const part of a.amount.split(",")) {
      const m = part.match(/^(\d+)(.+)$/);
      if (m && m[2] === NET.denom) d += (ev.type === "coin_received" ? 1n : -1n) * BigInt(m[1]);
    }
  }
  return d;
}

function txLabel(tx, addr) {
  const msg = tx.tx?.body?.messages?.[0] || {};
  const t = (msg["@type"] || "").split(".").pop();
  if (t === "MsgSend") return msg.from_address === addr ? `Отправка → ${short(msg.to_address)}` : `Получено от ${short(msg.from_address)}`;
  if (t === "MsgMultiSend") return "Получено (мультиперевод)";
  if (t === "MsgDelegate") return "Стейкинг";
  if (t === "MsgUndelegate") return "Вывод из стейкинга";
  if (t === "MsgWithdrawDelegatorReward") return "Награды за стейкинг (за вычетом комиссии)";
  return t || "Транзакция";
}

async function loadHistory() {
  if (!address) return;
  const box = $("history");
  try {
    const q = (s) => `/cosmos/tx/v1beta1/txs?query=${encodeURIComponent(s)}&order_by=ORDER_BY_DESC&page=1&limit=50`;
    const [a, b] = await Promise.all([rest(q(`message.sender='${address}'`)), rest(q(`transfer.recipient='${address}'`))]);
    const seen = new Map();
    for (const t of [...(a.tx_responses || []), ...(b.tx_responses || [])]) seen.set(t.txhash, t);
    const txs = [...seen.values()].sort((x, y) => Number(y.height) - Number(x.height));
    box.textContent = "";
    if (!txs.length) {
      const d = document.createElement("div");
      d.className = "sub";
      d.textContent = "Транзакций пока нет.";
      box.append(d);
    }
    for (const t of txs) {
      const delta = balanceDelta(t, address);
      const it = document.createElement("div");
      it.className = "item";
      const l = document.createElement("div");
      l.className = "l";
      const tt = document.createElement("div");
      tt.className = "t";
      tt.textContent = txLabel(t, address) + (t.code ? " — ошибка" : "");
      const s = document.createElement("div");
      s.className = "s";
      s.textContent = `${new Date(t.timestamp).toLocaleString("ru-RU")} · блок ${t.height} · ${short(t.txhash)}`;
      l.append(tt, s);
      const amt = document.createElement("div");
      amt.className = "amt " + (delta >= 0n ? "in" : "out");
      amt.textContent = (delta >= 0n ? "+" : "") + fmt(delta) + " " + SYMBOL;
      it.append(l, amt);
      box.append(it);
    }
    // balance chart: walk back from the current balance through the transactions
    let bal = BigInt(await client.balance(address));
    const pts = [{ x: Date.now(), y: bal }];
    for (const t of txs) {
      pts.push({ x: new Date(t.timestamp).getTime(), y: bal });
      bal -= balanceDelta(t, address);
      pts.push({ x: new Date(t.timestamp).getTime() - 1, y: bal });
    }
    pts.reverse();
    lineChart($("chartBalance"), pts.map((p) => ({ x: p.x, y: Number(toAyv(p.y)) })), { color: "#f5b642", unit: SYMBOL, step: true });
  } catch (e) {
    box.textContent = "Не удалось загрузить историю: " + e.message;
  }
}

// ------------------------------------------------------------------ charts (plain SVG)

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function niceNum(v) {
  return Math.abs(v) >= 1000 ? v.toLocaleString("ru-RU", { maximumFractionDigits: 0 }) : v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

function lineChart(host, pts, { color = "#8b5cf6", unit = "", step = false } = {}) {
  host.textContent = "";
  if (pts.length < 2) {
    host.textContent = "Пока мало данных для графика";
    return;
  }
  const W = 600, H = 180, P = 34;
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || x0 + 1;
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const X = (x) => P + ((x - x0) / (x1 - x0 || 1)) * (W - P - 8);
  const Y = (y) => H - 22 - ((y - y0) / (y1 - y0)) * (H - 34);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  for (const v of [y0, (y0 + y1) / 2, y1]) {
    svg.append(svgEl("line", { x1: P, x2: W - 8, y1: Y(v), y2: Y(v), stroke: "#2a2058", "stroke-width": 1 }));
    const t = svgEl("text", { x: 2, y: Y(v) + 4, fill: "#9a90c4", "font-size": 10 });
    t.textContent = niceNum(v);
    svg.append(t);
  }
  let d = "";
  pts.forEach((p, i) => {
    if (i && step) d += ` L${X(p.x)},${Y(pts[i - 1].y)}`;
    d += `${i ? " L" : "M"}${X(p.x)},${Y(p.y)}`;
  });
  svg.append(svgEl("path", { d: `${d} L${X(x1)},${H - 22} L${X(x0)},${H - 22} Z`, fill: color, opacity: 0.12 }));
  svg.append(svgEl("path", { d, fill: "none", stroke: color, "stroke-width": 2.5, "stroke-linejoin": "round" }));
  const last = svgEl("text", { x: W - 10, y: 14, fill: color, "font-size": 12, "text-anchor": "end" });
  last.textContent = niceNum(ys[ys.length - 1]) + (unit ? " " + unit : "");
  svg.append(last);
  host.append(svg);
}

function barChart(host, values, { color = "#8b5cf6" } = {}) {
  host.textContent = "";
  if (!values.length) {
    host.textContent = "Нет данных";
    return;
  }
  const W = 600, H = 180, P = 34, max = Math.max(1, ...values);
  const bw = (W - P - 8) / values.length;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  for (const v of [0, max]) {
    const y = H - 22 - (v / max) * (H - 34);
    svg.append(svgEl("line", { x1: P, x2: W - 8, y1: y, y2: y, stroke: "#2a2058", "stroke-width": 1 }));
    const t = svgEl("text", { x: 2, y: y + 4, fill: "#9a90c4", "font-size": 10 });
    t.textContent = String(v);
    svg.append(t);
  }
  values.forEach((v, i) => {
    const h = (v / max) * (H - 34);
    svg.append(svgEl("rect", { x: P + i * bw + 1, y: H - 22 - h, width: Math.max(1, bw - 2), height: Math.max(v ? 2 : 0, h), rx: 2, fill: color }));
  });
  host.append(svg);
}

// ------------------------------------------------------------------ network status

async function refreshNetwork() {
  try {
    const st = await rpc("/status");
    const h = Number(st.sync_info.latest_block_height);
    $("netDot").className = "dot ok";
    $("netState").textContent = st.node_info.network;
    $("netHeight").textContent = h.toLocaleString("ru-RU");
    $("netline").textContent = `${st.node_info.network} · ${NET.rpc.replace(/^https?:\/\//, "").replace(/\/rpc$/, "")}`;
    // last 60 blocks (the RPC returns at most 20 per call)
    const metas = [];
    for (let top = h; top > Math.max(0, h - 60); top -= 20) {
      const r = await rpc(`/blockchain?minHeight=${Math.max(1, top - 19)}&maxHeight=${top}`);
      metas.push(...r.block_metas);
    }
    metas.sort((a, b) => Number(a.header.height) - Number(b.header.height));
    barChart($("chartActivity"), metas.map((m) => Number(m.num_txs)));
    const times = metas.map((m) => new Date(m.header.time).getTime());
    const gaps = times.slice(1).map((t, i) => ({ x: Number(metas[i + 1].header.height), y: (t - times[i]) / 1000 }));
    lineChart($("chartBlockTime"), gaps, { color: "#5be59a", unit: "с" });
    if (gaps.length) $("netBlockTime").textContent = (gaps.reduce((s, g) => s + g.y, 0) / gaps.length).toFixed(1) + " с";
    const [pool, supply, vals] = await Promise.all([
      rest("/cosmos/staking/v1beta1/pool"),
      rest(`/cosmos/bank/v1beta1/supply/by_denom?denom=${NET.denom}`),
      rest("/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED"),
    ]);
    const bonded = BigInt(pool.pool.bonded_tokens), total = BigInt(supply.amount.amount);
    const ratio = total ? Number((bonded * 10000n) / total) / 100 : 0;
    $("stakeRatio").textContent = ratio.toFixed(2) + " %";
    $("stakeBar").style.width = Math.min(100, ratio) + "%";
    $("bonded").textContent = fmt(bonded);
    $("supply").textContent = fmt(total);
    $("netVals").textContent = vals.validators.length;
  } catch (e) {
    $("netDot").className = "dot bad";
    $("netState").textContent = "сеть недоступна";
    $("netline").textContent = "Проверьте адреса сети в настройках (⚙)";
  }
}

// ------------------------------------------------------------------ settings

function openSettings() {
  const s = netSettings();
  $("setRpc").value = s.rpc;
  $("setRest").value = s.rest;
  setMsg("settingsMsg", "");
  $("settings").classList.remove("hidden");
}
async function saveSettings() {
  const r = $("setRpc").value.trim().replace(/\/$/, ""), s = $("setRest").value.trim().replace(/\/$/, "");
  if (!/^https?:\/\//.test(r) || !/^https?:\/\//.test(s)) return setMsg("settingsMsg", "Адреса должны начинаться с https://", "err");
  ls.set(STORE.net, JSON.stringify({ rpc: r, rest: s }));
  location.reload();
}

// ------------------------------------------------------------------ start

function wire() {
  $("btnKeplr").onclick = () => connectExtension("keplr");
  $("btnLeap").onclick = () => connectExtension("leap");
  $("btnCreate").onclick = startCreate;
  $("btnImport").onclick = startImport;
  $("btnUnlock").onclick = unlock;
  $("unlockPass").onkeydown = (e) => { if (e.key === "Enter") unlock(); };
  $("btnForget").onclick = () => {
    if (confirm("Удалить кошелёк из этого браузера? Без секретной фразы восстановить его будет невозможно.")) {
      ls.del(STORE.wallet);
      ls.del(STORE.kind);
      showConnect();
    }
  };
  $("btnSaveWallet").onclick = saveWallet;
  $("btnCancelSetup").onclick = () => { pendingMnemonic = null; $("words").textContent = ""; showConnect(); };
  $("btnLogout").onclick = () => { ls.del(STORE.kind); showConnect(); };
  $("btnCopy").onclick = async () => {
    try { await navigator.clipboard.writeText(address); $("btnCopy").textContent = "Скопировано ✓"; } catch { /* no clipboard */ }
    setTimeout(() => { $("btnCopy").textContent = "Копировать адрес"; }, 1500);
  };
  $("btnQr").onclick = async () => {
    $("qrImg").src = await QRCode.toDataURL(address, { margin: 1, width: 360 });
    $("qrBox").classList.toggle("hidden");
  };
  $("btnSend").onclick = send;
  $("btnClaim").onclick = claimAll;
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
      for (const t of ["send", "stake", "history"]) $("tab-" + t).classList.toggle("hidden", t !== b.dataset.tab);
    };
  });
  $("openSettings").onclick = openSettings;
  $("btnCloseSettings").onclick = () => $("settings").classList.add("hidden");
  $("btnSaveSettings").onclick = saveSettings;
  $("btnResetSettings").onclick = () => { ls.del(STORE.net); location.reload(); };
}

async function main() {
  wire();
  showConnect();
  try {
    reader = await AyviaReader.connect(NET);
  } catch {
    /* network unavailable: status shows it; wallet buttons still work once settings are fixed */
  }
  refreshNetwork();
  setInterval(refreshNetwork, 15000);
  setInterval(refreshWallet, 10000);
  const kind = ls.get(STORE.kind);
  if (kind === "keplr" || kind === "leap") connectExtension(kind);
}

main();
