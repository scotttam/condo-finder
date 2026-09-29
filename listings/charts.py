"""Small server-rendered line charts: turns weekly series into SVG coordinates for a template."""

from datetime import date

WIDTH, HEIGHT = 380, 190
LEFT, RIGHT, TOP, BOTTOM = 50, WIDTH - 14, 12, HEIGHT - 26


def _format(value, fmt):
    if fmt == "dollars":
        return f"${value:,.0f}"
    if fmt == "percent":
        return f"{value * 100:.0f}%"
    if fmt == "days":
        return f"{value:.0f}d"
    return f"{value:g}"


def _nice_ticks(low, high, count=4):
    if low == high:
        return [low]
    step = (high - low) / (count - 1)
    return [low + step * i for i in range(count)]


def line_chart(series, labels, fmt=""):
    """series: {name: [value or None per label]}; labels: ISO dates. None leaves a gap in the line."""
    values = [v for points in series.values() for v in points if v is not None]
    chart = {"width": WIDTH, "height": HEIGHT, "left": LEFT, "right": RIGHT, "top": TOP, "bottom": BOTTOM,
             "lines": [], "y_ticks": [], "x_ticks": [], "empty": not values}
    if not values:
        return chart
    low, high = min(values), max(values)
    pad = (high - low) * 0.1 or abs(high) * 0.05 or 1
    low, high = low - pad, high + pad
    span_x = max(len(labels) - 1, 1)

    def x(i):
        return LEFT + (RIGHT - LEFT) * i / span_x if len(labels) > 1 else (LEFT + RIGHT) / 2

    def y(v):
        return BOTTOM - (BOTTOM - TOP) * (v - low) / (high - low)

    for name, points in series.items():
        coords = [(i, v) for i, v in enumerate(points) if v is not None]
        if not coords:
            continue
        paths, run = [], []
        for i, v in enumerate(points + [None]):
            if v is None:
                if len(run) > 1:
                    paths.append(" ".join(f"{'M' if n == 0 else 'L'}{px:.1f},{py:.1f}" for n, (px, py) in enumerate(run)))
                run = []
            else:
                run.append((x(i), y(v)))
        chart["lines"].append({
            "name": name,
            "paths": paths,
            "points": [{"x": round(x(i), 1), "y": round(y(v), 1), "label": _format(v, fmt)} for i, v in coords],
        })
    chart["y_ticks"] = [{"y": round(y(v), 1), "label": _format(v, fmt)} for v in _nice_ticks(min(values), max(values))]
    chart["x_ticks"] = [
        {
            "x": round(x(i), 1),
            "label": f"{date.fromisoformat(label):%b} {date.fromisoformat(label).day}",
            "anchor": "end" if i == len(labels) - 1 and len(labels) > 1 else "middle",  # keep the latest inside the frame
        }
        for i, label in enumerate(labels)
        if len(labels) <= 6 or (len(labels) - 1 - i) % 2 == 0  # every other week when crowded, always the latest
    ]
    return chart
