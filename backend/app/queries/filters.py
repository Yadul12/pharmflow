from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.config import DATASET_END, DATASET_START


@dataclass
class AnalyticsFilter:
    start_date: date = DATASET_START
    end_date: date = DATASET_END
    city: str | None = None
    city_tier: str | None = None
    channel: str | None = None
    device: str | None = None
    category_id: int | None = None
    customer_type: str | None = None  # 'new' | 'repeat' | None
    segment: str | None = None

    def normalized(self) -> "AnalyticsFilter":
        s = max(DATASET_START, min(self.start_date, DATASET_END))
        e = max(s, min(self.end_date, DATASET_END))
        return AnalyticsFilter(
            start_date=s,
            end_date=e,
            city=self.city or None,
            city_tier=self.city_tier or None,
            channel=self.channel or None,
            device=self.device or None,
            category_id=self.category_id,
            customer_type=self.customer_type if self.customer_type in ("new", "repeat") else None,
            segment=self.segment or None,
        )

    def prior_period(self) -> tuple[date, date]:
        span = (self.end_date - self.start_date).days + 1
        prev_end = self.start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        return (prev_start, prev_end)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "city": self.city,
            "city_tier": self.city_tier,
            "channel": self.channel,
            "device": self.device,
            "category_id": self.category_id,
            "customer_type": self.customer_type,
            "segment": self.segment,
        }


def build_session_where(f: AnalyticsFilter, alias: str = "sf", start_override: date | None = None, end_override: date | None = None) -> tuple[str, list[Any]]:
    clauses = [f"{alias}.session_date BETWEEN %s AND %s"]
    params: list[Any] = [start_override or f.start_date, end_override or f.end_date]

    if f.city:
        clauses.append(f"{alias}.city = %s")
        params.append(f.city)
    if f.city_tier:
        clauses.append(f"{alias}.city_tier = %s")
        params.append(f.city_tier)
    if f.channel:
        clauses.append(f"{alias}.acquisition_channel = %s")
        params.append(f.channel)
    if f.device:
        clauses.append(f"{alias}.device_type = %s")
        params.append(f.device)
    if f.category_id is not None:
        clauses.append(f"{alias}.primary_category_id = %s")
        params.append(f.category_id)
    if f.customer_type == "new":
        clauses.append(f"{alias}.is_new_customer_session = TRUE")
    elif f.customer_type == "repeat":
        clauses.append(f"{alias}.is_new_customer_session = FALSE")

    return " AND ".join(clauses), params


def build_order_where(f: AnalyticsFilter, alias: str = "o", start_override: date | None = None, end_override: date | None = None) -> tuple[str, list[Any]]:
    clauses = [f"{alias}.order_date BETWEEN %s AND %s"]
    params: list[Any] = [start_override or f.start_date, end_override or f.end_date]

    if f.city:
        clauses.append(f"{alias}.city = %s")
        params.append(f.city)
    if f.city_tier:
        clauses.append(f"{alias}.city_tier = %s")
        params.append(f.city_tier)
    if f.channel:
        clauses.append(f"{alias}.acquisition_channel = %s")
        params.append(f.channel)
    if f.device:
        clauses.append(f"{alias}.device_type = %s")
        params.append(f.device)
    if f.category_id is not None:
        clauses.append(f"{alias}.primary_category_id = %s")
        params.append(f.category_id)
    if f.customer_type == "new":
        clauses.append(f"{alias}.is_first_order = TRUE")
    elif f.customer_type == "repeat":
        clauses.append(f"{alias}.is_first_order = FALSE")

    return " AND ".join(clauses), params


def build_customer_where(f: AnalyticsFilter, alias: str = "cl") -> tuple[str, list[Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if f.city:
        clauses.append(f"{alias}.primary_city = %s")
        params.append(f.city)
    if f.city_tier:
        clauses.append(f"{alias}.city_tier = %s")
        params.append(f.city_tier)
    if f.channel:
        clauses.append(f"{alias}.acquisition_channel = %s")
        params.append(f.channel)
    if f.device:
        clauses.append(f"{alias}.primary_device = %s")
        params.append(f.device)
    if f.category_id is not None:
        clauses.append(f"{alias}.first_order_category_id = %s")
        params.append(f.category_id)
    return " AND ".join(clauses), params
