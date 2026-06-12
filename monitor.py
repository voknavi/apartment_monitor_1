#!/usr/bin/env python3
"""
Apartment rental monitor
- Onliner: fast JSON API
- Kufar + Realt.by: real browser via Playwright
"""

import json
import time
import logging
import sys
import subprocess
from datetime import datetime
from pathlib import Path
import requests

# ── CONFIG ─────────────────────────────────────────────────────────────────────

CONFIG = {
    "interval_minutes": 1,
    "data_file": "seen_ads.json",
    "log_file": "monitor.log",
    "telegram_token": "",       # from @BotFather
    "telegram_chat_ids": "",     # from @userinfobot
    "desktop_notifications": True,
    "browser_headless": True,
    "browser_timeout": 30000,
}

SITES = [
    {
        "name": "Kufar",
        "parser": "kufar_browser",
        "enabled": True,
        "url": "https://re.kufar.by/l/minsk/snyat/kvartiru?cur=USD&prc=r%3A0%2C400&sort=lst.d",
    },
    {
        "name": "Realt.by",
        "parser": "realt_browser",
        "enabled": True,
        "url": (
            "https://realt.by/rent/flat-for-long/"
            "?addressV2=%5B%7B%22townUuid%22%3A%224cb07174-7b00-11eb-8943-0cc47adabd66%22%7D%5D"
            "&page=1&priceTo=400&priceType=840&sortType=createdAt"
        ),
    },
    {
        "name": "Onliner",
        "parser": "onliner_api",
        "enabled": True,
        "api_url": (
            "https://ak.api.onliner.by/search/apartments"
            "?bounds[lb][lat]=53.7503348957998"
            "&bounds[lb][long]=27.301025390625004"
            "&bounds[rt][lat]=54.04568280705819"
            "&bounds[rt][long]=27.822875976562504"
            "&currency=USD&price[min]=50&price[max]=400"
            "&order=created_at:desc&page=1&limit=30"
        ),
    },
]

# ── LOGGING ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["log_file"], encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── PLAYWRIGHT SETUP ───────────────────────────────────────────────────────────

def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        log.info("Installing Playwright browser (one-time, ~150MB)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright",
                        "--quiet", "--no-warn-script-location"], capture_output=True)
        r = subprocess.run([sys.executable, "-m", "playwright", "install",
                            "chromium", "--with-deps"], capture_output=True)
        if r.returncode == 0:
            log.info("Playwright installed OK.")
            return True
        log.error("Playwright install failed:\n" + r.stderr.decode()[:400])
        return False

# ── KUFAR ──────────────────────────────────────────────────────────────────────
# Exact path confirmed by diagnose.py:
#   __NEXT_DATA__ -> props -> initialState -> listing -> ads  (list of 30)
# Each ad has: ad_id (int), subject (str), ad_parameters (list), price_byn (dict)
# URL pattern: https://re.kufar.by/vi/minsk/snyat/kvartiru/{ad_id}

def parse_kufar_ad(ad: dict) -> dict | None:
    ad_id = str(ad.get("ad_id", ""))
    if not ad_id:
        return None

    subject = ad.get("subject", "Квартира")
    # URL comes directly in ad, or build from category path
    link = ad.get("ad_link") or ad.get("url") or f"https://re.kufar.by/vi/minsk/snyat/kvartiru/{ad_id}"

    # Price: look for USD in ad_parameters first
    price_str = "—"
    for p in ad.get("ad_parameters", []):
        if isinstance(p, dict) and p.get("pl") == "price_usd":
            price_str = f"${p['vl']}/мес"
            break
    if price_str == "—":
        byn = ad.get("price_byn") or {}
        if isinstance(byn, dict) and byn.get("amount"):
            price_str = f"{byn['amount']} BYN/мес"

    return {
        "id": f"kufar_{ad_id}",
        "title": subject,
        "price": price_str,
        "url": link,
        "source": "Kufar",
    }


