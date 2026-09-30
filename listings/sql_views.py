import csv
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from . import sql_console
from .models import QueryRun, SavedQuery
from .sql_queries import by_category


def _console_url(sql, saved=None):
    params = {"q": sql}
    if saved is not None:
        params["saved"] = saved.pk
    return f"{reverse('sql_console')}?{urlencode(params)}"


def _cells(result):
    """Rows as cells with a link to the listing page where the column holds a listing id."""
    links = sql_console.listing_link_columns(result.sql, result.columns)
    return [
        [
            {"value": value, "href": reverse("listing_detail", args=[value]) if index in links and isinstance(value, int) else ""}
            for index, value in enumerate(row)
        ]
        for row in result.rows
    ]


@staff_member_required
def sql_console_page(request):
    sql = request.GET.get("q", "").strip()
    result = None
    if sql:
        result = sql_console.run_query(sql, max_rows=settings.SQL_CONSOLE_MAX_ROWS)
        QueryRun.record(sql=sql, user=request.user, row_count=None if result.error else result.row_count,
                        elapsed_ms=result.elapsed_ms, error=result.error)
    saved_pk = request.GET.get("saved", "")
    saved = SavedQuery.objects.filter(pk=saved_pk).first() if saved_pk.isdigit() else None
    return render(request, "listings/sql_console.html", {
        "sql": sql,
        "result": result,
        "cells": _cells(result) if result and not result.error else [],
        "max_rows": settings.SQL_CONSOLE_MAX_ROWS,
        "timeout": settings.SQL_CONSOLE_TIMEOUT_SECONDS,
        "canned": by_category(),
        "saved": saved,
        "saved_queries": SavedQuery.objects.all(),
        "recent": QueryRun.objects.all(),
        "schema": sql_console.schema(),
    })


@staff_member_required
def sql_csv(request):
    sql = request.GET.get("q", "").strip()
    if not sql:
        return HttpResponseBadRequest("No query.", content_type="text/plain")
    result = sql_console.run_query(sql)  # no row cap; the timeout still applies
    if result.error:
        return HttpResponseBadRequest(f"Query failed: {result.error}", content_type="text/plain; charset=utf-8")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="query-{timezone.localtime():%Y%m%d-%H%M}.csv"'
    writer = csv.writer(response)
    writer.writerow(result.columns)
    writer.writerows(result.rows)
    return response
