from __future__ import annotations

import json
from datetime import date, time, timedelta

import pytest

from bot.config import DEFAULT_CITIES, ConfigError, City, load_settings, parse_cities, parse_int_list, parse_time
from bot.days import build_title, human_date, kazakh_day, russian_day
from bot.friends import (
    Friend,
    age_on,
    birthdays_on,
    load_friends,
    next_birthday,
    parse_birthday,
    parse_friends,
    upcoming_birthdays,
)

# 2026-10-26 — понедельник
MONDAY = date(2026, 10, 26)


class TestDays:
    def test_all_week_in_kazakh(self):
        week = [kazakh_day(MONDAY + timedelta(days=i)) for i in range(7)]
        assert week == ["Дүйсенбі", "Сейсенбі", "Сәрсенбі", "Бейсенбі", "Жұма", "Сенбі", "Жексенбі"]

    def test_russian_day_and_date(self):
        assert russian_day(MONDAY) == "Понедельник"
        assert human_date(date(2026, 3, 8)) == "8 марта"

    def test_title_template(self):
        assert build_title("{day}", MONDAY) == "Дүйсенбі"
        assert build_title("Достар | {day} {date}", MONDAY) == "Достар | Дүйсенбі 26.10"
        assert build_title("{day_ru}", MONDAY) == "Понедельник"

    def test_title_empty_and_long(self):
        assert build_title("   ", MONDAY) == "Дүйсенбі"
        assert len(build_title("x" * 300, MONDAY)) == 128


class TestConfig:
    def test_defaults(self):
        s = load_settings({"TELEGRAM_BOT_TOKEN": "t"})
        assert s.chat_ids == ()
        assert s.cities == DEFAULT_CITIES
        assert s.morning_time == time(8, 0)
        assert s.timezone.key == "Asia/Almaty"
        assert s.ai_api_key is None
        assert s.port is None
        assert s.delete_title_service_msg is True

    def test_full(self):
        s = load_settings({
            "TELEGRAM_BOT_TOKEN": "t", "CHAT_IDS": "-1001, -1002", "ADMIN_IDS": "5;6",
            "MORNING_TIME": "07:30", "AI_API_KEY": " k ", "PORT": "8080",
            "DELETE_TITLE_SERVICE_MSG": "no", "BIRTHDAY_REMIND_DAYS": "0",
        })
        assert s.chat_ids == (-1001, -1002)
        assert s.admin_ids == (5, 6)
        assert s.morning_time == time(7, 30)
        assert s.ai_api_key == "k"
        assert s.port == 8080
        assert s.delete_title_service_msg is False
        assert s.birthday_remind_days == 0

    def test_missing_token(self):
        with pytest.raises(ConfigError):
            load_settings({})

    @pytest.mark.parametrize(
        "env",
        [
            {"PORT": "abc"},
            {"BIRTHDAY_REMIND_DAYS": "x"},
            {"TZ_NAME": "Asia/Nowhere"},
            {"TITLE_TEMPLATE": "{weekday}"},
            {"TITLE_TEMPLATE": "Достар {"},
        ],
    )
    def test_bad_numbers(self, env):
        with pytest.raises(ConfigError):
            load_settings({"TELEGRAM_BOT_TOKEN": "t", **env})

    def test_parsers(self):
        assert parse_int_list("", "X") == ()
        assert parse_time(" 9:05 ", "X") == time(9, 5)
        assert parse_cities("Шымкент:42.3:69.6; ;") == (City("Шымкент", 42.3, 69.6),)
        with pytest.raises(ConfigError):
            parse_int_list("1,a", "X")
        with pytest.raises(ConfigError):
            parse_time("утром", "X")
        with pytest.raises(ConfigError):
            parse_cities("Шымкент:42.3")


class TestFriends:
    def test_parse_birthday(self):
        assert parse_birthday("15.03") == (15, 3, None)
        assert parse_birthday("29.02.1996") == (29, 2, 1996)
        for bad in ("15", "31.02", "15-03-1998", "1.2.3.4"):
            with pytest.raises(ValueError):
                parse_birthday(bad)

    def test_parse_friends(self):
        friends = parse_friends({"friends": [
            {"name": "Айдос", "username": "@aidos", "birthday": "15.03.1998"},
            {"name": "Без даты"},
        ]})
        assert friends[0] == Friend("Айдос", "aidos", 15, 3, 1998)
        assert friends[0].mention == "@aidos"
        assert friends[1].mention == "Без даты"
        assert not friends[1].has_birthday
        with pytest.raises(ValueError):
            parse_friends({"friends": [{"username": "x"}]})

    def test_load_friends(self, tmp_path):
        assert load_friends(tmp_path / "missing.json") == ()
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert load_friends(broken) == ()
        good = tmp_path / "good.json"
        good.write_text(json.dumps({"friends": [{"name": "Дана", "birthday": "02.11"}]}), encoding="utf-8")
        assert load_friends(good) == (Friend("Дана", None, 2, 11),)

    def test_leap_day_birthday(self):
        erlan = Friend("Ерлан", birth_day=29, birth_month=2)
        assert birthdays_on((erlan,), date(2027, 2, 28)) == (erlan,)
        assert birthdays_on((erlan,), date(2028, 2, 28)) == ()
        assert birthdays_on((erlan,), date(2028, 2, 29)) == (erlan,)

    def test_next_birthday_and_age(self):
        dana = Friend("Дана", birth_day=2, birth_month=1, birth_year=2000)
        assert next_birthday(dana, date(2026, 10, 30)) == date(2027, 1, 2)
        assert next_birthday(dana, date(2027, 1, 2)) == date(2027, 1, 2)
        assert age_on(dana, date(2027, 1, 2)) == 27
        assert age_on(Friend("X"), date(2027, 1, 2)) is None

    def test_upcoming(self):
        a = Friend("A", birth_day=5, birth_month=11)
        b = Friend("B", birth_day=1, birth_month=11)
        c = Friend("C", birth_day=1, birth_month=6)
        result = upcoming_birthdays((a, b, c, Friend("D")), date(2026, 10, 30), 10)
        assert [f.name for f, _ in result] == ["B", "A"]