def fetch_kufar_browser(site: dict, context) -> list[dict]:
    ads = []
    page = None
    try:
        page = context.new_page()
        page.goto(site["url"], wait_until="domcontentloaded",
                  timeout=CONFIG["browser_timeout"])
        # Wait for listing to render
        try:
            page.wait_for_selector("a[href*='/vi/']", timeout=10000)
        except Exception:
            pass

        next_data_str = page.evaluate(
            "() => { const e = document.getElementById('__NEXT_DATA__'); return e ? e.textContent : null; }"
        )
        if not next_data_str:
            log.warning("  [Kufar] No __NEXT_DATA__ found")
            return ads

        data = json.loads(next_data_str)
        # EXACT path from diagnose:  props.initialState.listing.ads
        raw = (
            data.get("props", {})
                .get("initialState", {})
                .get("listing", {})
                .get("ads", [])
        )
        log.debug(f"  [Kufar] ads in __NEXT_DATA__: {len(raw)}")

        for ad in raw:
            parsed = parse_kufar_ad(ad)
            if parsed:
                ads.append(parsed)

        log.info(f"  [Kufar] Parsed {len(ads)} ads")
    except Exception as e:
        log.warning(f"  [Kufar] Error: {e}")
    finally:
        if page:
            page.close()
    return ads

# ── REALT.BY ───────────────────────────────────────────────────────────────────
# Exact path confirmed by diagnose.py:
#   __NEXT_DATA__ -> props -> pageProps -> objects  (list of 30)

def parse_realt_object(obj: dict) -> dict | None:
    # Unique numeric code used in URLs (e.g. 4150946)
    code = obj.get("code")
    uuid = obj.get("uuid", "")
    ad_id = str(code or uuid)
    if not ad_id:
        return None

    # Correct URL pattern confirmed from real data
    if code:
        url = f"https://realt.by/rent-flat-for-long/object/{code}/"
    else:
        url = f"https://realt.by/rent-flat-for-long/object/{uuid}/"

    # Title: rooms + address + floor
    rooms = obj.get("rooms")
    addr = obj.get("address", "")
    storey = obj.get("storey")
    storeys = obj.get("storeys")

    parts = []
    if rooms:
        parts.append(f"{rooms}-комн.")
    if addr:
        parts.append(addr)
    if storey and storeys:
        parts.append(f"{storey}/{storeys} эт.")
    title = ", ".join(parts) if parts else "Квартира"

    # Price: priceRates has currency codes as keys
    # 840=USD, 933=BYN, 978=EUR
    price_str = "—"
    rates = obj.get("priceRates") or {}
    if isinstance(rates, dict):
        usd = rates.get("840")   # USD
        eur = rates.get("978")   # EUR
        byn = rates.get("933")   # BYN
        if usd:
            price_str = f"${usd}/мес"
        elif eur:
            price_str = f"€{eur}/мес"
        elif byn:
            price_str = f"{byn} BYN/мес"
    # Fallback: direct price field
    if price_str == "—":
        amount = obj.get("price")
        currency = obj.get("priceCurrency")
        if amount:
            cur_map = {840: "$", 933: " BYN", 978: "€"}
            cur_sym = cur_map.get(currency, "")
            price_str = f"{cur_sym}{amount}/мес" if cur_sym == "$" or cur_sym == "€" else f"{amount}{cur_sym}/мес"

    return {
        "id": f"realt_{ad_id}",
        "title": title,
        "price": price_str,
        "url": url,
        "source": "Realt.by",
    }


