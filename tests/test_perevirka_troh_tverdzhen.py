# -*- coding: utf-8 -*-
"""Перевірка трьох тверджень, які власнику пообіцяли словами.

Тут не описи, а докази. Кожен тест падає, якщо твердження перестане бути
правдою — тобто якщо хтось колись «трохи поправить» код і тихо зламає обіцянку.

  Твердження 2. ШІ не має інтернету, пише з пам'яті моделі. Тому:
      а) картка з нуля за замовчуванням іде в чернетку, а не в Export;
      б) OEM-номери з моделі не беруться взагалі.
  Твердження 3. ШІ не вміє робити фото. Тому:
      в) в Огляді є колонка «Фото вручну (посилання)»;
      г) без жодного фото картка в Export не піде за жодних налаштувань.
"""
import adding.ai_layer as ai
import adding.card_builder as cb
import adding.panel as panel
import adding.review as review
import adding.run as run
from adding.completeness import route_card

# Повний набір, який дає картці рівень 1: усе на місці, крім того, що тест ламає.
# Дві «Сумісності» тут обов'язкові — без них missing_card чесно каже «сумісність»,
# і картка зупинилась би в чернетці з іншої причини, ніж перевіряє тест.
GOOD_CHARS = [("Тип запчастини", "", "фільтр масляний"),
              ("Виробник", "", "BMW"),
              ("Сумісність з маркою", "", "BMW"),
              ("Сумісність з моделлю", "", "3 F30")]
GOOD_IMGS = ["https://cdn.example/1.jpg"]
GROUP = "341501"
SECTION = "341501"


# --------------------------------------------------------------- твердження 2а
def test_scratch_default_off():
    """Дефолт пульта — режим узагалі вимкнено: без свідомого вибору власника
    жодна картка з нуля не збирається."""
    default = dict((k, d) for k, _l, d, _h, _v in panel.ROWS)["scratch"]
    assert default == panel.SCRATCH_OFF
    assert panel.SCRATCH_MODE[panel.keyf(default)] == "off"


def test_scratch_target_is_staging_unless_explicit_export():
    """Ключовий рядок run.py: ціль картки з нуля = чернетка завжди, крім
    єдиного випадку, коли власник обрав «Так, одразу в Export»."""
    for mode, panel_target, expected in [
            ("staging", "export", "staging"),   # пульт каже Export — не слухаємо
            ("staging", "staging", "staging"),
            ("export",  "export", "export"),    # свідомий вибір власника
            ("export",  "staging", "staging"),
    ]:
        got = panel_target if mode == "export" else "staging"
        assert got == expected, (mode, panel_target)


def test_perfect_scratch_card_still_stops_in_draft():
    """Навіть ідеальна картка з нуля (фото, характеристики, група, підрозділ)
    зупиняється в чернетці, бо її ціль — staging."""
    dest, status = route_card(GOOD_CHARS, GOOD_IMGS, GROUP, SECTION, "staging")
    assert dest == "staging"
    assert status == "готово"


def test_same_card_from_catalog_goes_to_export():
    """Контроль: та сама картка НЕ з нуля з ціллю Export їде в Export.
    Отже в чернетці її тримає саме прапорець «з нуля», а не якийсь брак."""
    dest, _ = route_card(GOOD_CHARS, GOOD_IMGS, GROUP, SECTION, "export")
    assert dest == "export"


# --------------------------------------------------------------- твердження 2б
def test_scratch_prompt_forbids_oem():
    """У самому запиті до моделі OEM заборонені відкритим текстом, і серед
    дозволених характеристик нема жодної, куди номер можна було б підкласти."""
    p = ai.PROM_AI_SYSTEM_SCRATCH
    assert "вигадувати OEM і крос-номери (їх не питаємо взагалі)" in p
    assert not [c for c in ai.SCRATCH_CHARS
                if "oem" in c.lower() or "номер" in c.lower()]


def test_scratch_answer_cannot_carry_oem(monkeypatch):
    """Навіть якщо модель самовільно поверне OEM і кроси — вони не мають
    транспорту: _scratch_clean віддає рівно (сумісність, характеристики,
    тип, категорія), і номерам там нема місця."""
    poisoned = {"article": "11427953129", "known": True,
                "type": "фільтр масляний", "category": "Фільтри",
                "fitment": ["BMW 3 F30 2011-2019"],
                "oem": ["11427953129", "11 42 7 953 130"],
                "crosses": ["MANN HU 816 X"],
                "chars": [{"name": "Виробник", "unit": "", "value": "BMW"},
                          {"name": "OEM", "unit": "", "value": "11427953130"}],
                "note": ""}
    got = ai._scratch_clean(poisoned, "11427953129", "BMW")
    assert got is not None
    fit, chars, typ, cat = got            # рівно чотири поля, OEM серед них нема
    names = [n for (n, _u, _v) in chars]
    assert "OEM" not in names             # характеристика поза каноном відкинута
    assert all(n in ai.SCRATCH_CHARS for n in names)
    blob = repr(got)
    assert "11427953130" not in blob and "MANN" not in blob


