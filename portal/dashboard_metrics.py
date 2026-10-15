"""Aggregated scheduling indicators, always scoped to one doctor."""
from datetime import datetime, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from .models import Appointment


def doctor_charts(doctor, today):
    def midnight(day):
        return timezone.make_aware(datetime.combine(day, datetime.min.time()))

    months = [today.replace(day=1)]
    for _ in range(5):
        months.insert(0, (months[0] - timedelta(days=1)).replace(day=1))
    qs = Appointment.objects.filter(doctor=doctor).order_by()
    period = qs.filter(start_at__gte=midnight(months[0]), start_at__lt=midnight(today + timedelta(days=1)))
    monthly = {
        row["month"].date(): row["total"]
        for row in period.filter(status="done").annotate(month=TruncMonth("start_at"))
        .values("month").annotate(total=Count("pk"))
    }
    max_month = max(monthly.values(), default=1) or 1
    month_bars = [{"date": month, "count": monthly.get(month, 0),
                   "height": round(monthly.get(month, 0) * 100 / max_month)} for month in months]
    counts = dict(period.values("status").annotate(total=Count("pk")).values_list("status", "total"))
    total = sum(counts.values())
    statuses = [("done", "Completadas", "#2f7867"), ("approved", "Aprobadas", "#689bc0"),
                ("pending", "Pendientes", "#b98432"), ("cancelled", "Canceladas", "#ba7370"),
                ("rejected", "Rechazadas", "#8a849e")]
    status_bars = [{"label": label, "count": counts.get(key, 0), "color": color,
                    "percent": round(counts.get(key, 0) * 100 / total) if total else 0}
                   for key, label, color in statuses]
    week = {
        row["day"]: row["total"]
        for row in qs.filter(status="approved", start_at__gte=midnight(today),
                             start_at__lt=midnight(today + timedelta(days=7)))
        .annotate(day=TruncDate("start_at")).values("day").annotate(total=Count("pk"))
    }
    max_day = max(week.values(), default=1) or 1
    days = [today + timedelta(days=i) for i in range(7)]
    return {"months": month_bars, "completed": sum(monthly.values()),
            "statuses": status_bars, "total": total, "since": months[0],
            "week_total": sum(week.values()),
            "week": [{"date": day, "count": week.get(day, 0),
                      "height": round(week.get(day, 0) * 100 / max_day)} for day in days]}
