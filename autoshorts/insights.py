from datetime import date, timedelta
from statistics import mean

from googleapiclient.discovery import build

from autoshorts.upload import _credentials

MIN_VIDEOS_FOR_INSIGHTS = 3
MIN_VIDEOS_PER_FORMAT = 2
MIN_VIEWS = 100


def fetch_performance(history: list[dict], days: int = 90) -> list[dict]:
    analytics = build("youtubeAnalytics", "v2", credentials=_credentials(), cache_discovery=False)
    response = analytics.reports().query(
        ids="channel==MINE",
        startDate=(date.today() - timedelta(days=days)).isoformat(),
        endDate=date.today().isoformat(),
        metrics="views,averageViewPercentage,likes,subscribersGained",
        dimensions="video",
        sort="-views",
        maxResults=200,
    ).execute()
    by_id = {h["video_id"]: h for h in history if h.get("video_id")}
    performance = []
    for video_id, views, retention, likes, subscribers in response.get("rows", []):
        entry = by_id.get(video_id)
        if entry and int(views) >= MIN_VIEWS:
            performance.append({
                **entry,
                "views": int(views),
                "retention": float(retention),
                "likes": int(likes),
                "subscribers": int(subscribers),
            })
    return performance


def _score(video: dict) -> float:
    return video["views"] * (video["retention"] / 100)


def _line(video: dict) -> str:
    return (
        f'- "{video["title"]}" (formato {video.get("format", "dato")}, {video["views"]} vistas, '
        f'{video["retention"]:.0f}% visto de media, {video["subscribers"]} suscriptores)'
    )


def build_insights(performance: list[dict]) -> str:
    if len(performance) < MIN_VIDEOS_FOR_INSIGHTS:
        return ""
    ranked = sorted(performance, key=_score, reverse=True)
    best = ranked[:min(5, len(ranked) // 2)]
    worst = ranked[len(best):][-3:] if len(ranked) >= 6 else []
    lines = ["Rendimiento real de shorts anteriores del canal. Imita el tipo de tema, gancho y título de los mejores"]
    lines.append("(sin repetir tema) y evita lo que tienen en común los peores.")
    lines.append("MEJORES:")
    lines += [_line(v) for v in best]
    if worst:
        lines.append("PEORES:")
        lines += [_line(v) for v in worst]
    return "\n".join(lines)


def format_weights(performance: list[dict]) -> dict[str, float]:
    by_format: dict[str, list[float]] = {}
    for video in performance:
        by_format.setdefault(video.get("format", "dato"), []).append(video["retention"])
    if not by_format:
        return {}
    overall = mean(r for values in by_format.values() for r in values) or 1
    return {
        name: min(max(mean(values) / overall, 0.5), 2.0)
        for name, values in by_format.items()
        if len(values) >= MIN_VIDEOS_PER_FORMAT
    }
