# Справочник API

### LANClient

Клиент Standard API LAN (Game Mode). Отправляет команды по HTTP/HTTPS в приложение Lovense в той же сети.

Для асинхронных приложений (Discord, Telegram, FastAPI, воркеры) используйте `AsyncLANClient`.

#### Конструктор

```python
LANClient(
    app_name: str,
    local_ip: str | None = None,
    *,
    domain: str | None = None,
    port: int = 20011,
    ssl_port: int = 30011,
    use_https: bool = False,
    verify_ssl: bool = True,
    timeout: float = 10.0,
)
```

| Параметр | Тип | По умолчанию | Описание |
|-----------|------|---------|-------------|
| `app_name` | str | — | Имя приложения (например `"MyApp"`) |
| `local_ip` | str | None | IP устройства (например `"192.168.1.100"`). С `domain=None`. |
| `domain` | str | None | Готовый домен (например `"192-168-1-100.lovense.club"`). Когда домен из Socket API. |
| `port` | int | 20011 | HTTP-порт (Lovense Remote: 20011, Connect: 34567) |
| `ssl_port` | int | 30011 | HTTPS-порт |
| `use_https` | bool | False | Использовать HTTPS вместо HTTP |
| `verify_ssl` | bool | True | Проверять SSL-сертификат. Если False — привязка по отпечатку. |
| `timeout` | float | 10.0 | Таймаут запроса в секундах |

**Пример:**

```python
client = LANClient("MyApp", "192.168.1.100", port=20011)
```

**Метод класса:** `LANClient.from_device_info(app_name, domain, https_port=30011, **kwargs)` — создать из данных устройства Socket API (например payload `basicapi_update_device_info_tc`).

#### Методы

| Метод | Параметры | Возврат | Описание |
|--------|------------|---------|-------------|
| `get_toys()` | — | `GetToysResponse` | Подключённые игрушки. Типизированный список `data.toys[]`. |
| `get_toys_name()` | — | `GetToyNameResponse` | Имена подключённых игрушек. |
| `function_request(actions, time=0, loop_on_time=None, loop_off_time=None, toy_id=None, stop_previous=None)` | `actions`: dict вроде `{Actions.VIBRATE: 10}` или по моторам `{Actions.VIBRATE1: 12, Actions.VIBRATE2: 6}`; `toy_id`: один id, список или `None` для всех | `CommandResponse` | Команда Function. `time` в секундах. |
| `stop(toy_id=None)` | `toy_id`: str или list | `CommandResponse` | Остановить все моторы. |
| `preset_request(name, time=0, toy_id=None)` | `name`: enum Presets или str | `CommandResponse` | Пресет (pulse, wave и т.д.). |
| `pattern_request(pattern, actions=None, interval=100, time=0, toy_id=None)` | `pattern`: список 0–20; `actions`: например `[Actions.VIBRATE1]` для одного мотора; `toy_id` опционально | `CommandResponse` | Пользовательский паттерн. |
| `pattern_request_raw(strength, rule="V:1;F:;S:100#", time=0, toy_id=None)` | Сырые строки rule/strength | `CommandResponse` | Расширенный паттерн. |
| `position_request(value, toy_id=None)` | `value`: 0–100 | `CommandResponse` | Position для Solace Pro. |
| `pattern_v2_setup(actions)` | `actions`: список `{ts, pos}` | `CommandResponse` | PatternV2 Setup. |
| `pattern_v2_play(toy_id=None, start_time=None, offset_time=None, time_ms=None)` | — | `CommandResponse` | PatternV2 Play. |
| `pattern_v2_init_play(actions, toy_id=None, ...)` | — | `CommandResponse` | PatternV2 Setup + Play. |
| `pattern_v2_stop(toy_id=None)` | — | `CommandResponse` | PatternV2 Stop. |
| `pattern_v2_sync_time()` | — | `CommandResponse` | PatternV2 SyncTime. |
| `send_command(command_data, timeout=None)` | Сырой dict команды | `dict` | Низкий уровень; сырой dict. При ошибках — `LovenseError`. |
| `decode_response(response)` | dict ответа | str | Человекочитаемая строка ответа. |

**Примеры:**

