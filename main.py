import os
import time
import json
import pathlib
import requests
import datetime
import email.utils
import urllib.parse
from git import Repo
import leetcode_query


def parse_git_log():
    commits = dict()
    for commit in Repo(os.getcwd()).iter_commits():
        if commit.message not in commits:
            commits[commit.message] = int(commit.committed_datetime.timestamp())

    return commits


def scrape_leetcode():
    session = requests.Session()
    session.cookies.set("LEETCODE_SESSION", os.environ.get("LEETCODE_SESSION"), domain="leetcode.com")
    session.cookies.set("csrftoken", os.environ.get("LEETCODE_CSRF_TOKEN"), domain="leetcode.com")

    solved_problems = list()
    all_problems = session.get("https://leetcode.com/api/problems/all/").json()
    for problem in all_problems["stat_status_pairs"]:
        if problem["status"] == "ac":
            time.sleep(1)

            title_slug = problem["stat"]["question__title_slug"]
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36",
                "Connection": "keep-alive",
                "Content-Type": "application/json",
                "Referer": "https://leetcode.com/problems/" + title_slug,
            }

            json_data = leetcode_query.question_detail
            json_data["variables"]["titleSlug"] = title_slug
            question_details = session.post("https://leetcode.com/graphql", json=json_data, headers=headers, timeout=10).json()

            json_data = leetcode_query.submission_list
            json_data["variables"]["questionSlug"] = title_slug
            submissions = session.post("https://leetcode.com/graphql", json=json_data, headers=headers, timeout=10).json()

            json_data = leetcode_query.submission_details
            json_data["variables"]["submissionId"] = submissions["data"]["questionSubmissionList"]["submissions"][0]["id"]
            submission_details = session.post("https://leetcode.com/graphql", json=json_data, headers=headers, timeout=10).json()

            problem_info = {
                "id": int(problem["stat"]["frontend_question_id"]),
                "title": problem["stat"]["question__title"],
                "title_slug": title_slug,
                "content": question_details["data"]["question"]["content"],
                "difficulty": question_details["data"]["question"]["difficulty"],
                "skills": [tag["name"] for tag in question_details["data"]["question"]["topicTags"]],
                "timestamp": int(submissions["data"]["questionSubmissionList"]["submissions"][0]["timestamp"]),
                "language": submissions["data"]["questionSubmissionList"]["submissions"][0]["langName"],
                "code": submission_details["data"]["submissionDetails"]["code"],
            }
            solved_problems.append(problem_info)

    return sorted(solved_problems, key=lambda entry: entry["timestamp"])


# def update_readme(submissions):
#     template = """
# # LeetCode Submissions

# > Auto-generated with [LeetCode Synchronizer](https://github.com/dos-m0nk3y/LeetCode-Synchronizer)

# ## Contents

# | # | Title | Difficulty | Skills |
# |---| ----- | ---------- | ------ |
# """
#     difficulty_badge = {
#         "Easy": "https://img.shields.io/badge/Easy-green",
#         "Medium": "https://img.shields.io/badge/Medium-orange",
#         "Hard": "https://img.shields.io/badge/Hard-red",
#     }

#     for submission in submissions:
#         title = f"[{submission['title']}](https://leetcode.com/problems/{submission['title_slug']})"
#         skills = " ".join([f"`{skill}`" for skill in submission["skills"]])

#         diff = submission["difficulty"]
#         badge = f"![{diff}]({difficulty_badge.get(diff, '')})"

#         template += (
#             f"| {str(submission['id']).zfill(4)} "
#             f"| {title} "
#             f"| {badge} "
#             f"| {skills} |\n"
#         )

