"""
github_tool — Interact with GitHub repositories, issues, branches, and Pull Requests.

Requires:  pip install PyGithub
Env vars:  GITHUB_TOKEN  — Personal Access Token (classic) with repo scope.
           GITHUB_REPO   — Default repo in "owner/name" format (can be overridden per call).

Actions
-------
  list_repos       : List repos visible to the authenticated user.
  list_issues      : List open issues on a repo.
  get_issue        : Get the title, body, and comments of a single issue.
  list_branches    : List all branches in a repo.
  create_branch    : Create a new branch from an existing base branch.
  get_file         : Read the content of a file at a given path (raw text).
  commit_file      : Create or update a file on a branch with a commit message.
  create_pr        : Open a Pull Request from one branch into another.
  list_prs         : List open Pull Requests on a repo.
  add_comment      : Post a comment on an issue or PR.
  close_issue      : Close an issue.
  search_code      : Search code within a repo for a query string.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_MAX_ITEMS = 20   # cap list responses to avoid context overflow


def github_tool(
    action: str,
    repo: str = "",
    issue_number: int = 0,
    pr_number: int = 0,
    title: str = "",
    body: str = "",
    head: str = "",
    base: str = "",
    path: str = "",
    content: str = "",
    message: str = "",
    comment: str = "",
    query: str = "",
    branch: str = "",
) -> str:
    """
    Perform a GitHub operation.

    action       : One of the actions listed in the module docstring.
    repo         : "owner/name" (falls back to GITHUB_REPO env var if omitted).
    issue_number : Issue number for get_issue, add_comment, close_issue.
    pr_number    : PR number for add_comment.
    title        : Title for create_pr or new issue.
    body         : Body text for create_pr, create_branch description, or add_comment.
    head         : Head branch for create_pr or create_branch source.
    base         : Base branch for create_pr / create_branch target.
    path         : File path in the repo for get_file / commit_file.
    content      : File content (UTF-8 text) for commit_file.
    message      : Commit message for commit_file.
    comment      : Comment text for add_comment.
    query        : Search string for search_code.
    branch       : Branch name for create_branch (new branch) or get_file.
    """
    try:
        from github import Github, GithubException  # type: ignore
    except ImportError:
        return (
            "Error: PyGithub is not installed.\n"
            "Install it with: pip install PyGithub"
        )

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return (
            "Error: GITHUB_TOKEN is not set.\n"
            "Generate a Personal Access Token at https://github.com/settings/tokens\n"
            "and add GITHUB_TOKEN=<token> to your .env file."
        )

    repo_name = (repo or os.environ.get("GITHUB_REPO", "")).strip()
    action = (action or "").strip().lower()

    if not action:
        return "Error: 'action' is required."

    try:
        gh = Github(token)

        # ── Actions that don't need a specific repo ────────────────────
        if action == "list_repos":
            user = gh.get_user()
            repos = list(user.get_repos())[:_MAX_ITEMS]
            lines = [f"Repos for {user.login}:"]
            for r in repos:
                lines.append(f"  • {r.full_name}  [{r.private and 'private' or 'public'}]  ⭐{r.stargazers_count}")
            return "\n".join(lines)

        # All other actions need a repo
        if not repo_name:
            return (
                "Error: 'repo' is required (or set GITHUB_REPO env var).\n"
                "Format: 'owner/repository-name'"
            )

        r = gh.get_repo(repo_name)

        if action == "list_issues":
            issues = list(r.get_issues(state="open"))[:_MAX_ITEMS]
            if not issues:
                return f"No open issues in {repo_name}."
            lines = [f"Open issues in {repo_name}:"]
            for i in issues:
                lines.append(f"  #{i.number}: {i.title}  [{', '.join(l.name for l in i.labels)}]")
            return "\n".join(lines)

        if action == "get_issue":
            if not issue_number:
                return "Error: 'issue_number' is required for get_issue."
            issue = r.get_issue(issue_number)
            lines = [
                f"Issue #{issue.number}: {issue.title}",
                f"State   : {issue.state}",
                f"Author  : {issue.user.login}",
                f"Labels  : {', '.join(l.name for l in issue.labels) or 'none'}",
                f"",
                issue.body or "(no body)",
            ]
            comments = list(issue.get_comments())[:10]
            if comments:
                lines.append(f"\n--- {len(comments)} comment(s) ---")
                for c in comments:
                    lines.append(f"\n@{c.user.login}: {c.body[:500]}")
            return "\n".join(lines)

        if action == "list_branches":
            branches = [b.name for b in list(r.get_branches())[:_MAX_ITEMS]]
            return f"Branches in {repo_name}:\n" + "\n".join(f"  • {b}" for b in branches)

        if action == "create_branch":
            if not branch:
                return "Error: 'branch' (new branch name) is required."
            base_ref = base or r.default_branch
            source = r.get_branch(base_ref)
            r.create_git_ref(ref=f"refs/heads/{branch}", sha=source.commit.sha)
            return f"Branch '{branch}' created from '{base_ref}' in {repo_name}."

        if action == "get_file":
            if not path:
                return "Error: 'path' (file path in repo) is required."
            ref = branch or r.default_branch
            try:
                file_content = r.get_contents(path, ref=ref)
            except GithubException as e:
                return f"Error: File '{path}' not found on branch '{ref}' — {e.data.get('message', e)}"
            if isinstance(file_content, list):
                return f"Error: '{path}' is a directory, not a file."
            decoded = file_content.decoded_content.decode("utf-8", errors="replace")
            lines_count = decoded.count("\n")
            if lines_count > 200:
                decoded = "\n".join(decoded.splitlines()[:200]) + f"\n\n[Truncated — showing 200/{lines_count} lines]"
            return f"File: {path}  (branch: {ref})\n{'─'*60}\n{decoded}"

        if action == "commit_file":
            if not path:
                return "Error: 'path' is required for commit_file."
            if not content:
                return "Error: 'content' is required for commit_file."
            commit_msg = message or f"AetheerAI: update {path}"
            ref = branch or r.default_branch
            content_bytes = content.encode("utf-8")
            try:
                existing = r.get_contents(path, ref=ref)
                result = r.update_file(
                    path=path,
                    message=commit_msg,
                    content=content_bytes,
                    sha=existing.sha,
                    branch=ref,
                )
                return f"Updated '{path}' on '{ref}' — commit {result['commit'].sha[:8]}"
            except GithubException:
                # File doesn't exist yet — create it
                result = r.create_file(
                    path=path,
                    message=commit_msg,
                    content=content_bytes,
                    branch=ref,
                )
                return f"Created '{path}' on '{ref}' — commit {result['commit'].sha[:8]}"

        if action == "create_pr":
            if not title:
                return "Error: 'title' is required for create_pr."
            if not head:
                return "Error: 'head' (source branch) is required for create_pr."
            base_branch = base or r.default_branch
            pr = r.create_pull(title=title, body=body or "", head=head, base=base_branch)
            return (
                f"Pull Request created: #{pr.number} '{pr.title}'\n"
                f"URL: {pr.html_url}\n"
                f"{head} → {base_branch}"
            )

        if action == "list_prs":
            prs = list(r.get_pulls(state="open"))[:_MAX_ITEMS]
            if not prs:
                return f"No open Pull Requests in {repo_name}."
            lines = [f"Open PRs in {repo_name}:"]
            for pr in prs:
                lines.append(f"  #{pr.number}: {pr.title}  [{pr.head.ref} → {pr.base.ref}]")
            return "\n".join(lines)

        if action == "add_comment":
            if not comment:
                return "Error: 'comment' is required for add_comment."
            if issue_number:
                issue = r.get_issue(issue_number)
                c = issue.create_comment(comment)
                return f"Comment added to issue #{issue_number}: {c.html_url}"
            if pr_number:
                pr = r.get_pull(pr_number)
                c = pr.create_issue_comment(comment)
                return f"Comment added to PR #{pr_number}: {c.html_url}"
            return "Error: specify 'issue_number' or 'pr_number' for add_comment."

        if action == "close_issue":
            if not issue_number:
                return "Error: 'issue_number' is required for close_issue."
            issue = r.get_issue(issue_number)
            issue.edit(state="closed")
            return f"Issue #{issue_number} closed in {repo_name}."

        if action == "search_code":
            if not query:
                return "Error: 'query' is required for search_code."
            results = gh.search_code(query=f"{query} repo:{repo_name}")
            items = list(results[:_MAX_ITEMS])
            if not items:
                return f"No code matches for '{query}' in {repo_name}."
            lines = [f"Code search results for '{query}' in {repo_name}:"]
            for item in items:
                lines.append(f"  • {item.path}  (sha: {item.sha[:8]})")
            return "\n".join(lines)

        return f"Unknown action '{action}'. See module docstring for valid actions."

    except GithubException as exc:  # type: ignore[possibly-undefined]
        msg = exc.data.get("message", str(exc)) if isinstance(exc.data, dict) else str(exc)
        return f"GitHub API error ({exc.status}): {msg}"
    except Exception as exc:
        logger.error("github_tool: unexpected error: %s", exc)
        return f"Error: {exc}"
