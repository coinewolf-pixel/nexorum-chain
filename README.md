# AYVIA — тестовая сеть

Собственный блокчейн AYVIA на **Cosmos SDK v0.53.8** и **CometBFT**: программа `ayviad`,
монета **AYV**, тестовая сеть из нескольких валидаторов, боты нагрузки и наблюдатель за сетью
с объяснением проблем через локальный AI.

> **Это тестовая сеть.** Тестовые AYV не имеют денежной стоимости. Ключи хранятся в
> незашифрованном виде (`--keyring-backend test`). Для основной сети (mainnet) нужны независимые
> валидаторы, аудит безопасности и утверждённая экономическая модель — см. «Что дальше».

## Что проверено

Всё ниже было запущено и проверено, а не только написано:

| Проверка | Результат |
|---|---|
| Сборка `ayviad` (Go 1.24, Cosmos SDK v0.53.8) | собирается, `go vet` без замечаний |
| Адреса | `ayv1...`, `ayvvaloper1...`, `ayvvalcons1...` |
| Сеть из 4 валидаторов | создаёт блоки каждые ~2 с, все узлы видят друг друга |
| Перевод AYV | проходит, комиссия списывается, перевод без комиссии отклоняется |
| Падение 1 узла из 4 | сеть продолжает работать, узел после включения догоняет остальных |
| Падение 1 узла из 3 | сеть **останавливается** — поэтому по умолчанию 4 валидатора |
| Боты: 264 перевода за 30 с | все попали в блоки, ~16 переводов на блок, баланс сошёлся до 1 uayv |
| Наблюдатель | заметил падение узла, пропуск подписей, отставание, остановку сети и восстановление |

## Параметры сети

| Параметр | Значение |
|---|---|
| Chain ID | `ayvia-testnet-1` |
| Монета | AYV, базовая единица `uayv`, 1 AYV = 1 000 000 uayv |
| Валидаторы | 4 (переживает падение одного) |
| Время блока | ~2 с |
| Минимальная цена газа | `0.0025uayv` |
| Модули | bank, staking, distribution, slashing, mint, gov, feegrant, authz, upgrade, evidence и др. |

Начальные суммы тестовые и настраиваются в `scripts/testnet.sh`: 1 000 000 AYV каждому
валидатору (100 000 в стейкинге), 10 000 000 AYV кошельку `faucet`, по 10 000 AYV каждому боту.
Экономика основной сети ещё не утверждена — см. `TOKENOMICS.md`.

## Установка на Ubuntu

```bash
sudo apt install -y golang-go build-essential git python3
go version            # любая версия от 1.21: make сам скачает проверенный Go 1.24.7
git clone https://github.com/coinewolf-pixel/ayvia-chain ~/ayvia
cd ~/ayvia
make install          # сборка 5-15 минут, ayviad ставится в /usr/local/bin
```

Данные сети лучше держать на большом диске:

```bash
export BASE=/data/ayvia/testnet
scripts/testnet.sh init       # создать сеть (старая в $BASE удаляется!)
scripts/testnet.sh start      # запустить 4 узла
scripts/testnet.sh status     # высота и соседи каждого узла
scripts/testnet.sh stop       # остановить
```

### Автозапуск вместе с сервером

```bash
sudo BASE=/data/ayvia/testnet scripts/install-systemd.sh
systemctl status 'ayvia-node@*' ayvia-monitor --no-pager
```

Журналы: `journalctl -u ayvia-node@0 -f`, `journalctl -u ayvia-monitor -f`.

## Панель управления

Одна веб-страница для всей сети: сервер и службы, высота и время блока, валидаторы, последние
блоки и транзакции, кошельки и балансы, запуск и остановка ботов, кран тестовых AYV,
журнал наблюдателя и подключение кошелька Keplr.

`install-systemd.sh` ставит её как службу `ayvia-panel` и сам создаёт пароль:

```bash
sudo cat /etc/ayvia/panel.env      # пароль панели
```

