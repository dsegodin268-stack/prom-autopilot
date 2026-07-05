"""Авто-забір прайсів із пошти (IMAP). Постачальники шлють .xlsx у листах.
Продакшн: MAIL_USER/MAIL_PASS (app-password) у секретах. Бере НАЙСВІЖІШИЙ лист від
відправника за since_days, витягує вкладення, парсить за мапою колонок постачальника."""
import imaplib, email, os, tempfile, datetime
from email.header import decode_header
from suppliers.excel import parse_excel
def _decode(s):
    if not s: return ""
    return "".join(p.decode(enc or "utf-8","ignore") if isinstance(p,bytes) else p for p,enc in decode_header(s))
def fetch_supplier_attachments(name, scfg, base):
    user=os.environ.get(scfg.get("user_env","MAIL_USER")); pw=os.environ.get(scfg.get("password_env","MAIL_PASS"))
    if not user or not pw:
        print(f"[email:{name}] нема креденшелів — пропуск"); return []
    host=scfg.get("host","imap.gmail.com"); sender=scfg.get("email_from"); since=int(scfg.get("since_days",5))
    cols=scfg.get("columns",{"article":0,"name":1,"qty":2,"cost":3}); brand=scfg.get("brand","")
    date=(datetime.date.today()-datetime.timedelta(days=since)).strftime("%d-%b-%Y")
    items=[]
    try:
        M=imaplib.IMAP4_SSL(host); M.login(user,pw); M.select(scfg.get("folder","INBOX"))
        crit=f'(FROM "{sender}" SINCE {date})' if sender else f'(SINCE {date})'
        typ,data=M.search(None,crit); ids=data[0].split()
        for num in reversed(ids):                       # найсвіжіший першим
            _,d=M.fetch(num,"(RFC822)"); msg=email.message_from_bytes(d[0][1])
            got=False
            for part in msg.walk():
                fn=_decode(part.get_filename())
                if fn and fn.lower().endswith((".xlsx",".xls")):
                    p=os.path.join(tempfile.gettempdir(),f"{name}_{fn}")
                    open(p,"wb").write(part.get_payload(decode=True))
                    items+=parse_excel(p, cols, brand); got=True
            if got: break                                # взяли останній лист із вкладенням
        M.logout()
    except Exception as e:
        print(f"[email:{name}] помилка: {str(e)[:70]}")
    print(f"[email:{name}] отримано {len(items)} позицій"); return items
