#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор КАНОН.md (запуск: python -m tools.rulebook [шлях]).

Навіщо. Правила й канон живуть у коді — adding/rules.py та adding/canon.py.
Але власнику потрібен текст, який можна відкрити й прочитати, не заходячи в
Python. Спокуса написати такий текст руками величезна — і саме так з'являється
друга копія правил, яка через місяць тихо розходиться з першою.

Тому документ ГЕНЕРУЄТЬСЯ. Правити треба код; КАНОН.md перезбирається однією
командою і завжди дорівнює тому, за чим реально ріже конвеєр.
"""
import sys

from adding.rules import rulebook_md

DEFAULT = "КАНОН.md"


def main():
    path = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT).strip() or DEFAULT
    md = rulebook_md()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"[rulebook] {path}: {len(md)} символів, {md.count(chr(10))} рядків")


if __name__ == "__main__":
    main()
