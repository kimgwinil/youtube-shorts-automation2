from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo


@dataclass
class DailyContext:
    date_iso: str
    weekday_name_ko: str
    season_ko: str
    weather_summary_ko: str
    mood_hint: str
    location_name: str
    is_weekend: bool


def build_daily_context(
    timezone_name: str,
    location_name: str,
    latitude: float,
    longitude: float,
) -> DailyContext:
    now = datetime.now(ZoneInfo(timezone_name))
    weather = _fetch_weather(latitude, longitude)
    weekday_name = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][now.weekday()]
    season = _season_ko(now.month)
    mood_hint = _mood_from_weather(weather, now.weekday())
    return DailyContext(
        date_iso=now.strftime("%Y-%m-%d"),
        weekday_name_ko=weekday_name,
        season_ko=season,
        weather_summary_ko=_weather_summary(weather, season),
        mood_hint=mood_hint,
        location_name=location_name,
        is_weekend=now.weekday() >= 5,
    )


def _fetch_weather(latitude: float, longitude: float) -> dict[str, Any]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=temperature_2m,weather_code,is_day,precipitation"
        "&timezone=auto"
    )
    try:
        with urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("current", {})
    except URLError:
        return {}


def _season_ko(month: int) -> str:
    if month in (3, 4, 5):
        return "봄"
    if month in (6, 7, 8):
        return "여름"
    if month in (9, 10, 11):
        return "가을"
    return "겨울"


def _weather_summary(weather: dict[str, Any], season: str) -> str:
    if not weather:
        return f"{season}의 공기와 하루의 흐름"
    code = int(weather.get("weather_code", 0))
    precipitation = float(weather.get("precipitation", 0.0))
    temperature = weather.get("temperature_2m")
    base = _weather_code_ko(code)
    if precipitation > 0.2:
        base = "비가 내리는 날"
    if temperature is not None:
        return f"{base}, 기온 약 {round(float(temperature))}도"
    return base


def _mood_from_weather(weather: dict[str, Any], weekday: int) -> str:
    if not weather:
        return "city" if weekday < 5 else "dawn"
    precipitation = float(weather.get("precipitation", 0.0))
    code = int(weather.get("weather_code", 0))
    if precipitation > 0.2 or code in {51, 53, 55, 61, 63, 65, 80, 81, 82}:
        return "rain"
    if weekday < 5:
        return "city"
    return "dawn"


def _weather_code_ko(code: int) -> str:
    mapping = {
        0: "맑은 날",
        1: "대체로 맑은 날",
        2: "구름이 드문드문 있는 날",
        3: "흐린 날",
        45: "안개 낀 날",
        48: "짙은 안개 낀 날",
        51: "이슬비가 내리는 날",
        53: "비가 잔잔하게 내리는 날",
        55: "비가 이어지는 날",
        61: "비 오는 날",
        63: "비가 제법 오는 날",
        65: "강한 비가 오는 날",
        80: "소나기 오는 날",
        81: "잦은 소나기 오는 날",
        82: "강한 소나기 오는 날",
    }
    return mapping.get(code, "하늘의 분위기가 변하는 날")
