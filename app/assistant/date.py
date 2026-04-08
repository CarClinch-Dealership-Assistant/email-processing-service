from datetime import datetime, timezone, timedelta, date
import calendar


def get_candidate_dates(candidate_dates) -> list:
    return DateRange().get_date_range(candidate_dates)


class DateRange:
    def __init__(self) -> None:
        pass

    def get_date_range(self, period:str) -> list:
        p = period.lower().replace(" ", "").replace("_", "")
        match p:
            case "thisweek":
                return self.get_this_week()
            case "nextweek":
                return self.get_next_week()
            case "thismonth":
                return self.get_this_month()
            case "nextmonth":
                return self.get_next_month()
            case _:
                return self.get_next_ten_days()

    def get_next_ten_days(self) -> list:
        today = datetime.now().date()
        date_list = [
            (today + timedelta(days=i)).strftime('%Y-%m-%d')
            for i in range(10)
        ]
        return date_list

    def get_this_week(self) -> list:
        today = datetime.now().date()
        days_left = 6 - today.weekday()

        date_list = [today + timedelta(days=i) for i in range(days_left + 1)]
        return [d.strftime('%Y-%m-%d') for d in date_list]

    def get_this_month(self) -> list:
        today = datetime.now().date()
        _, last_day = calendar.monthrange(today.year, today.month)
        date_list = [
            today + timedelta(days=i)
            for i in range((last_day - today.day) + 1)
        ]

        return [d.strftime('%Y-%m-%d') for d in date_list]

    def get_next_week(self) -> list:
        today = datetime.now().date()
        days_until_next_monday = 7 - today.weekday()

        next_monday = today + timedelta(days=days_until_next_monday)
        next_week = [
            (next_monday + timedelta(days=i)).strftime('%Y-%m-%d')
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
            datetime(year, next_month, day).strftime('%Y-%m-%d')
            for day in range(1, num_days + 1)
        ]

        return date_list

if __name__ == "__main__":
    print(get_candidate_dates(""))
    print(get_candidate_dates("this week"))
    print(get_candidate_dates("next month"))