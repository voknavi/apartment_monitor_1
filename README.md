# Монитор аренды квартир

Мониторит новые объявления на **Kufar**, **Realt.by** и **Onliner** каждые 5 минут.
При появлении нового объявления — показывает десктопное уведомление и/или отправляет в Telegram.

---

## Быстрый старт

### Windows
```
Дважды кликни start.bat
```

### Linux / macOS
```bash
chmod +x start.sh
./start.sh
```

### Или напрямую
```bash
pip install requests beautifulsoup4 lxml
python3 monitor.py
```

---

## Настройка

Открой `monitor.py` и в самом верху найди раздел `CONFIG`:

```python
CONFIG = {
    "interval_minutes": 5,       # Интервал проверки (минуты)
    "telegram_token": "",        # Токен Telegram-бота (см. ниже)
    "telegram_chat_id": "",      # Ваш Telegram chat_id
    "desktop_notifications": True,
}
```

---

## Настройка Telegram-уведомлений

1. Найди бота **@BotFather** в Telegram
2. Напиши `/newbot` и создай бота — получишь **токен** (вида `123456:ABCdef...`)
3. Напиши своему боту любое сообщение
4. Узнай свой chat_id: напиши боту **@userinfobot** команду `/start`
5. Вставь токен и chat_id в `CONFIG` в файле `monitor.py`

После настройки уведомления будут приходить вот так:
```
🏠 Новое объявление — Onliner
📋 2-комн., ул. Притыцкого 22, 3/9 эт.
💰 $280/мес
🔗 [Открыть]
```

---

## Работа в фоне

### Windows — запуск скрытым окном
Создай файл `start_hidden.vbs` рядом со скриптом:
```vbscript
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python monitor.py", 0, False
```
Запускай `start_hidden.vbs` — окно будет скрыто.

### Linux — запуск через nohup
```bash
nohup python3 monitor.py > monitor.log 2>&1 &
echo $! > monitor.pid
```
Остановить: `kill $(cat monitor.pid)`

### macOS — запуск через launchd (автостарт)
Создай `~/Library/LaunchAgents/apartment.monitor.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
  <key>Label</key><string>apartment.monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/ПУТЬ/К/monitor.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```
```bash
launchctl load ~/Library/LaunchAgents/apartment.monitor.plist
```

---

## Файлы

| Файл | Описание |
|------|----------|
| `monitor.py` | Основной скрипт |
| `seen_ads.json` | База виденных объявлений (создаётся автоматически) |
| `monitor.log` | Лог работы скрипта |
| `start.sh` | Запуск на Linux/macOS |
| `start.bat` | Запуск на Windows |

---

## Возможные проблемы

**«Объявления не получены»** — сайт заблокировал запрос или изменил структуру.
Решение: подождать следующей попытки (часто временно) или написать issue.

**Telegram не работает** — проверь токен и chat_id, убедись что написал боту `/start`.

**Нет десктопных уведомлений на Linux** — установи `libnotify`:
```bash
sudo apt install libnotify-bin   # Ubuntu/Debian
sudo dnf install libnotify       # Fedora
```