#     with open("README.md", "wt", encoding="utf-8") as fd:
#         fd.write(template.strip())
def update_readme(submissions):
    # ---------- STATS ----------
    stats = {
        "Easy": 0,
        "Medium": 0,
        "Hard": 0,
    }

    for s in submissions:
        if s["difficulty"] in stats:
            stats[s["difficulty"]] += 1

    total = sum(stats.values())

    difficulty_badge = {
        "Easy": "https://img.shields.io/badge/Easy-green",
        "Medium": "https://img.shields.io/badge/Medium-orange",
        "Hard": "https://img.shields.io/badge/Hard-red",
    }

    # ---------- README HEADER ----------
    template = f"""
# LeetCode Submissions

> Auto-generated with [LeetCode Synchronizer Plus](https://github.com/HoneyHabib/LeetCode-Synchronizer-Plus)

## 📊 Stats

![Total](https://img.shields.io/badge/Total-{total}-blue)
![Easy](https://img.shields.io/badge/Easy-{stats['Easy']}-green)
![Medium](https://img.shields.io/badge/Medium-{stats['Medium']}-orange)
![Hard](https://img.shields.io/badge/Hard-{stats['Hard']}-red)

---

## Contents

| # | Title | Difficulty | Skills |
|---| ----- | ---------- | ------ |
"""

    # ---------- TABLE ----------
    for submission in submissions:
        title = f"[{submission['title']}](https://leetcode.com/problems/{submission['title_slug']})"
        skills = " ".join([f"`{skill}`" for skill in submission["skills"]])

        diff = submission["difficulty"]
        badge = f"![{diff}]({difficulty_badge.get(diff, '')})"

        template += (
            f"| {str(submission['id']).zfill(4)} "
            f"| {title} "
            f"| {badge} "
            f"| {skills} |\n"
        )

    with open("README.md", "wt", encoding="utf-8") as fd:
        fd.write(template.strip())


def sync_github(commits, submissions):
    repo = Repo(os.getcwd())

    # ---------- auth ----------
    url = urllib.parse.urlparse(repo.remote("origin").url)
    url = url._replace(netloc=f"{os.environ.get('GITHUB_TOKEN')}@" + url.netloc)
    url = url._replace(path=url.path + ".git")
    repo.remote("origin").set_url(url.geturl())

    last_commit = list(repo.iter_commits())[0]
    repo.config_writer().set_value("user", "name", last_commit.author.name).release()
    repo.config_writer().set_value("user", "email", last_commit.author.email).release()

    for submission in submissions:
        dir_name = f"{str(submission['id']).zfill(4)}-{submission['title_slug']}"
        base_dir = pathlib.Path("problems") / dir_name
        base_dir.mkdir(parents=True, exist_ok=True)

        # ---------- language → extension ----------
        ext = {
            "C++": "cpp",
            "JavaScript": "js",
            "JavaScript (Node.js)": "js",
            "MySQL": "sql",
            "Bash": "sh",
            "Python": "py",
            "Java": "java",
        }.get(submission["language"], submission["language"].lower().replace(" ", ""))

        # ---------- UNIQUE FILE (NO OVERRIDE) ----------
        ts = datetime.datetime.fromtimestamp(submission["timestamp"])
        filename = f"{ts.strftime('%Y-%m-%dT%H-%M-%S')}_{submission['timestamp']}.{ext}"
        solution_file = base_dir / filename

        if solution_file.exists():
            continue  # already synced

        solution_file.write_text(submission["code"].strip(), encoding="utf-8")

        # ---------- README (write once) ----------
        readme = base_dir / "README.md"
        if not readme.exists():
            readme.write_text(
                f"<h2>{submission['id']}. {submission['title']}</h2>\n\n"
                + submission["content"].strip(),
                encoding="utf-8",
            )

        # ---------- update global README ----------
        submission["skills"].sort()
        new_entry = {
            "id": submission["id"],
            "title": submission["title"],
            "title_slug": submission["title_slug"],
            "difficulty": submission["difficulty"],
            "skills": submission["skills"],
        }

        saved = []
        if os.path.isfile("submissions.json"):
            with open("submissions.json", "rt") as f:
                saved = json.load(f)

        if new_entry not in saved:
            saved.append(new_entry)
            saved = sorted(saved, key=lambda x: x["id"])
            update_readme(saved)
            with open("submissions.json", "wt") as f:
                json.dump(saved, f, indent=2)

        # ---------- commit ----------
        commit_msg = (
            f"LeetCode [{submission['id']}] "
            f"{submission['title']} | {submission['language']} | {filename}"
        )

        iso_date = email.utils.format_datetime(ts)
        os.environ["GIT_AUTHOR_DATE"] = iso_date
        os.environ["GIT_COMMITTER_DATE"] = iso_date

        repo.index.add([str(base_dir), "README.md", "submissions.json"])
        repo.index.commit(commit_msg)
        repo.remote("origin").push()

        os.environ.pop("GIT_AUTHOR_DATE", None)
        os.environ.pop("GIT_COMMITTER_DATE", None)


def main():
    commits = parse_git_log()
    submissions = scrape_leetcode()
    sync_github(commits, submissions)


if __name__ == "__main__":
    main()