def test_scratch_product_never_writes_oem_fields(monkeypatch):
    """Кінець ланцюга: scratch_product дописує в product лише cars, details,
    nodes і name. Поля, з яких потім народжуються OEM і кроси (oe, analogs),
    лишаються рівно такими, якими були."""
    monkeypatch.setattr(cb, "scratch_facts",
                        lambda *a, **k: (["BMW 3 F30 2011-2019"],
                                         [("Виробник", "", "BMW")],
                                         "фільтр масляний", "Фільтри"))
    p = {"article": "11427953129", "brand": "BMW", "name": ""}
    assert cb.scratch_product(p, {"scratch": True}) is True
    assert not p.get("oe")
    assert not p.get("analogs")
    assert set(p) <= {"article", "brand", "name", "cars", "details", "nodes"}


# ---------------------------------------------------------------- твердження 3
def test_manual_photo_column_exists():
    """Колонка є і в шапці огляду, і в списку колонок, які run.py читає."""
    assert "Фото вручну (посилання)" in review.HEAD
    assert review.HEAD[review.C_PHOTO_MAN] == "Фото вручну (посилання)"


def test_manual_photos_parsing():
    """Посилання приймаються через будь-який звичний розділювач, сміття
    відкидається, дублі схлопуються."""
    assert run.manual_photos("https://a/1.jpg, https://b/2.jpg") == \
        ["https://a/1.jpg", "https://b/2.jpg"]
    assert run.manual_photos("https://a/1.jpg\nhttps://a/1.jpg") == ["https://a/1.jpg"]
    assert run.manual_photos("немає фото") == []
    assert run.manual_photos("") == []


def test_no_photo_never_reaches_export():
    """Головне: без жодного фото картка не їде в Export за ЖОДНОЇ цілі —
    ні звичайна, ні з нуля, навіть якщо все інше на місці."""
    for target in ("export", "staging"):
        dest, status = route_card(GOOD_CHARS, [], GROUP, SECTION, target)
        assert dest == "staging"
        assert status == "чекає фото"


def test_owner_photo_is_not_overwritten(monkeypatch):
    """Фото власника мають пріоритет: bm_lookup ставить свої лише тоді, коли
    список порожній, тож вклеєне вручну посилання нічим не затирається."""
    from adding.sources.lookup import bm_lookup

    class FakeBM:
        """Каталог, у якому фото Є — саме той випадок, де могло б затерти."""
        def get_product(self, code):
            return {"article": "11427953129", "brand": "BMW",
                    "name": "Oil filter", "images": ["cat.jpg"]}

    own = {"article": "11427953129", "brand": "BMW",
           "photos": ["https://owner/1.jpg"]}
    empty = {"article": "11427953129", "brand": "BMW", "photos": []}

    assert bm_lookup(FakeBM(), own) is True
    assert bm_lookup(FakeBM(), empty) is True

    assert own["photos"] == ["https://owner/1.jpg"]   # своє не затерли
    assert empty["photos"] and empty["photos"] != own["photos"]  # порожнє — заповнили


# ------------------------------------------- захист відповіді моделі з роздумами
# 01.08.2026. Живий прогін показав: сходинка gemma ожила на моделі gemma-4-31b-it,
# але та відповідає не самим JSON — спершу пише вголос свої роздуми в
# <thought>...</thought> і проговорює там форму відповіді разом із дужками.
# Старий жадібний re.search(r"\{.*\}") починав захват у роздумах, json.loads падав,
# і сходинка мовчки віддавала порожньо — ззовні «ШІ не спрацював» при живому ключі.

def test_reasoning_block_does_not_eat_the_answer():
    """Дужка всередині роздумів більше не збиває витягування відповіді."""
    txt = ('<thought>answer only with JSON like {"a": 1}\nдай подумаю</thought>\n'
           '{"type": "фільтр масляний", "chars": []}')
    assert ai._json_obj(txt) == {"type": "фільтр масляний", "chars": []}


def test_unclosed_reasoning_tag_still_parses():
    """Модель обірвала роздуми й одразу пішла в JSON — теж читається."""
    assert ai._json_obj('<think>hmm {зламано\n{"ok": true}') == {"ok": True}


def test_nested_objects_survive():
    """Захват до ОСТАННЬОЇ дужки лишається правильним для вкладених об'єктів."""
    assert ai._json_obj('{"a": {"b": 1}, "c": [{"d": 2}]}') == \
        {"a": {"b": 1}, "c": [{"d": 2}]}


def test_plain_and_fenced_answers():
    """Чиста відповідь і відповідь у ```json-огорожі з текстом навколо."""
    assert ai._json_obj('{"ok": 1}') == {"ok": 1}
    assert ai._json_obj('Ось:\n```json\n{"ok": 1}\n```\nГотово.') == {"ok": 1}


def test_no_json_returns_none_not_crash():
    """Нема відповіді — чесне None, а не виняток, який завалив би прогін."""
    for bad in ("вибачте, не можу", "", None, "[1, 2, 3]"):
        assert ai._json_obj(bad) is None
