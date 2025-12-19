#!/usr/bin/env python3
"""
GitHub + Azure DevOps Commits Heatmap Generator
Собирает коммиты из обоих источников и генерирует SVG heatmap
"""

import os
import sys
import requests
from datetime import datetime, timedelta
from collections import defaultdict
import base64


# === КОНФИГУРАЦИЯ ===
# Azure DevOps
AZURE_ORG = os.environ.get("AZURE_ORG", "")
AZURE_PAT = os.environ.get("AZURE_DEVOPS_PAT", "")

# GitHub
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.environ.get("GH_USERNAME", "")

# Общее
AUTHOR_EMAILS = [e.strip().lower() for e in os.environ.get("AUTHOR_EMAILS", "").split(",") if e.strip()]
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "commits-heatmap.svg")

# Цвета для heatmap (зелёно-фиолетовый градиент)
COLORS = {
    0: "#161b22",   # нет коммитов
    1: "#5a3d6e",   # мало (фиолетовый)
    2: "#4a6fa5",   # средне (синий)
    3: "#26a641",   # много (зелёный)
    4: "#39d353",   # очень много (ярко-зелёный)
}


# === AZURE DEVOPS ===

def get_azure_headers() -> dict:
    auth = base64.b64encode(f":{AZURE_PAT}".encode()).decode()
    return {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }


def get_azure_projects() -> list[dict]:
    url = f"https://dev.azure.com/{AZURE_ORG}/_apis/projects?api-version=7.0"
    response = requests.get(url, headers=get_azure_headers())
    response.raise_for_status()
    return response.json().get("value", [])


def get_azure_repositories(project_name: str) -> list[dict]:
    url = f"https://dev.azure.com/{AZURE_ORG}/{project_name}/_apis/git/repositories?api-version=7.0"
    response = requests.get(url, headers=get_azure_headers())
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json().get("value", [])


def get_azure_commits(project_name: str, repo_id: str, from_date: datetime) -> list[dict]:
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


def fetch_azure_commits(from_date: datetime, emails: list[str]) -> list[dict]:
    """Собрать все коммиты из Azure DevOps"""
    if not AZURE_PAT or not AZURE_ORG:
        print("⏭️  Azure DevOps: skipped (no credentials)")
        return []

    all_commits = []
    print(f"\n🔷 Azure DevOps ({AZURE_ORG})")

    try:
        projects = get_azure_projects()
        print(f"   Found {len(projects)} projects")

        for project in projects:
            project_name = project["name"]
            repos = get_azure_repositories(project_name)

            for repo in repos:
                repo_name = repo["name"]
                repo_id = repo["id"]

                commits = get_azure_commits(project_name, repo_id, from_date)
                # Фильтрация по email
                if emails:
                    commits = [c for c in commits if c.get("author", {}).get("email", "").lower() in emails]

                if commits:
                    print(f"   📦 {project_name}/{repo_name}: {len(commits)} commits")
                    all_commits.extend(commits)

    except Exception as e:
        print(f"   ❌ Error: {e}")

    return all_commits


# === GITHUB ===

def get_github_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_github_repos() -> list[dict]:
    """Получить все репозитории пользователя"""
    repos = []
    page = 1

    while True:
        url = f"https://api.github.com/user/repos?per_page=100&page={page}&affiliation=owner,collaborator,organization_member"
        response = requests.get(url, headers=get_github_headers())
        response.raise_for_status()

        data = response.json()
        if not data:
            break

        repos.extend(data)
        page += 1

        if len(data) < 100:
            break

    return repos


def get_github_commits(owner: str, repo: str, from_date: datetime, author: str = None) -> list[dict]:
    """Получить коммиты из GitHub репозитория"""
    commits = []
    page = 1

    while True:
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        params = {
            "since": from_date.isoformat(),
            "per_page": 100,
            "page": page,
        }
        if author:
            params["author"] = author

        response = requests.get(url, headers=get_github_headers(), params=params)

        if response.status_code == 409:  # Empty repository
            break
        if response.status_code == 404:
            break
        response.raise_for_status()

        data = response.json()
        if not data:
            break

        commits.extend(data)
        page += 1

        if len(data) < 100:
            break

    return commits


def fetch_github_commits(from_date: datetime, emails: list[str]) -> list[dict]:
    """Собрать все коммиты из GitHub"""
    if not GITHUB_TOKEN:
        print("⏭️  GitHub: skipped (no token)")
        return []

    all_commits = []
    print(f"\n🐙 GitHub")

    try:
        repos = get_github_repos()
        print(f"   Found {len(repos)} repositories")

        for repo in repos:
            owner = repo["owner"]["login"]
            repo_name = repo["name"]

            # Получаем коммиты для каждого email или для username
            commits = []
            if GITHUB_USERNAME:
                commits = get_github_commits(owner, repo_name, from_date, GITHUB_USERNAME)
            else:
                commits = get_github_commits(owner, repo_name, from_date)

            # Фильтрация по email если указаны
            if emails and commits:
                commits = [c for c in commits if c.get("commit", {}).get("author", {}).get("email", "").lower() in emails]

            if commits:
                print(f"   📦 {owner}/{repo_name}: {len(commits)} commits")
                # Преобразуем в общий формат
                for c in commits:
                    all_commits.append({
                        "author": {
                            "email": c.get("commit", {}).get("author", {}).get("email", ""),
                            "date": c.get("commit", {}).get("author", {}).get("date", ""),
                        }
                    })

    except Exception as e:
        print(f"   ❌ Error: {e}")

    return all_commits


