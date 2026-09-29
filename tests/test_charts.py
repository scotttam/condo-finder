from listings.charts import line_chart


def test_scales_series_into_the_plot_area():
    chart = line_chart({"Portland": [3000, 3100, 3200]}, ["2026-09-15", "2026-09-22", "2026-09-29"], fmt="dollars")
    (line,) = chart["lines"]
    xs = [point["x"] for point in line["points"]]
    ys = [point["y"] for point in line["points"]]
    assert xs[0] == chart["left"] and xs[-1] == chart["right"]
    assert ys[0] > ys[1] > ys[2]  # higher value, higher on the page (smaller y)
    assert chart["top"] <= min(ys) and max(ys) <= chart["bottom"]
    assert line["paths"] == ["M{:.1f},{:.1f} L{:.1f},{:.1f} L{:.1f},{:.1f}".format(*sum(([p["x"], p["y"]] for p in line["points"]), []))]
    assert [tick["label"] for tick in chart["x_ticks"]] == ["Sep 15", "Sep 22", "Sep 29"]
    assert [tick["anchor"] for tick in chart["x_ticks"]] == ["middle", "middle", "end"]
    assert all(tick["label"].startswith("$") for tick in chart["y_ticks"])
    assert line["points"][-1]["label"] == "$3,200"


def test_gaps_split_the_line_and_empty_series_are_dropped():
    chart = line_chart({"A": [10, None, 12, 13], "B": [None, None, None, None]}, ["2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29"])
    assert [line["name"] for line in chart["lines"]] == ["A"]
    (line,) = chart["lines"]
    assert len(line["paths"]) == 1  # the lone first point has no segment; 12→13 does
    assert len(line["points"]) == 3


def test_no_data_at_all():
    chart = line_chart({"A": [None, None]}, ["2026-09-22", "2026-09-29"])
    assert chart["empty"] is True and chart["lines"] == []


def test_percent_format_and_flat_series():
    chart = line_chart({"Cuts": [0.25, 0.25]}, ["2026-09-22", "2026-09-29"], fmt="percent")
    (line,) = chart["lines"]
    assert line["points"][0]["y"] == line["points"][1]["y"]
    assert line["points"][0]["label"] == "25%"


def test_crowded_weeks_label_every_other_ending_on_the_latest():
    labels = [f"2026-08-{day:02d}" for day in (4, 11, 18, 25)] + ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"]
    chart = line_chart({"A": [1] * 8}, labels)
    assert [tick["label"] for tick in chart["x_ticks"]] == ["Aug 11", "Aug 25", "Sep 8", "Sep 22"]
