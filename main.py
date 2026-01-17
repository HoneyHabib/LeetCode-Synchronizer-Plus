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

def require_json(response, context):
    if response.status_code != 200:
        raise RuntimeError(
            f"LeetCode API failed ({context}) "
            f"with status {response.status_code}. "
            "Cookies may be expired."
        )
    try:
        return response.json()
    except Exception:
        raise RuntimeError(
            f"LeetCode API returned non-JSON ({context}). "
            "Your LEETCODE_SESSION or CSRF token is likely expired."
        )

def require_graphql_data(response, context):
    payload = require_json(response, context)

    if "errors" in payload:
        raise RuntimeError(
            f"LeetCode GraphQL error ({context}): "
            f"{payload['errors'][0].get('message', payload['errors'])}"
        )

    if "data" not in payload or payload["data"] is None:
        raise RuntimeError(
            f"LeetCode GraphQL returned no data ({context}). "
            "Authentication or query structure may be broken."
        )

    return payload["data"]

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
    # all_problems = session.get("https://leetcode.com/api/problems/all/").json()
    resp = session.get("https://leetcode.com/api/problems/all/")
    all_problems = require_json(resp, "fetching problem list")
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
            # question_details = session.post("https://leetcode.com/graphql", json=json_data, headers=headers, timeout=10).json()
            resp = session.post(
                "https://leetcode.com/graphql",
                json=json_data,
                headers=headers,
                timeout=10
            )
            question_details = require_graphql_data(
                resp, f"question details for {title_slug}"
            )

            json_data = leetcode_query.submission_list
            json_data["variables"]["questionSlug"] = title_slug
            # submissions = session.post("https://leetcode.com/graphql", json=json_data, headers=headers, timeout=10).json()
            resp = session.post(
                "https://leetcode.com/graphql",
                json=json_data,
                headers=headers,
                timeout=10
            )
            submissions = require_graphql_data(
                resp, f"submission list for {title_slug}"
            )
            # ✅ GUARD EMPTY / MISSING SUBMISSIONS
            submission_list = submissions.get("data", {}) \
                                        .get("questionSubmissionList", {}) \
                                        .get("submissions", [])

            if not submission_list:
                # No accepted submissions found — skip safely
                continue

            latest_submission_id = submission_list[0]["id"]
            json_data = leetcode_query.submission_details
            json_data["variables"]["submissionId"] = latest_submission_id
            resp = session.post(
                "https://leetcode.com/graphql",
                json=json_data,
                headers=headers,
                timeout=10
            )
            submission_details = require_graphql_data(
                resp, f"submission details for {title_slug}"
            )
            code = submission_details.get("data", {}) \
                         .get("submissionDetails", {}) \
                         .get("code")

            if not code:
                continue

            latest_submission = submission_list[0]
            problem_info = {
                "id": int(problem["stat"]["frontend_question_id"]),
                "title": problem["stat"]["question__title"],
                "title_slug": title_slug,
                "content": question_details["data"]["question"]["content"],
                "difficulty": question_details["data"]["question"]["difficulty"],
                "skills": [tag["name"] for tag in question_details["data"]["question"]["topicTags"]],
                "timestamp": int(latest_submission["timestamp"]),
                "language": latest_submission["langName"],
                "code": code,
            }
            solved_problems.append(problem_info)

    return sorted(solved_problems, key=lambda entry: entry["timestamp"])

def calculate_stats(submissions):
    stats = {
        "total": len(submissions),
        "Easy": 0,
        "Medium": 0,
        "Hard": 0,
    }

    for s in submissions:
        if s["difficulty"] in stats:
            stats[s["difficulty"]] += 1

    return stats

def update_readme(submissions):
    stats = calculate_stats(submissions)

    difficulty_badges = {
        "Easy": "![Easy](https://img.shields.io/badge/Easy-success)",
        "Medium": "![Medium](https://img.shields.io/badge/Medium-yellow)",
        "Hard": "![Hard](https://img.shields.io/badge/Hard-red)",
    }
    template = f"""
# LeetCode Submissions

> Auto-generated with [LeetCode Synchronizer](https://github.com/dos-m0nk3y/LeetCode-Synchronizer)

## 📊 Stats

- **Total Solved:** {stats["total"]}
- 🟢 Easy: {stats["Easy"]}
- 🟡 Medium: {stats["Medium"]}
- 🔴 Hard: {stats["Hard"]}

---

## Contents

| # | Title | Difficulty | Skills |
|---| ----- | ---------- | ------ |
"""
    for submission in submissions:
        title = f"[{submission['title']}](https://leetcode.com/problems/{submission['title_slug']})"
        skills = " ".join([f"`{skill}`" for skill in submission["skills"]])
        difficulty = difficulty_badges.get(
            submission["difficulty"],
            submission["difficulty"]
        )
        template += f"| {str(submission['id']).zfill(4)} | {title} | {difficulty} | {skills} |\n"

    with open("README.md", "wt") as fd:
        fd.write(template.strip())