# === ОБЩИЕ ФУНКЦИИ ===

def aggregate_by_date(commits: list[dict]) -> dict[str, int]:
    """Агрегировать коммиты по датам"""
    counts = defaultdict(int)
    for commit in commits:
        date_str = commit.get("author", {}).get("date", "")[:10]
        if date_str:
            counts[date_str] += 1
    return dict(counts)


def calculate_streak(commit_counts: dict[str, int]) -> tuple[int, int]:
    """Рассчитать текущий и максимальный streak"""
    today = datetime.now().date()

    # Текущий streak
    current_streak = 0
    check_date = today
    while True:
        date_str = check_date.strftime("%Y-%m-%d")
        if commit_counts.get(date_str, 0) > 0:
            current_streak += 1
            check_date -= timedelta(days=1)
        else:
            # Проверим вчера если сегодня ещё нет коммитов
            if check_date == today:
                check_date -= timedelta(days=1)
                continue
            break

    # Максимальный streak
    max_streak = 0
    temp_streak = 0
    start_date = today - timedelta(days=365)

    for i in range(366):
        check_date = start_date + timedelta(days=i)
        date_str = check_date.strftime("%Y-%m-%d")
        if commit_counts.get(date_str, 0) > 0:
            temp_streak += 1
            max_streak = max(max_streak, temp_streak)
        else:
            temp_streak = 0

    return current_streak, max_streak


def get_color_level(count: int, max_count: int) -> int:
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


def generate_svg(commit_counts: dict[str, int], total_commits: int, current_streak: int = 0, max_streak: int = 0) -> str:
    """Генерировать SVG heatmap"""

    cell_size = 11
    cell_gap = 3
    margin_left = 35
    margin_top = 20
    margin_bottom = 20

    weeks = 53
    days = 7

    width = margin_left + (weeks * (cell_size + cell_gap)) + 10
    height = margin_top + (days * (cell_size + cell_gap)) + margin_bottom + 30

    today = datetime.now().date()
    start_date = today - timedelta(days=364)

    start_weekday = start_date.weekday()
    if start_weekday != 6:
        start_date = start_date - timedelta(days=(start_weekday + 1) % 7)

    max_count = max(commit_counts.values()) if commit_counts else 0

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<style>',
        '  .month { font-size: 10px; fill: #8b949e; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }',
        '  .day { font-size: 9px; fill: #8b949e; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }',
        '  .stats { font-size: 10px; fill: #8b949e; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }',
        '  rect.day-cell { rx: 2; ry: 2; }',
        '  rect.day-cell:hover { stroke: #8b949e; stroke-width: 1; }',
        '</style>',
        f'<rect width="{width}" height="{height}" fill="#0d1117"/>',
    ]

    day_labels = ["", "Mon", "", "Wed", "", "Fri", ""]
    for i, label in enumerate(day_labels):
        if label:
            y = margin_top + (i * (cell_size + cell_gap)) + 9
            svg_parts.append(f'<text x="5" y="{y}" class="day">{label}</text>')

    months_shown = set()
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

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

            month_key = (current_date.year, current_date.month)
            if month_key not in months_shown and current_date.day <= 7:
                months_shown.add(month_key)
                month_name = month_names[current_date.month - 1]
                svg_parts.append(f'<text x="{x}" y="{margin_top - 5}" class="month">{month_name}</text>')

            tooltip = f"{date_str}: {count} commit{'s' if count != 1 else ''}"
            svg_parts.append(
                f'<rect class="day-cell" x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" fill="{color}">'
                f'<title>{tooltip}</title></rect>'
            )

            current_date += timedelta(days=1)

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


def update_stats_file(total: int, azure: int, github: int, current_streak: int, max_streak: int):
    """Обновить файл STATS.md с актуальной статистикой"""
    stats_content = f"""## 📊 Stats

| Metric | Value |
|--------|-------|
| Total commits | **{total}** |
| Azure DevOps | {azure} |
| GitHub | {github} |
| 🔥 Current streak | **{current_streak} days** |
| 🏆 Max streak | **{max_streak} days** |

*Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}*
"""
    with open("STATS.md", "w", encoding="utf-8") as f:
        f.write(stats_content)
    print(f"✅ Saved to STATS.md")


def main():
    print("🚀 GitHub + Azure DevOps Commits Heatmap Generator")
    print(f"   Author emails: {AUTHOR_EMAILS or 'all'}")

    from_date = datetime.now() - timedelta(days=365)

    # Собираем коммиты из обоих источников
    azure_commits = fetch_azure_commits(from_date, AUTHOR_EMAILS)
    github_commits = fetch_github_commits(from_date, AUTHOR_EMAILS)

    all_commits = azure_commits + github_commits

    print(f"\n📊 Total: {len(all_commits)} commits")
    print(f"   Azure DevOps: {len(azure_commits)}")
    print(f"   GitHub: {len(github_commits)}")

    commit_counts = aggregate_by_date(all_commits)

    # Рассчитать streak
    current_streak, max_streak = calculate_streak(commit_counts)
    print(f"   Current streak: {current_streak} days")
    print(f"   Max streak: {max_streak} days")

    print(f"\n🎨 Generating SVG...")
    svg = generate_svg(commit_counts, len(all_commits), current_streak, max_streak)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(svg)

    print(f"✅ Saved to {OUTPUT_FILE}")

    # Сохранить статистику
    update_stats_file(len(all_commits), len(azure_commits), len(github_commits), current_streak, max_streak)


if __name__ == "__main__":
    main()