```python
import time

with client.play({Actions.VIBRATE: 10}, time=5, toy_id="T123"):
    time.sleep(5)

# Одна игрушка, моторы раздельно (класс Edge); каналы через features_for_toy(toy_dict)
client.function_request({Actions.VIBRATE1: 14}, time=2, toy_id="T123")
client.function_request({Actions.VIBRATE2: 8}, time=2, toy_id="T123")

# Паттерн только на мотор 2
client.pattern_request([6, 12, 18], time=4, toy_id="T123", actions=[Actions.VIBRATE2])
```

См. также [руководство LAN](tutorials/lan.md#step-5-one-toy-at-a-time-or-one-motor-at-a-time).

---

### ServerClient

Клиент Standard API Server. Команды через облако Lovense. Нужны токен разработчика и `uid` из сопряжения по QR.

#### Конструктор

```python
ServerClient(
    developer_token: str,
    uid: str,
    timeout: float = 10.0,
)
```

| Параметр | Тип | Описание |
|-----------|------|-------------|
| `developer_token` | str | Из Lovense Developer Dashboard |
| `uid` | str | User ID из callback сопряжения по QR |
| `timeout` | float | Таймаут запроса |

#### Методы

Согласованы с :class:`LANClient` для смены транспорта: `get_toys`, `get_toys_name`, `function_request`, `stop`, `play`, `preset_request`, `pattern_request`, `pattern_request_raw`, `send_command`, `decode_response`.

`pattern_request` принимает **список уровней силы** (как LAN) или сырые позиционные строки ``(rule, strength)``; порядок аргументов `pattern_request_raw(strength, rule=..., ...)` как у LAN.

**По игрушке / мотору:** те же `toy_id` и `Actions.VIBRATE1` / `VIBRATE2`, что у `LANClient` (id из `get_toys()`).

```python
r = client.get_toys()
toys = {t.id: t.model_dump() for t in r.data.toys} if r.data else {}
for tid in toys:
    client.function_request({Actions.VIBRATE: 7}, time=2, toy_id=tid)
```

---

### LovenseAsyncControlClient

Абстрактный базовый класс (`abc.ABC`) для **общего async API управления**: те же имена методов и совместимые сигнатуры у **`AsyncLANClient`**, **`AsyncServerClient`**, **`BleDirectClient`** и **`BleDirectHub`**. Используйте, когда один `async def` (или поле класса) должен держать любую из реализаций — транспорт меняется только **способом создания** клиента.

Синхронные **`LANClient`** / **`ServerClient`** **не** наследники; те же идеи с блокирующими вызовами. Для новых asyncio-приложений предпочтительны async-типы + этот ABC.

```python
from lovensepy import Actions, LovenseAsyncControlClient, AsyncLANClient, AsyncServerClient

async def pulse_once(client: LovenseAsyncControlClient) -> None:
    await client.function_request({Actions.VIBRATE: 8}, time=1.5)

# Pick one transport:
async def via_lan():
    async with AsyncLANClient("App", "192.168.1.50", port=20011) as c:
        await pulse_once(c)

async def via_server():
    async with AsyncServerClient("DEV_TOKEN", "user_uid") as c:
        await pulse_once(c)
```

Сервис FastAPI типизирует бэкенд как **`LovenseControlBackend`** (`Protocol`, подмножество этой поверхности: `get_toys`, `function_request`, `stop`, `pattern_request`, `preset_request`). См. `lovensepy.services.fastapi`.

---

### AsyncServerClient

Асинхронная версия Standard API Server для серверных ботов.

Наследует **`LovenseAsyncControlClient`**.

#### Жизненный цикл и ресурсы

`AsyncServerClient` — async-клиент; закрывайте при остановке процесса:

```python
from lovensepy import AsyncServerClient, Actions

async def run_once():
    async with AsyncServerClient("YOUR_DEV_TOKEN", "USER_UID") as client:
        await client.function_request({Actions.VIBRATE: 10}, time=2)
```

Без `async with` вызывайте явно `await client.aclose()`.

#### Переопределение таймаута на запрос

Высокоуровневые async-методы принимают `timeout`, переопределяя дефолт клиента для одного вызова.

---

### AsyncLANClient

Асинхронный LAN-клиент для локальных приложений (та же сеть, что у устройства Lovense).
Для продакшен-бота на своём сервере предпочтительнее `AsyncServerClient` или `SocketAPIClient`.

Наследует **`LovenseAsyncControlClient`**.

#### Жизненный цикл и ресурсы

`AsyncLANClient` переиспользует HTTP-сессии для пропускной способности. Закрывайте по завершении:

```python
from lovensepy import AsyncLANClient, Actions

async def run_once():
    async with AsyncLANClient("MyBot", "192.168.1.100", port=20011) as client:
        await client.function_request({Actions.VIBRATE: 10}, time=2)
```

Без `async with` вызывайте `await client.aclose()` явно.

#### Переопределение таймаута на запрос

Все высокоуровневые async-методы принимают `timeout` для этого вызова:

```python
toys = await client.get_toys(timeout=2.0)  # быстрый вызов
await client.pattern_request([5, 10, 15, 20], time=20, timeout=15.0)  # длиннее
```

#### Параллелизм

При HTTPS с `verify_ssl=False` проверка отпечатка сертификата защищена от дублирующих одновременных проверок при лавине команд на один endpoint.

---

### Паттерн мультисессионного серверного бота (Discord/Telegram)

На сервере обычно используют:
- `AsyncServerClient` (Standard API Server): HTTP в облако (token + `uid`)
- `SocketAPIClient` (Socket API): WebSocket в облако + цикл событий

Идея: бэкенд должен аутентифицировать входящий запрос и по **своей** карте (например БД) найти *правильную* сессию Lovense. Не принимайте `uid` Lovense (или socket auth token) напрямую из пользовательского запроса.

Так избегают:
- конфликтов данных (общие изменяемые объекты между пользователями)
- путаницы сессий (команды не на тот `uid`)
- проблем безопасности (доверие клиентским идентификаторам сессии)

```python
import asyncio
from lovensepy import AsyncServerClient, Actions


class ServerSessionPool:
    """
    Держит клиентов на пользователя в памяти.

    user_id: id пользователя вашего приложения (Discord/Telegram).
    lovense_uid: сохранён в БД после сопряжения по QR / похожего потока.
    """

    def __init__(self):
        self._clients: dict[str, AsyncServerClient] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, user_id: str, *, lovense_uid: str) -> AsyncServerClient:
        async with self._lock:
            client = self._clients.get(user_id)
            if client is None:
                client = AsyncServerClient(
                    developer_token="YOUR_DEV_TOKEN",
                    uid=lovense_uid,
                    timeout=5.0,
                )
                self._clients[user_id] = client
            return client

    async def close_session(self, user_id: str) -> None:
        async with self._lock:
            client = self._clients.pop(user_id, None)
        if client is not None:
            await client.aclose()

    async def shutdown(self) -> None:
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        await asyncio.gather(*(c.aclose() for c in clients), return_exceptions=True)


sessions = ServerSessionPool()


async def handle_vibrate(user_id: str, level: int) -> None:
    # 1) Аутентификация запроса на сервере (Discord/Telegram).
    # 2) Найти lovense_uid этого пользователя в БД.
    lovense_uid = "LOOKED_UP_FROM_YOUR_DB"

    # 3) Получить правильного клиента на пользователя.
    client = await sessions.get_or_create(user_id, lovense_uid=lovense_uid)

    # 4) При необходимости таймаут на запрос.
    await client.function_request({Actions.VIBRATE: level}, time=2, timeout=3.0)
```

Масштабирование (сервер):
- Один общий event loop и неблокирующие обработчики (`await` везде).
- Переиспользуйте клиентов на пользователя/сессию; не создавайте на каждую команду.
- Ограничивайте параллелизм (`asyncio.Semaphore`), если возможен спам команд.
- TTL / уборка неактивных сессий.
- При больших нагрузках — шардирование воркеров и карты сессий на процесс.
- С `SocketAPIClient` — один WebSocket на сессию Lovense-пользователя (`ws_url`/токен), маршрутизация команд как выше.

---

### SocketAPIClient

Асинхронный WebSocket-клиент Socket API. Команды по WebSocket (или LAN HTTPS при `use_local_commands=True`).

#### Конструктор

```python
SocketAPIClient(
    ws_url: str,
    *,
    use_local_commands: bool = False,
    app_name: str = "lovensepy",
    raise_on_disconnect: bool = False,
    on_socket_open: Callable | None = None,
    on_socket_close: Callable | None = None,
    on_socket_error: Callable[[Exception], ...] | None = None,
    on_socket_io_connected: Callable | None = None,
    on_event: Callable[[str, Any], ...] | None = None,
)
```

| Параметр | Тип | Описание |
|-----------|------|-------------|
| `ws_url` | str | WebSocket URL из `build_websocket_url` |
| `use_local_commands` | bool | Команды по LAN HTTPS, если устройство в той же сети |
| `app_name` | str | Имя приложения для локальных команд |
| `raise_on_disconnect` | bool | `ConnectionError` при отправке в обрыве |
| `on_socket_open`, `on_socket_close`, `on_socket_error` | Callable | Колбэки жизненного цикла соединения |
| `on_socket_io_connected` | Callable | После завершения рукопожатия Socket.IO |
| `on_event` | Callable | На каждое событие Socket.IO `(event_name, payload)` |

#### Методы

| Метод | Описание |
|--------|-------------|
| `connect()` | Async. Подключение и фоновые ping/recv (неблокирующе). |
| `run_forever()` | Async. Подключение и ожидание до разрыва. |
| `start_background(auto_reconnect=False, retry_delay=5.0)` | Запуск `run_forever` (или цикла переподключения) как задачи. |
| `connect_with_retry(retry_delay=5.0, max_retries=None)` | Цикл переподключения для 24/7 ботов. |
| `wait_closed()` | Ждать полного закрытия соединения. |
| `disconnect()` | Закрыть соединение. |
| `send_command(command, action, time_sec=0, toy=None, ...)` | Отправить команду (неблокирующе). |
| `send_command_await(command, action, ...)` | Отправить и дождаться доставки. Для стопов. |
| `send_event(event, payload=None)` | Сырое событие Socket.IO. |
| `on(event_name)` | Декоратор обработчика события. |
| `add_event_handler(event_name, handler)` | Регистрация обработчика из кода. |

Пример маршрутизации событий:

```python
@client.on("basicapi_update_device_info_tc")
async def on_device_info(payload):
    print("Device info:", payload)
```

#### Свойства

| Свойство | Тип | Описание |
|----------|------|-------------|
| `is_socket_io_connected` | bool | True после рукопожатия Socket.IO, готов к командам |
| `is_using_local_commands` | bool | True, если команды идут по LAN HTTPS |

---

### ToyEventsClient

Асинхронный WebSocket-клиент Toy Events API. События игрушек в реальном времени. Только Lovense Remote, порт 20011.

#### Конструктор

```python
ToyEventsClient(
    ip: str,
    port: int = 20011,
    use_https: bool = False,
    https_port: int = 30011,
    app_name: str = "lovensepy",
    *,
    on_open: Callable | None = None,
    on_close: Callable | None = None,
    on_error: Callable[[Exception], ...] | None = None,
    on_event: Callable[[str, Any], ...] | None = None,
)
```

#### Методы и свойства

| Метод/свойство | Описание |
|-----------------|-------------|
| `connect()` | Async. Подключение, запрос доступа, приём событий до разрыва. |
| `disconnect()` | Закрыть соединение. |
| `is_connected` | True, если WebSocket подключён. |
| `is_access_granted` | True, если пользователь выдал доступ в Lovense Remote. |

---

### BleDirectClient

Управление **прямым BLE** (опционально `bleak`). Ограничения, несколько игрушек и конфликт с Lovense Remote — в [Прямой BLE](direct-ble.md#direct-ble).

Импорт: `from lovensepy import BleDirectClient` (ленивый) или `from lovensepy.ble_direct import BleDirectClient`.

Наследует **`LovenseAsyncControlClient`**.

#### Конструктор

```python
BleDirectClient(
    address: str,
    *,
    uart_tx_uuid: str | None = None,
    uart_rx_uuid: str | None = None,
    write_with_response: bool = False,
    silence_on_link_loss: bool = True,
    link_loss_silence_timeout: float = 12.0,
    toy_type: str | None = None,
    uart_inter_command_delay_s: float = 0.015,
    post_timed_function_silence_cooldown_s: float = 0.22,
    dual_single_channel_prime_peer_zero: bool = True,
    dual_single_channel_prime_delay_s: float = 0.045,
    ble_preset_uart_keyword: str = "Pat",
    ble_preset_emulate_with_pattern: bool = False,
    gatt_write_max_attempts: int = 1,
    gatt_write_retry_base_delay: float = 0.2,
    gatt_write_retry_max_delay: float = 2.0,
)
```

| Параметр | Описание |
|-----------|-------------|
| `address` | BLE-адрес устройства (строка зависит от ОС, на macOS часто UUID). |
| `uart_tx_uuid` | Если задано — характеристика должна быть после connect. Если `None`, перебор `DEFAULT_UART_TX_UUIDS` (Lovense UART 5030/455a/5330/5730, Nordic NUS TX, legacy `fff2`), затем семейство Lovense `????0002-…`. |
| `uart_rx_uuid` | Опциональный **RX** (notify). Если `None` — `DEFAULT_UART_RX_UUIDS` и «сосед» TX (`…0002…` → `…0003…`). Без RX хелперы запросов недоступны, `set_vibration`/`send_uart_command` работают. |
| `write_with_response` | Пробрасывается в `bleak` `write_gatt_char(..., response=...)`. |
| `silence_on_link_loss` | Если true (дефолт), неожиданный разрыв планирует короткое **переподключение** и полный список стопов из `uart_catalog`. |
| `link_loss_silence_timeout` | Секунды на переподключение + service discovery (дефолт 12). |
| `toy_type` | Опциональная строка типа Lovense (`lush`, `edge`, `solace pro`, …) для дефолтов :meth:`silence_all_motors` и fallback :func:`lovensepy.toy_utils.features_for_toy`. |
| `uart_inter_command_delay_s` | Пауза между **подряд идущими строками UART** одного логического обновления (например `Vibrate1` затем `Vibrate2`). Дефолт :data:`DEFAULT_UART_INTER_COMMAND_DELAY_S` (~15 ms); `0` — без паузы. |
| `post_timed_function_silence_cooldown_s` | После :meth:`function_request` с ``time > 0`` вызывается :meth:`silence_all_motors`, затем пауза перед возвратом (дефолт :data:`DEFAULT_POST_TIMED_FUNCTION_SILENCE_COOLDOWN_S`, ~220 ms). Помогает следующей команде на части BLE-стеков. `0` — отключить. |
| `dual_single_channel_prime_peer_zero` | Если у игрушки **и** ``Vibrate1``, и ``Vibrate2``, а обновление даёт **одну** ненулевую строку и последний ненулевой мотор был **парный**, послать пару как ``…:0;`` **отдельной** предварительной записью GATT (дефолт вкл.). Сырые :meth:`send_uart_command` сбрасывают память моторов. |
| `dual_single_channel_prime_delay_s` | Пауза после prime-записи нуля пары до основной строки (дефолт :data:`DEFAULT_DUAL_SINGLE_CHANNEL_PRIME_DELAY_S`, ~45 ms). ``0`` — без паузы (всё равно две записи). |
| `ble_preset_uart_keyword` | Ключевое слово UART для пресетов: `Pat` или `Preset`. |
| `ble_preset_emulate_with_pattern` | Если true, имена пресетов приложения мапятся на пошаговые паттерны по UART, если прошивка игнорирует Pat/Preset. |
| `gatt_write_max_attempts` | Сколько раз повторять каждую запись GATT TX при **кратковременных** сбоях (`BleakError`, таймауты, часть `OSError`). `1` = без повторов. |
| `gatt_write_retry_base_delay` | Начальная пауза в секундах между попытками (экспоненциальный backoff, потолок — `gatt_write_retry_max_delay`). |
| `gatt_write_retry_max_delay` | Максимальная пауза между повторами записи GATT. |

#### Методы и свойства

| Метод / свойство | Описание |
|-------------------|-------------|
| `async connect()` | Подключение, разрешение TX UUID (macOS: сериализация между клиентами); `LovenseBLEError`, если нет `bleak` или характеристики. |
| `async disconnect()` | Закрыть BLE. |
| `async aclose()` | Синоним `disconnect()`. |
| `async set_vibration(level)` | `Vibrate:{level};` для `level` в `0..20`; пропуск дубликатов подряд. |
| `async send_uart_command(str, *, encoding, ensure_semicolon)` | Кодирование и запись строки UART; сброс дедупликации вибрации. |
| `async send_uart_bytes(bytes)` | Сырая запись в TX. |
| `async silence_all_motors(toy_type=None)` | Серия стопов: по типу или полный `uart_catalog`. |
| `async query_uart_line(command)` | Подписка на RX, запись команды, первая строка `…;`. |
| `async fetch_battery_percent()` | `Battery;` → проценты 0–100. |
| `async fetch_device_type_fields()` | `DeviceType;` → :class:`DeviceTypeFields`. |
| `async fetch_ble_snapshot(adv_name=None)` | Батарея + тип + `suggested_features` из slug имени `LVS-…`. |
| `is_connected` | True по отчёту нижележащего клиента. |
| `uart_tx_uuid` | UUID TX после `connect()` или `None`. |
| `uart_rx_uuid` | UUID RX notify или `None`. |
| `actions`, `presets`, `error_codes` | Как у :class:`~lovensepy.standard.async_lan.AsyncLANClient`. |
| `last_command` | Последний JSON payload для `send_command`, как у LAN. |
| `async function_request(...)`, `async stop(...)`, `play(...)` | Имена Standard API поверх UART (`lovensepy/ble_direct/standard_compat.py`). :class:`~lovensepy._models.CommandResponse` с `data.transport == "ble"`. |
| `async pattern_request` / `pattern_request_raw` | Эмуляция тайминга LAN-паттерна по UART (не то же самое, что in-app Pattern). |
| `async preset_request` | UART ``Pat:{n};`` или ``Preset:{n};``. Префикс: ``ble_preset_uart_keyword``. Имена через :data:`~lovensepy.PRESET_BLE_PAT_INDEX`; только цифры в ``name`` — сырой слот 0–20. |
| `async position_request` | `Position:{0..100};` по UART. |
| `async send_command` | Те же ключи JSON, что LAN, на UART. |
| `decode_response` | Как у async LAN. |
| `async get_toys` / `get_toys_name`, `async pattern_v2_*` | `LovenseBLEError` — нужен мост приложения Lovense (LAN). |

**Хелперы** (импорт `lovensepy.ble_direct`): `scan_lovense_ble_devices`, `build_vibrate_command`, константы задержек, `ble_uart_features_for_toy_type`, `ble_stop_command_strings_for_toy_type`, `DEFAULT_FULL_STOP_COMMANDS`, `default_full_stop_payloads`, `parse_battery_percent`, `parse_device_type_fields`, `DeviceTypeFields`.

#### BleDirectHub (несколько игрушек, API как у LAN)

Импорт: `from lovensepy import BleDirectHub` (ленивый) или `from lovensepy.ble_direct import BleDirectHub`.

Наследует **`LovenseAsyncControlClient`**.

Один объект в коде; **у каждой зарегистрированной игрушки** свой `BleDirectClient` и BLE. Строковые id (как LAN `toyId`), маппинг на адреса, те же имена методов, что у `AsyncLANClient` / `BleDirectClient`. **`toy_id=None`** (или без `toy` в `send_command`) — **все** зарегистрированные игрушки.

```python
hub = BleDirectHub()
hub.add_toy("a", "BLE-ADDRESS-1", name="LVS-Edge", toy_type="edge")
hub.add_toy("b", "BLE-ADDRESS-2", name="LVS-Lush")
await hub.connect_all()
await hub.preset_request(hub.presets.PULSE, time=10.0, toy_id=None)  # everyone
await hub.function_request({hub.actions.VIBRATE: 5}, toy_id="b")      # one
await hub.function_request({hub.actions.VIBRATE1: 10}, time=2, toy_id="a")  # Edge-style motor 1
await hub.function_request({hub.actions.VIBRATE2: 8}, time=2, toy_id="a")   # motor 2
await hub.disconnect_all()
```

Без ручных адресов: ``await hub.discover_and_connect(timeout=10.0)`` сканирует рекламу ``LVS-…``, регистрирует стабильные id, подключается и опционально читает UART, чтобы ``get_toys`` был как в LAN-руководстве. ``timeout`` — **только время прослушивания скана**, не время работы моторов.

`get_toys` **синтетический** (регистрация + состояние соединения + опционально батарея/тип по UART), не инвентарь самого приложения Lovense.

---

### HAMqttBridge

MQTT-мост для **Home Assistant** (MQTT Discovery). Команды через :class:`~lovensepy.standard.async_base.LovenseAsyncControlClient` — :class:`~lovensepy.standard.async_lan.AsyncLANClient` (**`transport="lan"`**) или :class:`~lovensepy.ble_direct.hub.BleDirectHub` (**`transport="ble"`**). Опционально :class:`~lovensepy.toy_events.client.ToyEventsClient` **только в LAN** для живой батареи/силы при `use_toy_events=True`.

Нужен `paho-mqtt` (`pip install 'lovensepy[mqtt]'`). Для BLE ещё `bleak` (`pip install 'lovensepy[ble]'`).

Импорт: `from lovensepy import HAMqttBridge` (ленивый) или `from lovensepy.integrations.mqtt import HAMqttBridge`.

#### Конструктор

```python
HAMqttBridge(
    mqtt_host: str,
    mqtt_port: int = 1883,
    *,
    lan_ip: str | None = None,
    transport: Literal["lan", "ble"] = "lan",
    lan_port: int = 20011,
    toy_events_port: int | None = None,
    app_name: str = "lovensepy_ha",
    topic_prefix: str = "lovensepy",
    mqtt_username: str | None = None,
    mqtt_password: str | None = None,
    mqtt_client_id: str | None = None,
    refresh_interval: float = 45.0,
    use_https: bool = False,
    use_toy_events: bool = True,
    ble_discover_timeout: float = 15.0,
    ble_name_prefix: str | None = "LVS-",
    ble_enrich_uart: bool = True,
    ble_client_kwargs: dict[str, Any] | None = None,
    ble_hub: BleDirectHub | None = None,
)
```

| Параметр | Описание |
|-----------|-------------|
| `mqtt_host`, `mqtt_port` | MQTT-брокер (тот же, что у интеграции HA). |
| `transport` | `"lan"` (Game Mode HTTP) или `"ble"` (прямой BLE-хаб). |
| `lan_ip`, `lan_port` | Обязательны при `transport="lan"`: HTTP API Game Mode (`/command`). |
| `toy_events_port` | WebSocket Toy Events (дефолт как `lan_port`, обычно 20011). Только LAN. |
| `topic_prefix` | Префикс топиков state/command и группировки discovery. |
| `use_toy_events` | Только LAN: False — только опрос `GetToys`. Игнорируется при `transport="ble"`. |
| `ble_discover_timeout` | BLE: время скана для `discover_and_connect`, если не передан `ble_hub`. |
| `ble_name_prefix`, `ble_enrich_uart`, `ble_client_kwargs` | В :meth:`~lovensepy.ble_direct.hub.BleDirectHub.discover_and_connect`. |
| `ble_hub` | Готовый хаб (`transport="ble"`); иначе мост создаст сам при `start()`. |

#### Методы и свойства

| Метод / свойство | Описание |
|-------------------|-------------|
| `async start()` | MQTT, транспорт (LAN или BLE), подписка, discovery, refresh (+ Toy Events в LAN). |
| `async stop()` | Отмена задач, `offline`, отключение MQTT, `aclose` у клиента управления. |
| `availability_topic` | Удерживаемый статус моста (`lovensepy/bridge/status`). У сущностей ещё `…/<safe_toy_id>/device_availability`. |

---

### Pattern Players

Высокоуровневый API синусов и комбо-паттернов.

#### SyncPatternPlayer

Для `LANClient`. Синхронный.

```python
SyncPatternPlayer(client: LANClient, toys: dict[str, dict] | GetToysResponse)
```

| Метод | Параметры | Описание |
|--------|------------|-------------|
| `play_sine_wave(toy_id, feature, duration_sec=5, num_steps=100, stop_prev_first=True)` | `feature`: например `"Vibrate1"` | Синус на одном канале. |
| `play_combo(targets, duration_sec=4, num_steps=100)` | `targets`: `[(toy_id, feature), ...]` | Комбо со случайными фазами. |
| `stop(toy_id)` | — | Стоп игрушки. |
| `features(toy_id)` | — | Список фич игрушки. |

**Пример:**

```python
player = SyncPatternPlayer(client, toys)
player.play_sine_wave("T123", "Vibrate1", duration_sec=5)
player.play_combo([("T1", "Vibrate1"), ("T2", "Vibrate")], duration_sec=4)
player.stop("T123")
```

#### AsyncPatternPlayer

Для `SocketAPIClient`. Те же методы, async (`await`).

```python
player = AsyncPatternPlayer(client, toys)
await player.play_sine_wave("T123", "Vibrate1", duration_sec=5)
await player.stop("T123")
```

---

### Исключения и обработка ошибок {: #exceptions-and-error-handling }

Все типы в `lovensepy.exceptions`, реэкспорт из `lovensepy`. У сетевых подклассов есть **`endpoint`** (URL или логическое имя) и опционально **`payload`** (отправленный dict команды — удобно для логов).

**Иерархия**

```text
LovenseError
└── LovenseNetworkError          # .endpoint, .payload
    ├── LovenseAuthError         # HTTP 401 / 403
    ├── LovenseDeviceOfflineError
    │   ├── LovenseTimeoutError  # таймаут HTTP-клиента (aiohttp)
    │   └── LovenseBLEError      # BLE / GATT, нет bleak, не подключено
    └── LovenseResponseParseError
```

**LAN / Server (HTTP)**

| Ситуация | Исключение | Примечание |
|-----------|------------|------------|
| Неверный/просроченный токен, запрещено | `LovenseAuthError` | `HttpTransport` / async при статусе **401** или **403**. |
| Приложение недоступно, отказ в соединении | `LovenseDeviceOfflineError` | Ошибки соединения aiohttp (например `ClientConnectorError`) — не то же самое, что таймаут. |
| Запрос слишком долгий | `LovenseTimeoutError` | Подкласс `LovenseDeviceOfflineError` — ловите **раньше** родителя, если нужен отдельный сценарий. |
| Другой HTTP (не 200 и не 401/403) | `LovenseNetworkError` | Общий сбой транспорта/HTTP. |
| Тело ответа не JSON | `LovenseResponseParseError` | |

**BLE**

Чаще всего `LovenseBLEError` (подкласс `LovenseDeviceOfflineError`): не подключено, неизвестный id на хабе, нет UART TX, обёртки ошибок `bleak`, таймауты библиотеки (в тексте часто `timed out`). Отдельного «BLE auth» нет — сопряжение вне этого клиента.

**Socket API**

При обрыве сессии возможен `LovenseDeviceOfflineError`; в других местах — `LovenseError`. Имеет смысл широкий `except LovenseError`, затем уточнение по типу.

**Порядок except**

Сначала **узкие** типы, затем `LovenseNetworkError`, затем `LovenseError`:

```python
from lovensepy import (
    LovenseAuthError,
    LovenseBLEError,
    LovenseDeviceOfflineError,
    LovenseError,
    LovenseResponseParseError,
    LovenseTimeoutError,
)

try:
    await client.function_request({...}, time=1)
except LovenseAuthError:
    ...
except LovenseTimeoutError:
    ...
except LovenseBLEError:
    ...
except LovenseResponseParseError:
    ...
except LovenseDeviceOfflineError:
    ...
except LovenseError:
    ...
```

**Устойчивость BLE и сравнение с Socket `auto_reconnect`**

- **Socket API:** `start_background(auto_reconnect=True)` держит **сессию** WebSocket при обрывах.
- **BLE:** `silence_on_link_loss` делает **одно** переподключение, чтобы послать **стоп** после неожиданного разрыва; ваши команды не повторяются.
- **Записи GATT:** задайте `gatt_write_max_attempts` &gt; `1` у `BleDirectClient` для повторов `write_gatt_char` при кратковременных `BleakError` / таймауте / OS. Те же аргументы — в `BleDirectHub.add_toy(..., **client_kwargs)` или `discover_and_connect(**client_kwargs)`.
- **Потеря сессии:** снова `await client.connect()` или `await hub.discover_and_connect(...)`; при частых сбоях оберните свой backoff.

---

### Утилиты

| Функция | Параметры | Возврат | Описание |
|----------|------------|---------|-------------|
| `get_token(developer_token, uid, uname=None, utoken=None, timeout=10)` | — | str | Токен авторизации Socket API. Исключение при ошибке. |
| `get_socket_url(auth_token, platform, timeout=10)` | `platform`: Website Name из Dashboard | dict | Информация о сокете. |
| `build_websocket_url(socket_info, auth_token)` | — | str | Полный wss:// URL. |
| `get_qr_code(developer_token, uid, uname=None, utoken=None, timeout=10)` | — | dict | QR для Server API. `{qr, code}`. Замечание по безопасности в docstring. |
| `features_for_toy(toy)` | `toy`: dict из GetToys | list[str] | Список фич (например `["Vibrate1", "Rotate"]`). |
| `stop_actions(toy)` | `toy`: dict | dict | `{Vibrate1: 0, ...}` для остановки. |