def fetch_realt_browser(site: dict, context) -> list[dict]:
    ads = []
    page = None
    try:
        page = context.new_page()
        # domcontentloaded is enough — objects are in SSR __NEXT_DATA__
        try:
            page.goto(site["url"], wait_until="domcontentloaded",
                      timeout=CONFIG["browser_timeout"])
        except Exception as e:
            log.debug(f"  [Realt] goto note: {e}")

        next_data_str = page.evaluate(
            "() => { const e = document.getElementById('__NEXT_DATA__'); return e ? e.textContent : null; }"
        )
        if not next_data_str:
            log.warning("  [Realt] No __NEXT_DATA__ found")
            return ads

        data = json.loads(next_data_str)
        # EXACT path from diagnose:  props.pageProps.objects
        objects = (
            data.get("props", {})
                .get("pageProps", {})
                .get("objects", [])
        )
        log.debug(f"  [Realt] objects in __NEXT_DATA__: {len(objects)}")

        for obj in objects:
            parsed = parse_realt_object(obj)
            if parsed:
                ads.append(parsed)

        log.info(f"  [Realt] Parsed {len(ads)} ads")
    except Exception as e:
        log.warning(f"  [Realt] Error: {e}")
    finally:
        if page:
            page.close()
    return ads

# ── ONLINER ────────────────────────────────────────────────────────────────────

def fetch_onliner_api(site: dict) -> list[dict]:
    ads = []
    try:
        r = requests.get(
            site["api_url"], timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
                "Accept": "application/json",
                "Referer": "https://r.onliner.by/",
            }
        )
        if r.status_code != 200:
            log.warning(f"  [Onliner] HTTP {r.status_code}")
            return ads
        for ap in r.json().get("apartments", []):
            ad_id = str(ap.get("id", ""))
            url = ap.get("url", f"https://r.onliner.by/ak/{ad_id}")
            usd = ap.get("price", {}).get("converted", {}).get("USD", {}).get("amount")
            price_str = f"${usd}/мес" if usd else "—"
            rooms = ap.get("number_of_rooms") or ap.get("rooms") or ap.get("bedrooms")
            rooms_str = f"{rooms}-комн." if rooms else "студия"
            floor = ap.get("floor")
            floors = ap.get("number_of_floors")
            loc = ap.get("location", {})
            address = loc.get("address") or loc.get("user_address", "")
            parts = [rooms_str]
            if address:
                parts.append(address)
            if floor and floors:
                parts.append(f"{floor}/{floors} эт.")
            ads.append({
                "id": f"onliner_{ad_id}",
                "title": ", ".join(parts),
                "price": price_str,
                "url": url,
                "source": "Onliner",
            })
    except Exception as e:
        log.warning(f"  [Onliner] Error: {e}")
    return ads

# ── STORAGE ────────────────────────────────────────────────────────────────────

def load_seen() -> dict:
    p = Path(CONFIG["data_file"])
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_seen(seen: dict):
    Path(CONFIG["data_file"]).write_text(
        json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# ── NOTIFICATIONS ──────────────────────────────────────────────────────────────

def notify_desktop(title: str, message: str):
    if not CONFIG.get("desktop_notifications"):
        return
    try:
        if sys.platform == "win32":
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,"
                "ContentType=WindowsRuntime]>$null;"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                f"$t.GetElementsByTagName('text')[0].InnerText='{title.replace(chr(39), '')}';"
                f"$t.GetElementsByTagName('text')[1].InnerText='{message[:100].replace(chr(39), '')}';"
                "$n=[Windows.UI.Notifications.ToastNotification]::new($t);"
                "[Windows.UI.Notifications.ToastNotificationManager]"
                "::CreateToastNotifier('ApartmentMonitor').Show($n);"
            )
            subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e",
                              f'display notification "{message[:100]}" with title "{title}"'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["notify-send", "-i", "dialog-information", "-t", "10000",
                              title, message[:200]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.debug(f"Desktop notify error: {e}")

def notify_telegram(ad: dict):
    token = CONFIG.get("telegram_token", "").strip()
    chat_ids = CONFIG.get("telegram_chat_ids", [])
    
    # Обратная совместимость: если список пуст, попробовать telegram_chat_id (строка)
    if not chat_ids:
        single = CONFIG.get("telegram_chat_id", "").strip()
        if single:
            chat_ids = [single]
    
    if not token or not chat_ids:
        return
    
    icon = {"Kufar": "\U0001f7e1", "Realt.by": "\U0001f535", "Onliner": "\U0001f7e2"}.get(ad["source"], "\U0001f3e0")
    text = (
        f"{icon} *{ad['source']}* — новое объявление\n"
        f"\U0001f4cb {ad['title']}\n"
        f"\U0001f4b0 {ad['price']}\n"
        f"\U0001f517 [Открыть]({ad['url']})"
    )
    
    for chat_id in chat_ids:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text,
                      "parse_mode": "Markdown", "disable_web_page_preview": False},
                timeout=10,
            )
        except Exception as e:
            log.debug(f"Telegram error for {chat_id}: {e}")

