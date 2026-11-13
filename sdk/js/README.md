# @nexorum/sdk

JavaScript / TypeScript SDK для блокчейна NEXORUM: кошельки, балансы, переводы, стейкинг,
подключение Keplr и Leap. Работает в Node.js и в браузере. Основан на CosmJS.

Проверено на тестовой сети `nexorum-testnet-1` сквозным тестом (`test/e2e.mjs`): создание
кошелька, переводы в обе стороны, стейкинг, награды, вывод из стейкинга, ошибки.

## Установка

Пока пакет не опубликован в npm, ставится из репозитория:

```bash
cd sdk/js && npm install && npm run build
# в своём проекте:
npm install /путь/к/nexorum-chain/sdk/js
```

## Быстрый старт (Node.js)

```js
import { NEXORUM_TESTNET, withEndpoints, createWallet, connect, NexorumReader, toNexo } from "@nexorum/sdk";

// свои публичные адреса сети (по умолчанию — локальный узел)
const net = withEndpoints("https://rpc.example.com", "https://api.example.com");

// новый кошелёк: фразу показать пользователю один раз, никуда не отправлять
const { mnemonic, address } = await createWallet(net);

// только чтение
const reader = await NexorumReader.connect(net);
console.log(toNexo(await reader.balance(address)), "NEXO");
console.log(await reader.validators());

// подпись и отправка
const client = await connect({ mnemonic, network: net });
await client.send("nexo1...", "12.5");            // перевести 12.5 NEXO
await client.delegate("nexovaloper1...", "100");  // застейкать
console.log(toNexo(await client.rewards(address)));
await client.claimRewards("nexovaloper1...");
```

Суммы задаются в NEXO строкой (`"12.5"`), балансы возвращаются в `unexo` строкой —
`toNexo()` / `fromNexo()` переводят точно, без ошибок округления.

## В браузере с Keplr или Leap

```js
import { withEndpoints, connectBrowserWallet, connect } from "@nexorum/sdk";

const net = withEndpoints("https://rpc.example.com", "https://api.example.com");
const signer = await connectBrowserWallet(window.keplr ?? window.leap, net);  // кошелёк сам предложит добавить сеть
const client = await connect({ signer, network: net });
await client.send("nexo1...", "1");   // пользователь подтверждает в окне кошелька
```

Ключи остаются в кошельке пользователя, сайт их не видит.

## API

| Функция | Что делает |
|---|---|
| `NEXORUM_TESTNET`, `withEndpoints(rpc, rest)` | параметры сети |
| `createWallet()` | новый кошелёк: 24 слова и адрес |
| `walletFromMnemonic(phrase)`, `walletFromPrivateKey(hex)` | подписант из фразы или ключа |
| `connect({ mnemonic \| privateKey \| signer })` | клиент с подписью |
| `connectBrowserWallet(window.keplr)` | подключение Keplr / Leap |
| `keplrChainInfo()` | описание сети для кошельков |
| `NexorumReader.connect()` | клиент только для чтения |
| `.balance(addr)`, `.height()`, `.tx(hash)`, `.validators()`, `.delegations(addr)`, `.rewards(addr)` | чтение |
| `.send(to, nexo, memo?)`, `.delegate(val, nexo)`, `.undelegate(val, nexo)`, `.claimRewards(val)` | транзакции |
| `toNexo(units)`, `fromNexo(nexo)`, `isAddress(addr)` | вспомогательные |

## Проверка на своей сети

```bash
FAUCET_KEY=$(nexorumd keys export faucet --unarmored-hex --unsafe --keyring-backend test --home $BASE/client -y) npm test
```
