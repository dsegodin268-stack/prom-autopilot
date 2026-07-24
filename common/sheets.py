# -*- coding: utf-8 -*-
"""Google Sheets: клієнти та пошук вкладок — спільні для всіх модулів."""
import json
import os
import re


def gclient():
    """gspread-клієнт із сервіс-акаунта (секрет GCP_SA_KEY, JSON)."""
    key = os.environ.get("GCP_SA_KEY")
    if not key:
        return None
    import gspread
    return gspread.service_account_from_dict(json.loads(key)) if key.strip().startswith("{") else None


def open_hub(hub_id):
    """Відкрити книгу за ID зі scope=spreadsheets (для конвеєра додавання)."""
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(hub_id)


def keyf(s):
    """Ключ порівняння назв: пробіли стиснуті, lower."""
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def find_ws(sh, name, create_cols=0):
    """Знайти вкладку за назвою (нечутливо до регістру/пробілів); create_cols>0 — створити."""
    want = keyf(name)
    for ws in sh.worksheets():
        if keyf(ws.title) == want:
            return ws
    for ws in sh.worksheets():
        if want in keyf(ws.title):
            return ws
    if create_cols:
        return sh.add_worksheet(name, rows=2000, cols=create_cols)
    raise SystemExit(f"вкладку {name!r} не знайдено")
