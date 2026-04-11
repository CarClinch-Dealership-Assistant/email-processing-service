from datetime import datetime, timedelta, date
import calendar
import logging


def get_candidate_dates(candidate_dates) -> list:
    return DateRange().get_date_range(candidate_dates)


class DateRange:
    def __init__(self) -> None:
        pass

    def get_date_range(self, period:str) -> list:
        l = period.split(",")
        if len(l) != 0:
            return l
        return self.get_next_ten_days()


    def get_next_ten_days(self) -> list:
        today = datetime.now().date()
        date_list = [
            (today + timedelta(days=i)).isoformat()
            for i in range(10)
        ]
        return date_list

    def get_this_week(self) -> list:
        today = datetime.now().date()
        days_left = 6 - today.weekday()

        date_list = [today + timedelta(days=i) for i in range(days_left + 1)]
        return [d.isoformat() for d in date_list]

    def get_this_month(self) -> list:
        today = datetime.now().date()
        _, last_day = calendar.monthrange(today.year, today.month)
        date_list = [
            today + timedelta(days=i)
            for i in range((last_day - today.day) + 1)
        ]

        return [d.isoformat() for d in date_list]

    def get_next_week(self) -> list:
        today = datetime.now().date()
        days_until_next_monday = 7 - today.weekday()

        next_monday = today + timedelta(days=days_until_next_monday)
        next_week = [
            (next_monday + timedelta(days=i)).isoformat()
            for i in range(7)
        ]
        return next_week

    def get_next_month(self) -> list:
        today = datetime.now().date()

        if today.month == 12:
            next_month = 1
            year = today.year + 1
        else:
            next_month = today.month + 1
            year = today.year

        _, num_days = calendar.monthrange(year, next_month)

        date_list = [
            datetime(year, next_month, day).isoformat()
            for day in range(1, num_days + 1)
        ]

        return date_list

