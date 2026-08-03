# Сервис FastAPI (LAN + BLE) {#fastapi-lan-rest-tutorial}

**HTTP API** для дашбордов, скриптов или мобильных приложений: **FastAPI** + **OpenAPI** на `/docs`, [панель управления](../web-ui.md) в браузере на `/` и планировщик **asyncio** (слоты `Function` по моторам, сессии preset/pattern, `GET /tasks`). Реализация — **`lovensepy.services.http_api`** (импорт **`lovensepy.services.fastapi`** сохранён для совместимости): в **LAN** используется **Game Mode** (`AsyncLANClient`); в **BLE** — **`BleDirectHub`**; в **hybrid** несколько транспортов одновременно. Все бэкенды удовлетворяют **`LovenseControlBackend`**, протоколу, согласованному с поверхностью **`LovenseAsyncControlClient`**, которую использует планировщик (см. [Справочник API — LovenseAsyncControlClient](../api-reference.md#lovenseasynccontrolclient)).

!!! tip "Просто хочется управлять игрушками?"
    Запустите сервис и откройте `http://127.0.0.1:8000/` — встроенная панель сама найдёт, подключит и будет управлять. Эта страница — про работу с API напрямую.

## Требования

```bash
pip install 'lovensepy[service]'
# для BLE-режима ещё:
pip install 'lovensepy[ble]'
```

## LAN-режим (по умолчанию)

### Окружение

```bash
export LOVENSE_LAN_IP=192.168.1.100   # хост с Lovense Remote (Game Mode)
export LOVENSE_SERVICE_MODE=lan        # по умолчанию; можно опустить
# опционально: LOVENSE_LAN_PORT=20011 LOVENSE_APP_NAME=... LOVENSE_TOY_IDS=id1,id2
# опционально: LOVENSE_SESSION_MAX_SEC=60  # строка /tasks при time=0 у preset/pattern
```

### Запуск сервера

```bash
uvicorn lovensepy.services.http_api.app:app --host 0.0.0.0 --port 8000
```

Устаревшая обёртка (предупреждение при импорте):

```bash
uvicorn examples.fastapi_lan_api:app --host 0.0.0.0 --port 8000
```

### Программная настройка

```python
from lovensepy.services import ServiceConfig, create_app

app = create_app(ServiceConfig(mode="lan", lan_ip="192.168.1.100"))
```

Колбэки BLE-рекламы (только BLE-режим, см. ниже): передайте `on_ble_advertisement` и/или `on_ble_advertisement_async` в `create_app(...)`.

## BLE-режим

Вместо Game Mode — прямой BLE. На старте ничего не подключено: вызовите `POST /ble/connect/auto` для сценария «просто работает» либо сканируйте и подключайте по адресу через `POST /ble/connect` (или колбэки для `BleDirectHub.add_toy` / `connect`).

```bash
export LOVENSE_SERVICE_MODE=ble
# опционально: LOVENSE_BLE_SCAN_TIMEOUT=8 LOVENSE_BLE_SCAN_PREFIX=LVS-  (пустой префикс = все имена)
# опционально пассивные обновления RSSI: LOVENSE_BLE_ADVERT_MONITOR=1 LOVENSE_BLE_ADVERT_MONITOR_INTERVAL=2
# опционально пресеты: LOVENSEPY_BLE_PRESET_UART=Pat   (как у BleDirectClient по умолчанию; сервис по умолчанию Preset для /command/preset)
# опционально: LOVENSEPY_BLE_PRESET_EMULATE_PATTERN=1  (pulse/wave/… через паттерн, если UART пресеты игнорируются)
# опционально: LOVENSE_BLE_AUTO_RECONNECT=0  (не держать зарегистрированные игрушки подключёнными)
uvicorn lovensepy.services.http_api.app:app --host 0.0.0.0 --port 8000
```

Дополнительные HTTP-маршруты (только BLE):

- `POST /ble/scan` — скан по запросу; query `timeout` опционально; ответ: `address`, `name`, `rssi`
- `GET /ble/advertisements` — последняя карта рекламы (сканы плюс опциональный монитор)
- `GET /ble/toys` — вид регистраций: адрес, состояние связи, кэш метаданных UART, статус автопереподключения
- `POST /ble/connect` — тело: `address`, опционально `toy_id`, `name`, `toy_type`, `replace`
- `POST /ble/connect/auto` — скан, подключение всего, что ответило, и переподключение зарегистрированных; вся настройка одним вызовом
- `POST /ble/reconnect/{toy_id}` — переподключение со снятием паузы после ручного отключения
- `POST /ble/disconnect/{toy_id}` — отключение GATT (регистрация остаётся, автопереподключение встаёт на паузу)
- `DELETE /ble/toys/{toy_id}` — отключение и снятие регистрации

`GET /toys` и командные маршруты совпадают с LAN после подключения игрушек. Зарегистрированные игрушки сервис держит подключёнными в фоне с экспоненциальной задержкой на игрушку (`LOVENSE_BLE_AUTO_RECONNECT=0` — выключить); текущее состояние — в `GET /state` → `ble.supervisor`.

## Состояние одним запросом, обновления одним сокетом

- `GET /state` — игрушки, объединённые по транспортам, активные строки планировщика, обнаружение BLE и статус супервизора, состояние привязки Socket API, возможности и конфигурация. Список игрушек кэшируется на `LOVENSE_STATE_CACHE_TTL` секунд (по умолчанию 2); `?fresh=true` обходит кэш. Дашборду стоит опрашивать именно этот эндпоинт вместо `/toys` в цикле: по BLE каждый `GET /toys` с `battery=true` стоит UART-обмена на устройство.
- `WS /ws` — тот же снимок при каждом изменении, в простое — heartbeat. `{"op": "refresh"}` — немедленный свежий снимок, `{"op": "ping"}` — ответ `{"type": "pong"}`.
- `GET /system/network` — адреса, по которым доступен сервис (для QR-кода «открыть на телефоне»).

## Настройка на ходу

Без перезапуска и переменных окружения:

- `POST /config/lan-ip` — `{"lan_ip": "192.168.1.100", "lan_port": 20011}` включает LAN на месте
- `POST /config/socket` — учётные данные Socket API (только в памяти, на диск не пишутся)
- `POST /config/ble` — автопереподключение, фоновый скан, фильтр скана, диалект пресетов
- `POST /config/transports` — `{"lan": true, "ble": false}` для переключения транспортов
- `GET /config` — текущая конфигурация без секретов

Эндпоинты выключенного транспорта отвечают **409**, чтобы клиент отличал «выключено» от «нет такого маршрута».

## OpenAPI

Откройте `http://127.0.0.1:8000/docs` (ReDoc на `/redoc`) и попробуйте `GET /state`, `POST /command/preset`, `GET /tasks` и эндпоинты стопа (`/command/stop/...` и пакетные варианты).

## Замечания по поведению

- **BLE:** паттерны (и зацикленный ``Function``) могут удерживать работу, пока :class:`~lovensepy.ble_direct.client.BleDirectClient` шагает по UART. **Пресеты** в этом сервисе по умолчанию через UART ``Preset:{n};`` (``LOVENSEPY_BLE_PRESET_UART=Pat`` — как у прямого BLE-клиента по умолчанию). С ``LOVENSEPY_BLE_PRESET_EMULATE_PATTERN=1`` четыре имени приложения идут через шаги паттерна (как ``/command/pattern``). Таймированные пресеты при ``wait_for_completion=False`` откладывают удержание + stop burst. У прямого :class:`~lovensepy.ble_direct.client.BleDirectClient` по умолчанию ``wait_for_completion=True``.
- Повторная отправка **того же** пресета или паттерна для той же игрушки **продлевает** сессию и **шлёт ещё одну транспортную команду** с новым `time` (Lovense иначе гасит после `timeSec` каждой команды).
- Сервис запускается даже когда транспорт недоступен (нет LAN IP, нет `bleak`, нет учётных данных Socket): его эндпоинты отвечают **409**, пока вы не настроите их через `/config/*` или панель. В health-only режим сервис уходит только при действительно сломанной конфигурации окружения.
- `GET /tasks` возвращает строки **function** (`kind: function`), **function_loop** при `loop_on_time` / `loop_off_time` у `POST /command/function`, и **preset** / **pattern** (`kind: preset` / `pattern`). В метках времени есть `started_at` (UTC) и `started_monotonic_sec` для стабильного `remaining_sec`.

См. также страницу [Веб-панель управления](../web-ui.md) и строку [Примеры](../appendix.md#examples) про HTTP-сервис.
