#!/usr/bin/env python3
"""Ein Durchlauf: prüft die Konsentas-Seite und pusht via ntfy, wenn Termine frei sind.
Wird von GitHub Actions alle ~5 Minuten gestartet."""
import os
import re
import sys
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

URL = "https://stuttgart.konsentas.de/form/3/?signup_new=1"
SERVICE = "Erstantrag"
CATEGORY = "Führerscheinstelle"
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
EVENT = os.environ.get("EVENT", "")

NO_SLOT_HINTS = [
    "keine termine",
    "keine freien termine",
    "derzeit keine",
    "aktuell keine",
    "keine verfügbaren",
    "nicht verfügbar",
    "no appointments",
]
TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def notify(title, message, priority=5):
    try:
        requests.post(
            "https://ntfy.sh",
            json={
                "topic": TOPIC,
                "title": title,
                "message": message,
                "priority": priority,
                "tags": ["rotating_light"],
                "click": URL,
            },
            timeout=15,
        ).raise_for_status()
        log(f"ntfy gesendet: {title}")
    except Exception as e:
        log(f"ntfy fehlgeschlagen: {e}")


def check(page):
    page.goto(URL, wait_until="networkidle", timeout=45000)

    label = page.get_by_text(re.compile(SERVICE, re.I)).first
    if not label.is_visible():
        page.get_by_text(CATEGORY, exact=True).first.click()
        page.wait_for_timeout(1000)
    label.wait_for(timeout=15000)

    box = (
        label.locator("xpath=ancestor::*[.//input[@type='checkbox']][1]")
        .locator("input[type=checkbox]")
        .first
    )
    try:
        box.check(force=True, timeout=5000)
    except Exception:
        label.click()

    page.get_by_text("Weiter", exact=True).first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)

    text = page.inner_text("body")
    log("Seitentext (Anfang): " + text[:300].replace("\n", " | "))

    if any(h in text.lower() for h in NO_SLOT_HINTS):
        return "none"
    if TIME_RE.search(text):
        return "slots"
    return "unknown"


def main():
    if not TOPIC:
        log("NTFY_TOPIC fehlt (GitHub Secret nicht gesetzt?)")
        sys.exit(1)

    if EVENT == "workflow_dispatch":
        notify("Termin-Watcher eingerichtet", "Test klappt. Ab jetzt wird alle ~5 Min geprüft.", priority=3)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_context(locale="de-DE").new_page()
        try:
            state = check(page)
            log(f"Status: {state}")
            if state == "slots":
                notify("TERMIN FREI!", "Jetzt buchen, die sind schnell weg.")
            elif state == "unknown" and datetime.utcnow().minute < 10:
                # höchstens ca. 1x pro Stunde, damit es nicht nervt
                notify("Seite hat sich verändert", "Kein 'keine Termine'-Text mehr, schau mal nach.", priority=3)
        except Exception as e:
            log(f"Fehler: {e}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