Откройте `http://IP-сервера:8100` и введите пароль в поле справа вверху.

Запуск вручную, без systemd:

```bash
PANEL_KEY="длинный-пароль" BASE=/data/ayvia/testnet python3 panel/panel.py
```

Кран отправляет до 1000 тестовых AYV за раз. Для Keplr панель отдаёт RPC и REST узла по
адресам `/rpc` и `/rest` без пароля — это публичные данные сети; если сервер виден из
интернета, открывайте панель через HTTPS (например, `sudo tailscale serve --bg 8100`).

## Порты узлов

| Узел | RPC | REST API | gRPC | P2P |
|---|---|---|---|---|
| node0 | 26657 | 1317 | 9090 | 26656 |
| node1 | 26667 | 1318 | 9091 | 26666 |
| node2 | 26677 | 1319 | 9092 | 26676 |
| node3 | 26687 | 1320 | 9093 | 26686 |

RPC, API и gRPC слушают только `127.0.0.1` — снаружи сервера они недоступны.

## Боты нагрузки

Тестовые кошельки `bot0..bot9` отправляют друг другу случайные суммы тестовых AYV.
В конце — отчёт и сверка: боты потеряли ровно столько, сколько заплатили комиссий.

```bash
python3 scripts/loadbots.py --home $BASE/client --duration 60 --rate 2
python3 scripts/loadbots.py --home $BASE/client --duration 600 --rate 10   # нагрузка побольше
```

Пример отчёта:

```
sent:                 264
accepted to mempool:  264
included OK in blocks:   264
tx per block (avg):   16.50
balance check:        bots lost 0.132000 AYV, fees 0.132000 AYV -> OK, no AYV lost or created
```

## Наблюдатель за сетью

Следит за узлами и сообщает, когда узел не отвечает, сеть не создаёт блоки, узел отстаёт,
у узла нет соседей или валидатор перестал подписывать блоки. Когда проблема уходит —
пишет «ИСПРАВЛЕНО». Если на сервере есть `~/ai.py` и Ollama, к каждой проблеме добавляется
короткий разбор от локальной модели.

```bash
python3 scripts/monitor.py --once                  # одна проверка
python3 scripts/monitor.py --log $BASE/monitor.log # следить постоянно
```

Сообщения в Telegram: создайте бота у @BotFather, узнайте свой chat id и запишите в
`/etc/ayvia/monitor.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

затем `sudo systemctl restart ayvia-monitor`.

## Полезные команды

```bash
ayviad keys list --keyring-backend test --home $BASE/client
ayviad q bank balances <адрес> --node tcp://127.0.0.1:26657
ayviad tx bank send faucet <адрес> 1000000uayv --fees 500uayv \
  --chain-id ayvia-testnet-1 --keyring-backend test --home $BASE/client -y
ayviad q staking validators --node tcp://127.0.0.1:26657
```

## Устройство кода

```
app/                 приложение блокчейна (на основе эталонного simapp из Cosmos SDK v0.53.8)
  app_config.go      список модулей и префиксы адресов ayv
cmd/ayviad/        программа ayviad
scripts/testnet.sh   создание и запуск тестовой сети
scripts/loadbots.py  боты нагрузки
scripts/monitor.py   наблюдатель с AI-разбором и Telegram
scripts/install-systemd.sh  автозапуск на Ubuntu (узлы, наблюдатель, панель)
panel/panel.py       панель управления (порт 8100)
```

## Что дальше

Готово: ядро блокчейна, монета AYV, тестовая сеть, боты, наблюдатель.

Ещё не сделано:

- обозреватель блоков, кошелёк, админ-панель;
- пять AI-агентов и центр управления ими;
- Docker, HTTPS, резервные копии, Prometheus/Grafana;
- утверждённая экономика AYV (`TOKENOMICS.md` — пока черновик);
- для основной сети: независимые валидаторы на разных серверах, аудит безопасности,
  проверенное восстановление после сбоев.
