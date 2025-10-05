#!/usr/bin/env python3

"""
Scraper-Template mit Selenium (Chrome), automatischem Treiber-Download (webdriver-manager),
Unterstützung für Paginierung (URL-Parameter oder "Next"-Button) und CSV-Export.

Anpassbare Parameter:
- START_URL: Startseite / Listing
- ITEMS_SELECTOR: CSS-Selector für Einträge (list of items)
- FIELD_SELECTORS: Dict mit CSS-Selectoren relativ zum Item für die Felder
- PAGINATION: entweder 'url' (mit page_param) oder 'next_button' (CSS-Selector)


E-Bay verwendet: 
- listingId = als ID
- title = Titel
- displayPrice = Preis
- value = Preis als Zahl
- currency = Währung
- endTime = Endzeitpunkt  - davon "value": "2025-10-07T21:00:00.000Z"

Chat-GPT werwendet: 
- li.s-item = einzelnes Listenelement
- a.s-item__link = href enthält die Artikel-URL (daraus lässt sich die ID extrahieren)
- h3.s-item__title = Titel
- span.s-item__price = Preis

"""

"""
ebay_reisegitarren_scraper.py
Scrapt die erste Ergebnisseite der Kategorie:
https://www.ebay.ch/b/Reisegitarren/159948/bn_7204344

Ergebnis: CSV mit den Feldern id, title, price, link
Hinweis: Für Anfänger ist dieses Skript bewusst linear & kommentiert.
"""

import csv
import re
import time
import random
import logging

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

