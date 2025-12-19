#!/usr/bin/env python3
"""
Azure DevOps Commits Heatmap Generator
Собирает коммиты из Azure DevOps и генерирует SVG heatmap
"""

import os
import sys
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
import base64


# === КОНФИГУРАЦИЯ ===
AZURE_ORG = os.environ.get("AZURE_ORG", "interscout")
AZURE_PAT = os.environ.get("AZURE_DEVOPS_PAT", "")
AUTHOR_EMAILS = [e.strip().lower() for e in os.environ.get("AUTHOR_EMAILS", "").split(",") if e.strip()]
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "commits-heatmap.svg")

# Цвета для heatmap (стиль GitHub)
COLORS = {
    0: "#161b22",   # нет коммитов
    1: "#0e4429",   # мало
    2: "#006d32",   # средне
    3: "#26a641",   # много
    4: "#39d353",   # очень много
}


def get_azure_headers() -> dict:
    """Заголовки для Azure DevOps API"""
    auth = base64.b64encode(f":{AZURE_PAT}".encode()).decode()
    return {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }


def get_projects() -> list[dict]:
    """Получить список всех проектов в организации"""
    url = f"https://dev.azure.com/{AZURE_ORG}/_apis/projects?api-version=7.0"
    response = requests.get(url, headers=get_azure_headers())
    response.raise_for_status()
    return response.json().get("value", [])


def get_repositories(project_name: str) -> list[dict]:
    """Получить список репозиториев в проекте"""
    url = f"https://dev.azure.com/{AZURE_ORG}/{project_name}/_apis/git/repositories?api-version=7.0"
    response = requests.get(url, headers=get_azure_headers())
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json().get("value", [])


def get_commits(project_name: str, repo_id: str, from_date: datetime) -> list[dict]:
    """Получить коммиты из репозитория"""
    url = f"https://dev.azure.com/{AZURE_ORG}/{project_name}/_apis/git/repositories/{repo_id}/commits"
    params = {
        "api-version": "7.0",
        "searchCriteria.fromDate": from_date.isoformat(),
        "$top": 10000,
    }

    all_commits = []
    skip = 0

    while True:
        params["$skip"] = skip
        response = requests.get(url, headers=get_azure_headers(), params=params)
        if response.status_code == 404:
            break
        response.raise_for_status()

        commits = response.json().get("value", [])
        if not commits:
            break

        all_commits.extend(commits)
        skip += len(commits)

        if len(commits) < 10000:
            break

    return all_commits


def filter_commits_by_author(commits: list[dict], emails: list[str]) -> list[dict]:
    """Фильтровать коммиты по email автора"""
    if not emails:
        return commits
    return [c for c in commits if c.get("author", {}).get("email", "").lower() in emails]


def aggregate_by_date(commits: list[dict]) -> dict[str, int]:
    """Агрегировать коммиты по датам"""
    counts = defaultdict(int)
    for commit in commits:
        date_str = commit.get("author", {}).get("date", "")[:10]
        if date_str:
            counts[date_str] += 1
    return dict(counts)


def get_color_level(count: int, max_count: int) -> int:
    """Определить уровень цвета для количества коммитов"""
    if count == 0:
        return 0
    if max_count == 0:
        return 0

    ratio = count / max_count
    if ratio <= 0.25:
        return 1
    elif ratio <= 0.5:
        return 2
    elif ratio <= 0.75:
        return 3
    else:
        return 4