def sync_github(commits, submissions):
    repo = Repo(os.getcwd())
    url = urllib.parse.urlparse(repo.remote("origin").url)
    url = url._replace(netloc=f"{os.environ.get('GITHUB_TOKEN')}@" + url.netloc)
    url = url._replace(path=url.path + ".git")
    repo.remote("origin").set_url(url.geturl())

    commit = list(repo.iter_commits())[0]
    repo.config_writer().set_value("user", "name", commit.author.name).release()
    repo.config_writer().set_value("user", "email", commit.author.email).release()

    for submission in submissions:
        ts = datetime.datetime.fromtimestamp(submission["timestamp"])
        timestamp_name = f"{ts.strftime('%Y-%m-%dT%H-%M-%S')}_{submission['timestamp']}"
        commit_message = (
            f"LeetCode [{submission['id']}] "
            f"{submission['title']} | {submission['language']} | {timestamp_name}"
        )
        if commit_message not in commits:
            dir_name = f"{str(submission['id']).zfill(4)}-{submission['title_slug']}"
            if submission["language"] == "C++":
                ext = "cpp"
            elif submission["language"] in ["JavaScript", "JavaScript (Node.js)"]:
                ext = "js"
            elif submission["language"] == "MySQL":
                ext = "sql"
            elif submission["language"] == "Bash":
                ext = "sh"
            elif submission["language"] == "Python":
                ext = "py"
            elif submission["language"] == "Java":
                ext = "java"
            else:
                # Fallback instead of crashing
                ext = submission["language"].lower().replace(" ", "")

            pathlib.Path(f"problems/{dir_name}").mkdir(parents=True, exist_ok=True)
            with open(f"problems/{dir_name}/{timestamp_name}.{ext}", "wt") as fd:
                fd.write(submission["code"].strip())
            readme_path = f"problems/{dir_name}/README.md"
            if not os.path.exists(readme_path):
                with open(readme_path, "wt") as fd:
                    content = f"<h2>{submission['id']}. {submission['title']}</h2>\n\n"
                    content += submission["content"].strip()
                    fd.write(content)

            submission["skills"].sort()
            new_submission = {
                "id": submission["id"],
                "title": submission["title"],
                "title_slug": submission["title_slug"],
                "difficulty": submission["difficulty"],
                "skills": submission["skills"],
            }

            saved_submissions = list()
            if os.path.isfile("submissions.json"):
                with open("submissions.json", "rt") as fd:
                    saved_submissions = json.load(fd)

            if new_submission not in saved_submissions:
                saved_submissions.append(new_submission)
                saved_submissions = sorted(saved_submissions, key=lambda entry: entry["id"])
                update_readme(saved_submissions)
                with open("submissions.json", "wt") as fd:
                    json.dump(saved_submissions, fd, ensure_ascii=False, indent=2)

            # RFC 2822 (Thu, 07 Apr 2005 22:13:13 +0200) / ISO 8601 (2005-04-07T22:13:13)
            # https://github.com/gitpython-developers/GitPython/blob/master/git/objects/util.py#L134
            iso_datetime = email.utils.format_datetime(datetime.datetime.fromtimestamp(submission["timestamp"]))
            os.environ["GIT_AUTHOR_DATE"] = iso_datetime
            os.environ["GIT_COMMITTER_DATE"] = iso_datetime
            repo.index.add("**")
            repo.index.commit(commit_message)
            repo.git.push("origin")
            os.unsetenv("GIT_AUTHOR_DATE")
            os.unsetenv("GIT_COMMITTER_DATE")


def main():
    commits = parse_git_log()
    submissions = scrape_leetcode()
    sync_github(commits, submissions)


if __name__ == "__main__":
    main()
