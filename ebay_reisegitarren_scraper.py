#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ebay_reisegitarren_scraper.py
Vollständiges Scraper-Skript für:
https://www.ebay.ch/b/Reisegitarren/159948/bn_7204344

Ergebnis: CSV mit Spalten: id, title, price, link

Wesentliche Merkmale:
- Selenium + webdriver-manager (automatischer Chromedriver)
- Cookie-Banner-Erkennung und -Schließung
- Robuste, mehrstufige Selector-Fallbacks
- Debug-Ausgaben: debug_page.html, debug_first_item.html
- Extraktion der eBay-Item-ID aus Artikel-URLs
- Kompatibel mit Python 3.12
"""

import csv
import re
import time
import logging
from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# -------------------- Konfiguration --------------------
START_URL = "https://www.ebay.ch/b/Reisegitarren/159948/bn_7204344"
OUTPUT_CSV = "ebay_reisegitarren.csv"
HEADLESS = False            # Für Entwicklung: False (sichtbar). Produktion: True
WAIT_TIMEOUT = 18           # Sekunden für WebDriverWait
MAX_ITEMS = 500             # Schutzlimit: max. zu speichernde Items
# Robuste Selektoren (mehrere Alternativen, Komma-getrennt)
ITEMS_SELECTOR = "li.brwrvr__item-card, li.brwrvr__item-card--list, li.s-item, .s-item"
TITLE_SELECTOR = "h3.s-item__title, .s-item__title, .brwrvr__title, h3"
PRICE_SELECTOR = "span.s-item__price, .s-item__price, .brwrvr__price, span[aria-label*='Preis'], div.s-item__detail span, bsig__price, span.bsig__price, span.bsig__price--display"
LINK_SELECTOR = "a.s-item__link, a[href*='/itm/'], a"
# -------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("ebay_scraper")


def init_driver(headless: bool = True) -> webdriver.Chrome:
    """Initialisiert Chrome-WebDriver via webdriver-manager."""
    options = Options()
    if headless:
        # für aktuelle Chrome-Versionen
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1200")
    # Generische User-Agent (kann bei einigen Seiten hilfreich sein)
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def try_click(element, driver) -> bool:
    """Sicheres Klicken: normaler Click, sonst JS-Fallback."""
    try:
        element.click()
        return True
    except (ElementClickInterceptedException, Exception):
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


def dismiss_cookie_banner(driver, timeout: int = 8) -> bool:
    """
    Versucht verschiedene Strategien, ein Cookie-/Consent-Banner zu schließen.
    Gibt True zurück, wenn ein Klick erfolgte, sonst False.
    """
    logger.info("Versuche Cookie-Banner zu schließen (falls vorhanden)...")
    # Kandidaten (CSS oder XPath). Reihenfolge: generisch -> spezifisch
    candidates = [
        "button[aria-label*='accept']",
        "button[aria-label*='Accept']",
        "button[aria-label*='Akzeptieren']",
        "button[aria-label*='Einverstanden']",
        "button[class*='accept']",
        "button[class*='cookie']",
        "button[class*='consent']",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ', 'abcdefghijklmnopqrstuvwxyzäöü'), 'akzept')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'einverstanden')]",
        "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
        "//div[contains(@class,'cookie')]//button",
        "//div[contains(@class,'consent')]//button",
    ]

    for sel in candidates:
        try:
            if sel.startswith("//"):
                els = driver.find_elements(By.XPATH, sel)
            else:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            els = []

        for el in els:
            if try_click(el, driver):
                logger.info("Cookie-Banner geschlossen (Selector: %s).", sel)
                try:
                    WebDriverWait(driver, timeout).until(EC.invisibility_of_element(el))
                except Exception:
                    time.sleep(0.8)
                return True

    # Prüfen in iframes (manche banners liegen in iframe)
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, iframe in enumerate(iframes):
            try:
                driver.switch_to.frame(iframe)
                btns = driver.find_elements(By.XPATH, "//button | //a")
                for b in btns:
                    text = (b.text or "").strip().lower()
                    if any(k in text for k in ("accept", "akzept", "einverstanden", "cookie")):
                        if try_click(b, driver):
                            driver.switch_to.default_content()
                            logger.info("Cookie-Banner in iframe #%d geschlossen (Text: '%s').", i, text)
                            time.sleep(0.8)
                            return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
                continue
    except Exception:
        pass

    logger.info("Kein Cookie-Banner automatisch geschlossen (oder keines vorhanden).")
    return False


def find_first_text(item, selectors: str) -> str:
    """
    Probiert mehrere CSS-Selector-Alternativen (Komma-getrennt).
    Gibt den ersten nicht-leeren Text zurück oder "".
    """
    for sel in selectors.split(","):
        sel = sel.strip()
        if not sel:
            continue
        try:
            el = item.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text:
                return text
        except NoSuchElementException:
            continue
    return ""


def find_first_attr(item, selectors: str, attr: str = "href") -> str:
    """
    Probiert mehrere Selector-Alternativen (Komma-getrennt) und liefert Attribut (z. B. href).
    """
    for sel in selectors.split(","):
        sel = sel.strip()
        if not sel:
            continue
        try:
            el = item.find_element(By.CSS_SELECTOR, sel)
            val = el.get_attribute(attr)
            if val:
                return val
        except NoSuchElementException:
            continue
    return ""


def extract_item_id_from_url(url: str) -> str:
    """
    Extrahiert die eBay-Item-ID aus einer Artikel-URL.
    Beispiel: .../itm/.../123456789012  oder .../itm/123456789012?...
    """
    if not url:
        return ""
    m = re.search(r"/itm/(?:.*?/)?(\d{6,})", url)
    if m:
        return m.group(1)
    m2 = re.search(r"(\d{6,})", url)
    return m2.group(1) if m2 else ""


def scrape_first_page(driver) -> List[Dict[str, str]]:
    """
    Öffnet START_URL, schließt ggf. Cookie-Banner, wartet auf Items,
    extrahiert id, title, price, link und liefert Liste von Dicts zurück.
    """
    logger.info("Öffne Seite: %s", START_URL)
    driver.get(START_URL)

    # Debug: gesamte page_source speichern (zur Analyse)
    try:
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logger.info("DEBUG: page_source in debug_page.html geschrieben.")
    except Exception as e:
        logger.debug("Konnte debug_page.html nicht schreiben: %s", e)

    # Cookie-Banner attempt
    dismiss_cookie_banner(driver, timeout=8)
    # Kleiner Pause, damit Seite nach eventuellem Klick stabilisiert
    time.sleep(0.8)

    # Warten, bis mindestens ein Item erscheint
    try:
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ITEMS_SELECTOR))
        )
    except Exception as e:
        logger.warning("Timeout/Wartefehler beim Warten auf Items: %s", e)
        # No items found within timeout
        # Speichere Seite für Debug (nochmal)
        try:
            with open("debug_page_after_wait.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logger.info("DEBUG: page_source nach wait in debug_page_after_wait.html geschrieben.")
        except Exception:
            pass
        return []

    items = driver.find_elements(By.CSS_SELECTOR, ITEMS_SELECTOR)
    logger.info("Gefundene Elemente (raw): %d", len(items))

    # optional: speichern des ersten Items für Diagnostik
    if len(items) > 0:
        try:
            first = items[0]
            with open("debug_first_item.html", "w", encoding="utf-8") as f:
                f.write(first.get_attribute("outerHTML"))
            logger.info("DEBUG: outerHTML des ersten Items in debug_first_item.html geschrieben.")
            # kurze console-vorschau
            snippet = first.text.replace("\n", " ")[:300]
            logger.info("ERSTES ITEM - outerText (kurz): %s", snippet)
        except Exception:
            pass

    results = []
    for item in items:
        if len(results) >= MAX_ITEMS:
            break

        href = find_first_attr(item, LINK_SELECTOR, "href")
        title = find_first_text(item, TITLE_SELECTOR)
        price = find_first_text(item, PRICE_SELECTOR)
        item_id = extract_item_id_from_url(href)

        # Wenn kein title gefunden, versuchen wir noch, Text aus dem item-Container zu verwenden (Fallback)
        if not title:
            try:
                title = item.text.split("\n")[0].strip()
            except Exception:
                title = ""

        # Nur Datensätze speichern, die zumindest Link oder ID besitzen
        if href or item_id:
            results.append({
                "id": item_id,
                "title": title,
                "price": price,
                "link": href
            })

    logger.info("Extrahierte Datensätze: %d", len(results))
    return results


def save_csv(filename: str, rows: List[Dict[str, str]]):
    """Speichert rows als CSV mit definierten Feldnamen."""
    fieldnames = ["id", "title", "price", "link"]
    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        logger.info("CSV gespeichert: %s (Zeilen: %d)", filename, len(rows))
    except Exception as e:
        logger.error("Fehler beim Speichern der CSV: %s", e)


def main():
    driver = init_driver(HEADLESS)
    try:
        rows = scrape_first_page(driver)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if rows:
        save_csv(OUTPUT_CSV, rows)
    else:
        logger.info("Keine Daten extrahiert. Überprüfen Sie Selektoren, Cookie-Banner oder Netzwerkzugang.")
        logger.info("Schauen Sie sich die Debug-Dateien (debug_page.html / debug_first_item.html) an.")


if __name__ == "__main__":
    main()