def generate_svg(commit_counts: dict[str, int], total_commits: int) -> str:
    """Генерировать SVG heatmap"""

    # Размеры
    cell_size = 11
    cell_gap = 3
    margin_left = 35
    margin_top = 25
    margin_bottom = 20

    # 53 недели, 7 дней
    weeks = 53
    days = 7

    width = margin_left + (weeks * (cell_size + cell_gap)) + 10
    height = margin_top + (days * (cell_size + cell_gap)) + margin_bottom + 30

    # Определить даты
    today = datetime.now().date()
    start_date = today - timedelta(days=364)

    # Найти воскресенье (начало первой недели)
    start_weekday = start_date.weekday()
    if start_weekday != 6:  # Если не воскресенье
        start_date = start_date - timedelta(days=(start_weekday + 1) % 7)

    # Максимальное количество для цветовой шкалы
    max_count = max(commit_counts.values()) if commit_counts else 0

    # SVG header
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<style>',
        '  .month { font-size: 10px; fill: #8b949e; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }',
        '  .day { font-size: 9px; fill: #8b949e; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }',
        '  .title { font-size: 12px; fill: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-weight: 600; }',
        '  .stats { font-size: 10px; fill: #8b949e; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }',
        '  rect.day-cell { rx: 2; ry: 2; }',
        '  rect.day-cell:hover { stroke: #8b949e; stroke-width: 1; }',
        '</style>',
        f'<rect width="{width}" height="{height}" fill="#0d1117"/>',
        f'<text x="{margin_left}" y="15" class="title">Azure DevOps Contributions</text>',
    ]

    # Подписи дней недели
    day_labels = ["", "Mon", "", "Wed", "", "Fri", ""]
    for i, label in enumerate(day_labels):
        if label:
            y = margin_top + (i * (cell_size + cell_gap)) + 9
            svg_parts.append(f'<text x="5" y="{y}" class="day">{label}</text>')

    # Подписи месяцев
    months_shown = set()
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # Генерация ячеек
    current_date = start_date
    for week in range(weeks):
        for day in range(days):
            if current_date > today:
                current_date += timedelta(days=1)
                continue

            date_str = current_date.strftime("%Y-%m-%d")
            count = commit_counts.get(date_str, 0)
            color_level = get_color_level(count, max_count)
            color = COLORS[color_level]

            x = margin_left + (week * (cell_size + cell_gap))
            y = margin_top + (day * (cell_size + cell_gap))

            # Подпись месяца
            month_key = (current_date.year, current_date.month)
            if month_key not in months_shown and current_date.day <= 7:
                months_shown.add(month_key)
                month_name = month_names[current_date.month - 1]
                svg_parts.append(f'<text x="{x}" y="{margin_top - 5}" class="month">{month_name}</text>')

            # Ячейка
            tooltip = f"{date_str}: {count} commit{'s' if count != 1 else ''}"
            svg_parts.append(
                f'<rect class="day-cell" x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" fill="{color}">'
                f'<title>{tooltip}</title></rect>'
            )

            current_date += timedelta(days=1)

    # Легенда
    legend_x = width - 150
    legend_y = height - 20
    svg_parts.append(f'<text x="{legend_x - 30}" y="{legend_y + 9}" class="day">Less</text>')
    for i, color in COLORS.items():
        svg_parts.append(f'<rect x="{legend_x + i * 14}" y="{legend_y}" width="{cell_size}" height="{cell_size}" fill="{color}" rx="2" ry="2"/>')
    svg_parts.append(f'<text x="{legend_x + 75}" y="{legend_y + 9}" class="day">More</text>')

    # Статистика
    svg_parts.append(f'<text x="{margin_left}" y="{height - 10}" class="stats">{total_commits} contributions in the last year</text>')

    svg_parts.append('</svg>')

    return '\n'.join(svg_parts)


def main():
    print(f"🚀 Azure DevOps Commits Heatmap Generator")
    print(f"   Organization: {AZURE_ORG}")
    print(f"   Author emails: {AUTHOR_EMAILS or 'all'}")
    print()

    if not AZURE_PAT:
        print("❌ Error: AZURE_DEVOPS_PAT environment variable is not set")
        sys.exit(1)

    # Дата начала (365 дней назад)
    from_date = datetime.now() - timedelta(days=365)

    # Собрать все коммиты
    all_commits = []

    print("📁 Fetching projects...")
    projects = get_projects()
    print(f"   Found {len(projects)} projects")

    for project in projects:
        project_name = project["name"]
        print(f"\n📂 Project: {project_name}")

        repos = get_repositories(project_name)
        print(f"   Found {len(repos)} repositories")

        for repo in repos:
            repo_name = repo["name"]
            repo_id = repo["id"]

            commits = get_commits(project_name, repo_id, from_date)
            filtered = filter_commits_by_author(commits, AUTHOR_EMAILS)

            if filtered:
                print(f"   📦 {repo_name}: {len(filtered)} commits")
                all_commits.extend(filtered)

    print(f"\n📊 Total commits: {len(all_commits)}")

    # Агрегация по датам
    commit_counts = aggregate_by_date(all_commits)

    # Генерация SVG
    print(f"\n🎨 Generating SVG...")
    svg = generate_svg(commit_counts, len(all_commits))

    # Сохранение
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"✅ Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
