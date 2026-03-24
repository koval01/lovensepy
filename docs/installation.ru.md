# Установка и настройка

## Что нужно

Перед использованием LovensePy убедитесь, что у вас есть:

- приложение **Lovense Remote** или **Lovense Connect** на телефоне
- **игрушка Lovense**, сопряжённая с приложением
- **та же Wi‑Fi сеть**, что и у устройства (нужно для LAN / Game Mode)
- **токен разработчика** (для Server / Socket API) — в [Lovense Developer Dashboard](https://developer.lovense.com)
- **callback URL** (для сопряжения по QR в Server API) — например туннель ngrok для приёма callback’ов сопряжения

## Возможности

- **Standard API LAN (Game Mode)**: GetToys, GetToyName, Function, Stop, Pattern, Preset, Position, PatternV2
- **Standard API Server**: Function, Pattern, Preset через облако Lovense; `get_qr_code` для сопряжения по QR
- **Standard Socket API**: getToken, getSocketUrl, WebSocket-клиент для сценария с QR и удалённого управления
- **Toy Events API**: события в реальном времени (toy-list, button-down, function-strength-changed и т.д.)
- **MQTT-мост Home Assistant** (опционально): MQTT Discovery + управление через локальный Game Mode (`pip install 'lovensepy[mqtt]'`)
- **Прямой BLE** (опционально): `BleDirectHubSync` / `BleDirectHub` / `BleDirectClient` — см. [Прямой BLE](direct-ble.md)
- **Сервис FastAPI** (`lovensepy.services.fastapi`, опциональный extra `[service]`): HTTP REST + OpenAPI `/docs` для Game Mode или BLE — см. [руководство FastAPI](tutorials/fastapi-lan-rest.md). Пример-обёртка: `examples/fastapi_lan_api.py`.

## Установка пакета {: #install}

```bash
pip install lovensepy
```

MQTT / мост Home Assistant (ставит `paho-mqtt`):

```bash
pip install 'lovensepy[mqtt]'
```

Прямой BLE (ставит `bleak` и `pick` для интерактивного меню BLE-примера):

```bash
pip install 'lovensepy[ble]'
```

**Зависимости:** `aiohttp`, `pydantic`. Опционально: `paho-mqtt` (через `[mqtt]`), `bleak` + `pick` (через `[ble]`).

## Быстрый старт (Game Mode)

### Установите пакет

Команды см. в разделе [Установка пакета](#install) выше.

### Включите Game Mode

В Lovense Remote: **Discover** → **Game Mode** → **Enable LAN**. Запомните **IP-адрес** хоста (например `192.168.1.100`) и **порт** (часто **20011** для Remote, **34567** для Connect).

### Выполните команду

```python
from lovensepy import LANClient, Actions

client = LANClient("MyApp", "192.168.1.100", port=20011)
client.function_request({Actions.VIBRATE: 10}, time=3)
```

Игрушка должна вибрировать на уровне 10 в течение 3 секунд.

!!! tip "Асинхронный код и смена LAN / Server / BLE"
    В программах с **`async def`** клиенты **`AsyncLANClient`**, **`AsyncServerClient`**, **`BleDirectHub`** и **`BleDirectClient`** реализуют **`LovenseAsyncControlClient`**: одни и те же методы управления с одним типом для аннотаций — меняется только способ создания клиента. Синхронные **`LANClient`** / **`ServerClient`** повторяют имена методов, но остаются блокирующими. См. [Способы подключения](connection-methods.md#same-control-code-different-transport) и [Справочник API — LovenseAsyncControlClient](api-reference.md#lovenseasynccontrolclient).

!!! note "Единицы времени"
    Аргумент `time` задаётся в **секундах**. Устройство держит уровень до следующей команды или до вызова `client.stop()`.

Более длинные руководства — в [индексе руководств](index.md#tutorials).
