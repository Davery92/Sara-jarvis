"""Term calculations for Temerant."""

from __future__ import annotations

import calendar
from datetime import date
from typing import List

from sqlalchemy.orm import Session

from app.models.temerant import TemerantDailyState, TemerantTerm
from app.services.temerant.rules_engine import TemerantRulesEngine


class TermService:
    @staticmethod
    def first_day(d: date) -> date:
        return date(d.year, d.month, 1)

    @staticmethod
    def month_bounds(d: date) -> tuple[date, date]:
        first = date(d.year, d.month, 1)
        last_day = calendar.monthrange(d.year, d.month)[1]
        return first, date(d.year, d.month, last_day)

    @staticmethod
    def get_or_create_current_term(db: Session, user_id: str, character_id: str, for_date: date) -> TemerantTerm:
        month = TermService.first_day(for_date)
        term = db.query(TemerantTerm).filter(
            TemerantTerm.user_id == user_id,
            TemerantTerm.term_month == month,
        ).first()
        if term:
            return term
        term = TemerantTerm(
            user_id=user_id,
            character_id=character_id,
            term_month=month,
            completion_pct=0.0,
            admissions_result="good",
            tuition_talents=10,
            xp_multiplier=1.0,
            coin_delta=0.0,
        )
        db.add(term)
        db.flush()
        return term

    @staticmethod
    def calculate_completion_pct(db: Session, user_id: str, month: date, up_to: date | None = None) -> float:
        start, end = TermService.month_bounds(month)
        if up_to and up_to < end:
            end = up_to
        days = db.query(TemerantDailyState).filter(
            TemerantDailyState.user_id == user_id,
            TemerantDailyState.local_date >= start,
            TemerantDailyState.local_date <= end,
        ).all()
        if not days:
            return 0.0
        scores = [min(5, int(day.categories_completed or 0)) / 5.0 for day in days]
        return round((sum(scores) / len(scores)) * 100.0, 2)

    @staticmethod
    def close_term(
        db: Session,
        term: TemerantTerm,
        review_markdown: str | None = None,
        up_to: date | None = None,
    ) -> TemerantTerm:
        completion_pct = TermService.calculate_completion_pct(db, term.user_id, term.term_month, up_to=up_to)
        admissions, tuition, multiplier = TemerantRulesEngine.admissions_from_completion(completion_pct)
        term.completion_pct = completion_pct
        term.admissions_result = admissions
        term.tuition_talents = tuition
        term.xp_multiplier = multiplier
        term.coin_delta = float(-tuition)
        if review_markdown is not None:
            term.review_markdown = review_markdown
        # Lock handled by route when truly closing an ended term.
        db.flush()
        return term

    @staticmethod
    def list_term_history(db: Session, user_id: str, limit: int = 12) -> List[TemerantTerm]:
        return db.query(TemerantTerm).filter(
            TemerantTerm.user_id == user_id
        ).order_by(TemerantTerm.term_month.desc()).limit(limit).all()