def send_notification(ad: dict):
    msg = f"{ad['title']} — {ad['price']}"
    log.info(f"  NEW [{ad['source']}]: {msg}")
    log.info(f"     {ad['url']}")
    notify_desktop(f"Новая квартира на {ad['source']}", msg)
    notify_telegram(ad)

# ── MAIN LOOP ──────────────────────────────────────────────────────────────────

def fetch_site(site: dict, context) -> list[dict]:
    p = site["parser"]
    if p == "kufar_browser":
        return fetch_kufar_browser(site, context)
    elif p == "realt_browser":
        return fetch_realt_browser(site, context)
    elif p == "onliner_api":
        return fetch_onliner_api(site)
    return []

def check_all(context, seen: dict) -> int:
    new_count = 0
    for site in SITES:
        if not site.get("enabled"):
            continue
        log.info(f"Checking {site['name']}...")
        try:
            ads = fetch_site(site, context)
        except Exception as e:
            log.error(f"  [{site['name']}] Unexpected: {e}")
            ads = []

        if not ads:
            log.warning(f"  [{site['name']}] No listings received")
            continue

        for ad in ads:
            if ad["id"] not in seen:
                seen[ad["id"]] = {
                    "title": ad["title"], "price": ad["price"],
                    "url": ad["url"], "found_at": datetime.now().isoformat(),
                }
                send_notification(ad)
                new_count += 1

    save_seen(seen)
    return new_count


def run():
    log.info("=" * 60)
    log.info("Apartment Monitor (Playwright edition)")
    log.info(f"Interval: {CONFIG['interval_minutes']} min | Headless: {CONFIG['browser_headless']}")
    log.info(f"Telegram: {'configured' if CONFIG.get('telegram_token') else 'not configured'}")
    log.info("=" * 60)

    if not ensure_playwright():
        sys.exit(1)

    from playwright.sync_api import sync_playwright

    seen = load_seen()
    log.info(f"Loaded {len(seen)} previously seen listings")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=CONFIG["browser_headless"],
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )

        if not seen:
            log.info("First run — saving baseline (no notifications)...")
            for site in SITES:
                if not site.get("enabled"):
                    continue
                try:
                    for ad in fetch_site(site, context):
                        seen[ad["id"]] = {
                            "title": ad["title"], "price": ad["price"],
                            "url": ad["url"], "found_at": datetime.now().isoformat(),
                        }
                except Exception:
                    pass
            save_seen(seen)
            log.info(f"Baseline: {len(seen)} listings. Monitoring started...")

        while True:
            try:
                time.sleep(CONFIG["interval_minutes"] * 60)
                log.info(f"--- Check [{datetime.now().strftime('%H:%M:%S')}] ---")
                new = check_all(context, seen)
                if new == 0:
                    log.info("No new listings.")
            except KeyboardInterrupt:
                log.info("Stopped.")
                break
            except Exception as e:
                log.error(f"Unexpected: {e}")
                time.sleep(30)

        context.close()
        browser.close()


if __name__ == "__main__":
    run()