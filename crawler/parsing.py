from __future__ import annotations

import re
from typing import Iterable

from .models import (
    PLATFORM_INSTAGRAM,
    PLATFORM_LINKEDIN,
    PLATFORM_X,
    PLATFORM_YOUTUBE,
    SourceAccount,
)


PLATFORM_ALIASES = {
    "x": PLATFORM_X,
    "twitter": PLATFORM_X,
    "youtube": PLATFORM_YOUTUBE,
    "linkedin": PLATFORM_LINKEDIN,
    "instagram": PLATFORM_INSTAGRAM,
}


def normalize_platform(value: str) -> str:
    key = value.strip().lower()
    if key not in PLATFORM_ALIASES:
        raise ValueError(f"unsupported platform: {value}")
    return PLATFORM_ALIASES[key]


def split_platform_account(raw: str) -> tuple[list[str], str]:
    if "-" not in raw:
        raise ValueError(f"account field must be '<platform>-<name>': {raw}")
    platform_text, account_name = raw.split("-", 1)
    platforms = [normalize_platform(part) for part in platform_text.split("/")]
    return platforms, account_name.strip()


def parse_wan_number_to_int(value: str) -> int | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*万", value or "")
    if not match:
        match_yi = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*亿", value or "")
        if match_yi:
            return int(float(match_yi.group(1)) * 100_000_000)
        return None
    return int(float(match.group(1)) * 10_000)


def parse_platform_average_views(raw_average: str, platform: str) -> int | None:
    text = raw_average or ""
    platform_labels = {
        PLATFORM_X: ["X 平台", "X平台"],
        PLATFORM_YOUTUBE: ["YouTube 平台", "YouTube平台"],
        PLATFORM_LINKEDIN: ["LinkedIn 平台", "LinkedIn平台"],
        PLATFORM_INSTAGRAM: ["Instagram 平台", "Instagram平台"],
    }[platform]

    for label in platform_labels:
        match = re.search(rf"{re.escape(label)}\s*([0-9]+(?:\.[0-9]+)?)\s*万", text, re.IGNORECASE)
        if match:
            return int(float(match.group(1)) * 10_000)
    return parse_wan_number_to_int(text)


def parse_threshold_views(raw_threshold: str) -> int | None:
    return parse_wan_number_to_int(raw_threshold or "")


def parse_threshold_engagement_rate(raw_threshold: str) -> float | None:
    match = re.search(r"互动率\s*≥\s*([0-9]+(?:\.[0-9]+)?)%", raw_threshold or "")
    if not match:
        return None
    return float(match.group(1)) / 100.0


def detect_quality_issue(raw_account: str, raw_average: str, platforms: Iterable[str]) -> str | None:
    platform_label_by_key = {
        PLATFORM_X: "X",
        PLATFORM_YOUTUBE: "YouTube",
        PLATFORM_LINKEDIN: "LinkedIn",
        PLATFORM_INSTAGRAM: "Instagram",
    }
    raw_average_lower = (raw_average or "").lower()
    issues: list[str] = []
    for platform in platforms:
        label = platform_label_by_key[platform].lower()
        if "/" in raw_account and "平台" in (raw_average or "") and label not in raw_average_lower:
            issues.append(f"{platform} missing from average view field")
    if "instagram" in raw_account.lower() and "youtube" in raw_average_lower:
        issues.append("account platform says Instagram but average view field references YouTube")
    return "; ".join(dict.fromkeys(issues)) or None


def row_to_accounts(headers: list[str], row: tuple[object, ...], excel_row_number: int) -> list[SourceAccount]:
    data = {headers[index]: row[index] if index < len(row) else None for index in range(len(headers))}
    sequence = data.get("序号")
    if not isinstance(sequence, int):
        return []

    raw_account = str(data.get("外网账号（平台 + 名称）") or "").strip()
    platforms, account_name = split_platform_account(raw_account)
    raw_average = str(data.get("2026 平台单条平均阅读量") or "").strip()
    raw_threshold = str(data.get("内容筛选门槛（贴合平均值）") or "").strip()
    quality_issue = detect_quality_issue(raw_account, raw_average, platforms)

    accounts: list[SourceAccount] = []
    for platform in platforms:
        accounts.append(
            SourceAccount(
                category=str(data.get("分类") or "").strip(),
                platform=platform,
                account_name=account_name,
                original_account=raw_account,
                official_identity=str(data.get("原账号 2026 官方身份") or "").strip(),
                radar_name=str(data.get("雷达号名称") or "").strip(),
                radar_persona=str(data.get("雷达号专属人设简介") or "").strip(),
                threshold_views=parse_threshold_views(raw_threshold),
                threshold_engagement_rate=parse_threshold_engagement_rate(raw_threshold),
                average_views=parse_platform_average_views(raw_average, platform),
                raw_average_views=raw_average,
                raw_threshold=raw_threshold,
                source_row_number=excel_row_number,
                data_quality_issue=quality_issue,
            )
        )
    return accounts
