# -*- coding: utf-8 -*-
"""Джерело 3: дилерський прайс AutoNova з Drive-теки.
Теку наповнює Apps Script у таблиці; звідси файл забирає сервіс-акаунт (GCP_SA_KEY).
Секрет AUTONOVA_FOLDER_ID = ID (або повний URL) теки. Підтримує zip і xlsx.
Поштова гілка (IMAP) ВИДАЛЕНА 2026-07-24: дублювала цей канал, вимагала пароль
від усієї скриньки і не вміла розпаковувати zip."""
import io
import json
import os

from common.normalize import num
from repricing.sources.base import keep_best


def _open_xlsx_tolerant(data):
    """Відкриває xlsx; якщо 1С-файл без xl/sharedStrings.xml — додає порожній і пробує ще раз."""
    import openpyxl
    import zipfile
    try:
        return openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        zin = zipfile.ZipFile(io.BytesIO(data))
        buf = io.BytesIO()
        zout = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
        for it in zin.namelist():
            zout.writestr(it, zin.read(it))
        if "xl/sharedStrings.xml" not in zin.namelist():
            zout.writestr("xl/sharedStrings.xml",
                          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                          '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="0" uniqueCount="0"/>')
        zout.close()
        zin.close()
        return openpyxl.load_workbook(io.BytesIO(buf.getvalue()), read_only=True, data_only=True)


def pull_autonova_drive(folder_id, best, instock):
    """Читає найсвіжіший файл 'autonova_latest*' з Drive-теки через сервіс-акаунт."""
    folder_id = (folder_id or "").strip()
    if "/folders/" in folder_id:  # приймаємо і повний URL теки
        folder_id = folder_id.split("/folders/")[1].split("?")[0].split("#")[0].split("/")[0]
    key = os.environ.get("GCP_SA_KEY")
    if not key:
        print("[autonova] нема GCP_SA_KEY — пропуск Drive")
        return
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        creds = Credentials.from_service_account_info(
            json.loads(key), scopes=["https://www.googleapis.com/auth/drive.readonly"])
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        q = "'%s' in parents and trashed=false and name contains 'autonova_latest'" % folder_id
        files = svc.files().list(q=q, fields="files(id,name,modifiedTime,size)",
                                 orderBy="modifiedTime desc", pageSize=5,
                                 supportsAllDrives=True, includeItemsFromAllDrives=True
                                 ).execute().get("files", [])
        if not files:
            print("[autonova] у Drive-теці файлів нема")
            return
        fn = files[0]["name"].lower()
        data = svc.files().get_media(fileId=files[0]["id"]).execute()
        if fn.endswith(".zip"):
            import zipfile
            zf = zipfile.ZipFile(io.BytesIO(data))
            inner = [m for m in zf.namelist() if m.lower().endswith((".xlsx", ".xls"))]
            if not inner:
                print("[autonova] у zip нема xlsx")
                return
            data = zf.read(inner[0])
        elif fn.endswith(".rar"):
            print("[autonova] .rar не підтримується — треба zip")
            return
        from python_calamine import CalamineWorkbook
        cw = CalamineWorkbook.from_filelike(io.BytesIO(data))
        names = cw.sheet_names
        sh = cw.get_sheet_by_name("TDSheet") if "TDSheet" in names else cw.get_sheet_by_index(0)
        rows = sh.to_python(skip_empty_area=False)
        n = 0
        for r in rows:
            if len(r) <= 24 or r[2] in (None, ""):
                continue
            cost = num(r[24])
            if cost <= 0:
                continue
            qty = sum(num(r[c]) for c in range(5, 23) if c < len(r))
            if qty <= 0:
                continue
            keep_best(best, r[2], {"name": str(r[1] or ""), "cost": cost, "qty": qty,
                                   "presence": "available", "brand": "Авто"}, instock)
            n += 1
        print(f"[autonova] Drive '{files[0]['name']}': {n} поз.")
    except Exception as e:
        print(f"[autonova] Drive {str(e)[:140]}")
