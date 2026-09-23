"""Триаж, уровень 1: детерминированная нормализация чисел из речи (ru + kk).

LLM ненадёжно переводит продиктованные числа в цифры («жеті жүз бір» → 717 вместо 701),
поэтому телефон, ИИН и номера собираем кодом и отдаём роутеру и исполнителю готовыми.

    «плюс семь семьсот семь, сто двадцать три, сорок пять, шестьдесят семь» → +77071234567
    «плюс жеті, жеті жүз бір, нөл нөл нөл, нөл нөл, он»                     → +77010000010
"""

import re

UNITS = {
    "ноль": 0, "нуль": 0, "один": 1, "одна": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "нөл": 0, "бір": 1, "екі": 2, "үш": 3, "төрт": 4, "бес": 5, "алты": 6, "жеті": 7, "сегіз": 8, "тоғыз": 9,
}
TEENS = {
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
}
TENS = {
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90,
    "он": 10, "жиырма": 20, "отыз": 30, "қырық": 40, "елу": 50, "алпыс": 60, "жетпіс": 70, "сексен": 80, "тоқсан": 90,
}
HUNDREDS = {
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
    "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
KK_HUNDRED = "жүз"
PLUS = {"плюс", "плюс-", "+"}


class _Num:
    """Собирает одно число из слов по разрядам; если слово не помещается — число закрывается."""

    def __init__(self) -> None:
        self.value = 0
        self.has = {"h": False, "t": False, "u": False}

    def empty(self) -> bool:
        return not any(self.has.values())

    def add(self, word: str) -> bool:
        if word in HUNDREDS:
            if not self.empty():
                return False
            self.value, self.has["h"] = HUNDREDS[word], True
            return True
        if word == KK_HUNDRED:  # «жеті жүз» = 700, «жүз» = 100
            if self.has["h"] or self.has["t"]:
                return False
            self.value = (self.value or 1) * 100
            self.has = {"h": True, "t": False, "u": False}
            return True
        if word in TEENS:
            if self.has["t"] or self.has["u"]:
                return False
            self.value += TEENS[word]
            self.has["t"] = self.has["u"] = True
            return True
        if word in TENS:
            if self.has["t"] or self.has["u"]:
                return False
            self.value += TENS[word]
            self.has["t"] = True
            return True
        if word in UNITS:
            if UNITS[word] == 0:
                return False  # ноль всегда отдельная цифра
            if self.has["u"]:
                return False
            self.value += UNITS[word]
            self.has["u"] = True
            return True
        return False

    def text(self) -> str:
        return str(self.value)


WORD = re.compile(r"\+|[^\W\d_]+", re.UNICODE)


def _is_number_word(low: str) -> bool:
    return low in UNITS or low in TEENS or low in TENS or low in HUNDREDS or low == KK_HUNDRED


def spoken_to_digits(text: str) -> str:
    """Заменяет числа словами на цифры; весь остальной текст (госномера, коды, пунктуация) не трогает."""
    pieces: list[str] = []
    last = 0
    cur: _Num | None = None

    def flush() -> None:
        nonlocal cur
        if cur and not cur.empty():
            pieces.append(cur.text())
        cur = None

    for m in WORD.finditer(text):
        low = m.group(0).lower()
        if low not in PLUS and not _is_number_word(low):
            continue
        gap = text[last:m.start()]
        # Между словами одного числа — только пробелы; запятая или другой текст закрывают число.
        if cur is not None and gap.strip():
            flush()
        if cur is None or gap.strip():
            pieces.append(gap)
        if low in PLUS:
            flush()
            pieces.append("+")
        elif low in UNITS and UNITS[low] == 0:
            flush()
            pieces.append(" 0" if pieces and pieces[-1] and pieces[-1][-1].isdigit() else "0")
        else:
            if cur is None:
                cur = _Num()
                if pieces and pieces[-1] and pieces[-1][-1].isdigit():
                    pieces.append(" ")
            elif not cur.add(low):
                flush()
                pieces.append(" ")
                cur = _Num()
                cur.add(low)
                last = m.end()
                continue
            if cur.empty():
                cur.add(low)
        last = m.end()
    flush()
    pieces.append(text[last:])
    return "".join(pieces)


PHONE_RUN = re.compile(r"\+?\d[\d\s,.\-()]{8,}\d")


def extract(text: str) -> dict:
    """Возвращает нормализованный текст и найденные идентификаторы (телефон, ИИН, полис, госномер, заявление)."""
    norm = spoken_to_digits(text)
    found: dict[str, str | list[str]] = {}
    for run in PHONE_RUN.findall(norm):
        digits = re.sub(r"\D", "", run)
        if len(digits) == 11 and digits[0] in "78":
            found.setdefault("phone", "+7" + digits[1:])
        elif len(digits) == 10 and digits[0] == "7":
            found.setdefault("phone", "+7" + digits)
    iins = re.findall(r"(?<!\d)\d{12}(?!\d)", norm)
    if iins:
        found["iin"] = iins[0]
        if len(iins) > 1:
            found["drivers_iin"] = iins
    if m := re.search(r"\bSQ[\s-]*(OGPO|CASCO|TRVL|PROP|NS|DMS)[\s-]*(\d{6})\b", norm, re.I):
        found["policy_number"] = f"SQ-{m.group(1).upper()}-{m.group(2)}"
    if m := re.search(r"\bCL[\s-]*(\d{6})\b", norm, re.I):
        found["claim_number"] = f"CL-{m.group(1)}"
    if m := re.search(r"\b(\d{3}\s?[A-ZА-Я]{2,3}\s?\d{2})\b", norm.upper()):
        found["vehicle_plate"] = re.sub(r"\s", "", m.group(1))
    return {"text": norm, "ids": found}
