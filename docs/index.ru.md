# Документация LovensePy

Здесь собраны развёрнутые руководства, таблицы API и справочные материалы для [LovensePy](https://github.com/koval01/lovensepy). [README репозитория](https://github.com/koval01/lovensepy#readme) остаётся кратким для PyPI и быстрого знакомства.

## С чего начать

- [Установка и настройка](installation.md) — требования, extras (`[mqtt]`, `[ble]`), первый скрипт в Game Mode
- [Веб-панель управления](web-ui.md) — запустите HTTP-сервис и управляйте игрушками из браузера или с телефона, без кода
- [Способы подключения и архитектура](connection-methods.md) — какой клиент выбрать, пути трафика, схема
- [Прямой BLE](direct-ble.md) — быстрый старт `BleDirectHubSync` (как LAN), асинхронный хаб, замечания

## Руководства {: #tutorials}

- [LAN Game Mode и прямой BLE-хаб](tutorials/lan.md)
- [Server API + сопряжение по QR](tutorials/server-qr.md)
- [Socket API](tutorials/socket.md)
- [События игрушек](tutorials/toy-events.md)
- [Home Assistant MQTT](tutorials/home-assistant-mqtt.md)
- [FastAPI LAN REST](tutorials/fastapi-lan-rest.md)

## Справочник

- [Справочник API](api-reference.md) — конструкторы, методы, проигрыватели паттернов, утилиты
- [Приложение](appendix.md) — действия/пресеты, типы событий, диаграммы потоков Lovense, таблица примеров, тесты, внешние ссылки
- [История изменений](changelog.md) — заметки о релизах (ссылки на `CHANGELOG.md` в репозитории)

## Локальная сборка

```bash
pip install -e ".[docs]"
mkdocs serve
```

Откройте `http://127.0.0.1:8000` для предпросмотра.

Живой сайт собирается из этой папки с помощью [MkDocs](https://www.mkdocs.org/); конфигурация в [`mkdocs.yml`](https://github.com/koval01/lovensepy/blob/main/mkdocs.yml). GitHub Actions публикует статический вывод. Если сайт не обновился после первого запуска workflow, откройте в репозитории **Settings** → **Pages** и в **Build and deployment** выберите **GitHub Actions**.
