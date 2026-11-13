# NEXORUM в реестрах кошельков

Файлы `testnets/nexorumtestnet/chain.json` и `assetlist.json` описывают тестовую сеть и монету
NEXO в формате [Cosmos Chain Registry](https://github.com/cosmos/chain-registry). Из этого
реестра сети берут Keplr, Leap, Cosmostation и многие сайты. Оба файла проверены по официальным
схемам реестра.

## Что заменить перед подачей

В файлах стоят адреса-заглушки `*.nexorum.example`. Их нужно заменить на настоящие, когда сеть
будет доступна из интернета (см. «Публичный доступ» в основном README):

| Поле | Что указать |
|---|---|
| `website` | сайт проекта |
| `apis.rpc`, `apis.rest`, `apis.grpc` | публичные HTTPS-адреса узла |
| `codebase.genesis.genesis_url` | ссылка на `genesis.json` тестовой сети |
| `explorers` | обозреватель блоков, когда он будет |
| `logo_URIs`, `images` | логотип NEXO: PNG 256×256 и/или SVG, положить в `images/` рядом с файлами |

## Как подать

1. Сделайте форк https://github.com/cosmos/chain-registry
2. Скопируйте папку `testnets/nexorumtestnet` (вместе с `images/`) в `testnets/` форка.
3. Откройте pull request. Проверяющие смотрят, что адреса отвечают и файлы проходят схему.

Keplr ведёт и свой реестр (https://github.com/chainapsis/keplr-chain-registry) с похожими
требованиями. До включения в реестры сайты могут добавлять сеть в кошелёк сами — через
`keplrChainInfo()` из `@nexorum/sdk` или кнопку в панели.
