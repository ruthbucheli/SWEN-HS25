#!/usr/bin/env python3
"""
Scraper-Template mit Selenium (Chrome), automatischem Treiber-Download (webdriver-manager),
Unterstützung für Paginierung (URL-Parameter oder "Next"-Button) und CSV-Export.

Anpassbare Parameter:
- START_URL: Startseite / Listing
- ITEMS_SELECTOR: CSS-Selector für Einträge (list of items)
- FIELD_SELECTORS: Dict mit CSS-Selectoren relativ zum Item für die Felder
- PAGINATION: entweder 'url' (mit page_param) oder 'next_button' (CSS-Selector)
"""

import csv
import time
import logging
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ----------------- Konfiguration -----------------
START_URL = "https://www.ebay.ch/b/Reisegitarren/159948/bn_7204344"  # START-URL anpassen
HEADLESS = False
WAIT_TIMEOUT = 15  # Sekunden für WebDriverWait
DELAY_BETWEEN_REQUESTS = (1.0, 2.5)  # Sekunden; können mit random.uniform verwendet werden
MAX_PAGES = 10  # Sicherheitslimit für Paginierung

# Selektoren anpassen: ITEMS_SELECTOR selektiert alle Listeneinträge auf einer Seite
ITEMS_SELECTOR = ".result-item"  # Beispiel: CSS-Selector für jedes Listenelement

# Relative Selektoren (relativ zum einzelnen Item) für Feld-Extraktion
FIELD_SELECTORS: Dict[str, str] = {
    "title": ".title",           # item.find_element(By.CSS_SELECTOR, ".title").text
    "price": ".price",
    "link": "a",                 # extrahiert href von a
}

# Paginierungskonfiguration: "url" verwendet page_param, "next_button" klickt Button
PAGINATION_MODE = "url"  # "url" oder "next_button"
PAGE_PARAM_NAME = "page"  # falls PAGINATION_MODE == "url"
NEXT_BUTTON_SELECTOR = ".pagination-next"  # falls PAGINATION_MODE == "next_button"

OUTPUT_CSV = "scraped_data.csv"
# -------------------------------------------------

# Logging einrichten
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def build_url_for_page(base_url: str, page_number: int) -> str:
    """Erzeugt URL mit page-Parameter (einfacher Ansatz)."""
    if "?" in base_url:
        return f"{base_url}&{PAGE_PARAM_NAME}={page_number}"
    else:
        return f"{base_url}?{PAGE_PARAM_NAME}={page_number}"

def init_driver(headless: bool = True) -> webdriver.Chrome:
    """Initialisiert Chrome-WebDriver via webdriver-manager."""
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1200")
    chrome_options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except WebDriverException as e:
        logger.error("Fehler beim Starten des WebDrivers: %s", e)
        raise
    return driver

def extract_field_from_element(item, selector: str):
    """Extrahiert Text oder href (bei 'a') aus einem WebElement; gibt '' bei Fehlern."""
    try:
        # Wenn Selector direkt ein Attribut (z.B. 'a') ist und href benötigt:
        elem = item.find_element(By.CSS_SELECTOR, selector)
        if elem.tag_name.lower() == "a":
            href = elem.get_attribute("href")
            return href if href is not None else elem.text.strip()
        return elem.text.strip()
    except Exception:
        return ""

def scrape_page(driver: webdriver.Chrome, url: str) -> List[Dict[str, str]]:
    """Lädt URL, wartet auf Items, extrahiert Daten und gibt Liste von Dicts zurück."""
    logger.info("Lade Seite: %s", url)
    driver.get(url)
    # Warten, bis mindestens ein Item erscheint
    try:
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ITEMS_SELECTOR))
        )
    except TimeoutException:
        logger.warning("Timeout beim Warten auf Items auf %s", url)
        return []

    items = driver.find_elements(By.CSS_SELECTOR, ITEMS_SELECTOR)
    logger.info("Gefundene Elemente: %d", len(items))
    results = []
    for item in items:
        record = {}
        for field_name, sel in FIELD_SELECTORS.items():
            record[field_name] = extract_field_from_element(item, sel)
        results.append(record)
    return results

def click_next(driver: webdriver.Chrome) -> bool:
    """Klickt den 'Next'-Button; gibt True zurück, wenn erfolgreich."""
    try:
        btn = driver.find_element(By.CSS_SELECTOR, NEXT_BUTTON_SELECTOR)
        # Prüfen, ob Button disabled ist
        disabled_attr = btn.get_attribute("disabled")
        if disabled_attr:
            return False
        btn.click()
        # Kurz warten bis Seite nachlädt
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.staleness_of(btn)
        )
        return True
    except NoSuchElementException:
        logger.info("Next-Button nicht gefunden.")
        return False
    except TimeoutException:
        logger.warning("Timeout nach Klick auf Next-Button.")
        return False
    except Exception as e:
        logger.error("Fehler beim Klicken auf Next-Button: %s", e)
        return False

def save_to_csv(filename: str, rows: List[Dict[str, str]], fieldnames: List[str]):
    """Schreibt Ergebnisse in CSV; schreibt Header, falls Datei neu."""
    mode = "w"
    logger.info("Speichere %d Zeilen nach %s", len(rows), filename)
    with open(filename, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

def main():
    driver = init_driver(HEADLESS)
    all_results: List[Dict[str, str]] = []
    try:
        if PAGINATION_MODE == "url":
            # Iteriere über Seiten durch Setzen eines page-Parameters
            for page in range(1, MAX_PAGES + 1):
                url = build_url_for_page(START_URL, page)
                page_results = scrape_page(driver, url)
                if not page_results:
                    logger.info("Keine Ergebnisse auf Seite %d — Abbruch der Paginierung.", page)
                    break
                all_results.extend(page_results)
                # Sicherheitsmaßnahme: kleine Pause, um Server nicht zu überlasten
                time.sleep(1.2)
        else:
            # Paginierung über 'Next'-Button
            driver.get(START_URL)
            for page in range(1, MAX_PAGES + 1):
                try:
                    WebDriverWait(driver, WAIT_TIMEOUT).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ITEMS_SELECTOR))
                    )
                except TimeoutException:
                    logger.warning("Timeout beim Warten auf Items auf %s", driver.current_url)
                    break
                items_on_page = scrape_page(driver, driver.current_url)
                if not items_on_page:
                    break
                all_results.extend(items_on_page)
                # Versuch, Next zu klicken; wenn nicht möglich, beenden
                success = click_next(driver)
                if not success:
                    logger.info("Keine weitere Seite gefunden. Paginierung beendet.")
                    break
                # kleine Pause nach Klick
                time.sleep(1.0)

    finally:
        driver.quit()

    # CSV speichern
    if all_results:
        # Feldreihenfolge definieren
        fieldnames = list(FIELD_SELECTORS.keys())
        save_to_csv(OUTPUT_CSV, all_results, fieldnames)
        logger.info("Scraping abgeschlossen. %d Einträge gespeichert.", len(all_results))
    else:
        logger.info("Keine Daten extrahiert.")

if __name__ == "__main__":
    main()
