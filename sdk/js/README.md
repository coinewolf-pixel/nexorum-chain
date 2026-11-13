# @ayvia/sdk

JavaScript / TypeScript SDK для блокчейна AYVIA: кошельки, балансы, переводы, стейкинг,
подключение Keplr и Leap. Работает в Node.js и в браузере. Основан на CosmJS.

Проверено на тестовой сети `ayvia-testnet-1` сквозным тестом (`test/e2e.mjs`): создание
кошелька, переводы в обе стороны, стейкинг, награды, вывод из стейкинга, ошибки.

## Установка

Пока пакет не опубликован в npm, ставится из репозитория:

```bash
cd sdk/js && npm install && npm run build
# в своём проекте:
npm install /путь/к/ayvia-chain/sdk/js
```

## Быстрый старт (Node.js)

```js
import { AYVIA_TESTNET, withEndpoints, createWallet, connect, AyviaReader, toAyv } from "@ayvia/sdk";

// свои публичные адреса сети (по умолчанию — локальный узел)
const net = withEndpoints("https://rpc.example.com", "https://api.example.com");

// новый кошелёк: фразу показать пользователю один раз, никуда не отправлять
const { mnemonic, address } = await createWallet(net);

// только чтение
const reader = await AyviaReader.connect(net);
console.log(toAyv(await reader.balance(address)), "AYV");
console.log(await reader.validators());

// подпись и отправка
const client = await connect({ mnemonic, network: net });
await client.send("ayv1...", "12.5");            // перевести 12.5 AYV
await client.delegate("ayvvaloper1...", "100");  // застейкать
console.log(toAyv(await client.rewards(address)));
await client.claimRewards("ayvvaloper1...");
```

Суммы задаются в AYV строкой (`"12.5"`), балансы возвращаются в `uayv` строкой —
`toAyv()` / `fromAyv()` переводят точно, без ошибок округления.

## В браузере с Keplr или Leap

```js
import { withEndpoints, connectBrowserWallet, connect } from "@ayvia/sdk";

const net = withEndpoints("https://rpc.example.com", "https://api.example.com");
const signer = await connectBrowserWallet(window.keplr ?? window.leap, net);  // кошелёк сам предложит добавить сеть
const client = await connect({ signer, network: net });
await client.send("ayv1...", "1");   // пользователь подтверждает в окне кошелька
```

Ключи остаются в кошельке пользователя, сайт их не видит.

## API

| Функция | Что делает |
|---|---|
| `AYVIA_TESTNET`, `withEndpoints(rpc, rest)` | параметры сети |
| `createWallet()` | новый кошелёк: 24 слова и адрес |
| `walletFromMnemonic(phrase)`, `walletFromPrivateKey(hex)` | подписант из фразы или ключа |
| `connect({ mnemonic \| privateKey \| signer })` | клиент с подписью |
| `connectBrowserWallet(window.keplr)` | подключение Keplr / Leap |
| `keplrChainInfo()` | описание сети для кошельков |
| `AyviaReader.connect()` | клиент только для чтения |
| `.balance(addr)`, `.height()`, `.tx(hash)`, `.validators()`, `.delegations(addr)`, `.rewards(addr)` | чтение |
| `.send(to, ayv, memo?)`, `.delegate(val, ayv)`, `.undelegate(val, ayv)`, `.claimRewards(val)` | транзакции |
| `toAyv(units)`, `fromAyv(ayv)`, `isAddress(addr)` | вспомогательные |

## Проверка на своей сети

```bash
FAUCET_KEY=$(ayviad keys export faucet --unarmored-hex --unsafe --keyring-backend test --home $BASE/client -y) npm test
```