def find_first_text(item, selectors: str) -> str:
    """
    Probiert mehrere CSS-Selector-Varianten (Komma-getrennt).
    Gibt den ersten nicht-leeren Text zurück oder "".
    """
    for sel in selectors.split(","):
        sel = sel.strip()
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
    Probiert mehrere Selector-Varianten und gibt das Attribut (z.B. href, src) zurück.
    """
    for sel in selectors.split(","):
        sel = sel.strip()
        try:
            el = item.find_element(By.CSS_SELECTOR, sel)
            val = el.get_attribute(attr)
            if val:
                return val
        except NoSuchElementException:
            continue
    return ""

from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---------------- Konfiguration (anpassen) ----------------
START_URL = "https://www.ebay.ch/b/Reisegitarren/159948/bn_7204344"
OUTPUT_CSV = "ebay_reisegitarren.csv"
HEADLESS = False            # Debug: False, Produktiv: True
WAIT_TIMEOUT = 15           # Sekunden für WebDriverWait
MAX_ITEMS = 200             # Schutzlimit: max. zu speichernde Items
# Selektoren (angepasst, robustere Varianten)
ITEMS_SELECTOR = "li.brwrvr__item-card, li.brwrvr__item-card--list"
# Generische Fallback-Selektoren für Titel / Preis / Link (werden nacheinander geprüft)
TITLE_SELECTOR = "h3.s-item__title, h3, .brwrvr__title, .s-item__title"
PRICE_SELECTOR = "span.s-item__price, span[aria-label*='Preis'], .brwrvr__price, .s-item__price"
LINK_SELECTOR = "a.s-item__link, a[href*='/itm/'], a"

# ---------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def init_driver(headless: bool = True):
    """Chrome-WebDriver initialisieren (webdriver-manager lädt Chromedriver)."""
    options = Options()
    if headless:
        # headless neuer Stil für aktuelle Chrome-Versionen
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1200")
    # Optional: eine generische User-Agent setzen (kann helfen)
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def extract_item_id_from_url(url: str) -> str:
    """
    Extrahiert die eBay-Item-ID aus einer Artikel-URL.
    Beispiel-Formate:
      - https://www.ebay.ch/itm/.../123456789012
      - https://www.ebay.ch/itm/123456789012?hash...
    """
    if not url:
        return ""
    # Versuch 1: /itm/.../<ID>
    m = re.search(r"/itm/(?:.*?/)?(\d{6,})", url)
    if m:
        return m.group(1)
    # Versuch 2: letzte größere Ziffernfolge
    m2 = re.search(r"(\d{6,})", url)
    return m2.group(1) if m2 else ""

def scrape_first_page(driver) -> List[Dict[str, str]]:
    """Lädt START_URL, wartet auf die Listings und extrahiert id, title, price, link."""
    logger.info("Öffne Seite: %s", START_URL)
    driver.get(START_URL)

from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

def dismiss_cookie_banner(driver, timeout=8):
    """
    Versucht, ein Cookies-/Consent-Banner zu schließen. 
    Prüft mehrere mögliche Selektoren/XPath-Varianten und versucht
    auch, in iFrames zu wechseln, falls das Banner in einem iframe liegt.
    """
    logger.info("Versuche Cookie-Banner zu schließen (falls vorhanden)...")

    # 1) kurze Hilfsfunktion: click safe
    def try_click(elem):
        try:
            elem.click()
            return True
        except (ElementClickInterceptedException, Exception) as e:
            logger.debug("Click fehlgeschlagen: %s", e)
            try:
                # versuchen per JavaScript click (falls overlay die Klicks blockiert)
                driver.execute_script("arguments[0].click();", elem)
                return True
            except Exception as e2:
                logger.debug("JS-click fehlgeschlagen: %s", e2)
                return False

    # 2) Candidate-Selektoren / XPaths (Deutsch/Englisch / generisch)
    button_selectors = [
        "button[aria-label*='accept']",
        "button[aria-label*='Accept']",
        "button[aria-label*='Akzeptieren']",
        "button[aria-label*='Einverstanden']",
        "button:contains('Alle akzeptieren')",        # CSS pseudo -> handled by XPath below
        "button:contains('Accept')",
        "button:contains('Akzeptieren')",
        "button:contains('Einverstanden')",
        "button[class*='accept']",
        "button[class*='Accept']",
        "button[class*='cookie']",
        "button[class*='consent']",
        # generische XPath-Varianten prüfen (Textsuche, case-insensitive per translate)
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ', 'abcdefghijklmnopqrstuvwxyzäöü'), 'akzept')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'einverstanden')]",
        "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
        "//div[contains(@class,'cookie')]//button",
        "//div[contains(@class,'consent')]//button",
    ]

    # 3) Versuche: direktes Suchen im Dokument
    for sel in button_selectors:
        try:
            if sel.strip().startswith("//"):  # XPath
                els = driver.find_elements(By.XPATH, sel)
            elif ":contains" in sel:
                # Selenium unterstützt :contains nicht; wir übersetzen in XPath
                text = sel.split("contains(",1)[-1].rstrip(")")
                xpath = f"//button[contains(., {text})]"
                els = driver.find_elements(By.XPATH, xpath)
            else:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            els = []

        for el in els:
            if try_click(el):
                logger.info("Cookie-Banner über Selector '%s' weggedrückt.", sel)
                # kurz warten, bis Banner verschwindet
                try:
                    WebDriverWait(driver, timeout).until(EC.invisibility_of_element(el))
                except Exception:
                    time.sleep(1)
                return True

    # 4) Falls nicht gefunden: prüfen, ob Banner in einem iframe liegt
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        logger.debug("Gefundene iframes: %d", len(iframes))
        for i, iframe in enumerate(iframes):
            try:
                driver.switch_to.frame(iframe)
                # innerhalb iframe suchen wir einfache Accept-Buttons (XPath)
                iframe_buttons = driver.find_elements(By.XPATH, "//button | //a")
                for btn in iframe_buttons:
                    text = (btn.text or "").strip().lower()
                    if any(k in text for k in ("accept", "akzept", "einverstanden", "cookie")):
                        if try_click(btn):
                            logger.info("Cookie-Banner in iframe #%d weggedrückt (Text: '%s').", i, text)
                            driver.switch_to.default_content()
                            time.sleep(1)
                            return True
                driver.switch_to.default_content()
            except Exception:
                # überspringen und zurück zur Hauptkontext
                driver.switch_to.default_content()
                continue
    except Exception:
        pass

    logger.info("Kein Cookie-Banner automatisch geschlossen (oder keines vorhanden).")
    return False


    try:
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ITEMS_SELECTOR))
        )
    except Exception as e:
        logger.error("Timeout/Wartefehler: %s", e)
        return []

    items = driver.find_elements(By.CSS_SELECTOR, ITEMS_SELECTOR)
    logger.info("Gefundene Elemente (raw): %d", len(items))
if len(items) > 0:
    # Ausgabe der ersten beiden Items zur Kontrolle (kurzer Text / HTML-Auszug)
    first = items[0]
    logger.info("ERSTES ITEM - outerText (kurz): %.200s", first.text.replace("\n", " ") )
    # Optional: komplette erste Elemente-HTML speichern
    with open("debug_first_item.html", "w", encoding="utf-8") as f:
        f.write(first.get_attribute("outerHTML"))
    logger.info("DEBUG: outerHTML des ersten Items in debug_first_item.html geschrieben.")

    logger.info("Gefundene Elemente (raw): %d", len(items))
    results = []

    for idx, item in enumerate(items):
        if len(results) >= MAX_ITEMS:
            break
        try:
            # Link (href) — primärquelle für ID und Detail-URL
            link_el = item.find_element(By.CSS_SELECTOR, LINK_SELECTOR)
            href = find_first_attr(item, LINK_SELECTOR, "href") or ""
        except Exception:
            href = ""

        try:
            title_el = item.find_element(By.CSS_SELECTOR, TITLE_SELECTOR)
            title = find_first_text(item, TITLE_SELECTOR)
        except Exception:
            # Manchmal ist Titel anders strukturiert; sicherheitshalber leer lassen
            title = ""

        try:
            price_el = item.find_element(By.CSS_SELECTOR, PRICE_SELECTOR)
            price = find_first_text(item, PRICE_SELECTOR)
        except Exception:
            price = ""

        item_id = extract_item_id_from_url(href)

        # Nur speichern, wenn wir zumindest eine ID oder Link haben
        if item_id or href:
            results.append({
                "id": item_id,
                "title": title,
                "price": price,
                "link": href
            })

    logger.info("Extrahierte Datensätze: %d", len(results))
    return results

def save_csv(filename: str, rows: List[Dict[str, str]]):
    fieldnames = ["id", "title", "price", "link"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    logger.info("CSV gespeichert: %s (Zeilen: %d)", filename, len(rows))

def main():
    driver = init_driver(HEADLESS)
    try:
        rows = scrape_first_page(driver)
    finally:
        driver.quit()
    if rows:
        save_csv(OUTPUT_CSV, rows)
    else:
        logger.info("Keine Daten extrahiert. Überprüfen Sie Selektoren oder Netzwerkzugang.")

if __name__ == "__main__":
    main()
