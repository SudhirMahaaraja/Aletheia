import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build", ".pytest_cache"}
ALLOWED_EXTENSIONS = {".py", ".js", ".jsx", ".tsx", ".ts", ".sql", ".md", ".txt", ".text", ".ipynb", ".html", ".css", ".json"}
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB


@dataclass
class RepoInfo:
    full_name: str
    name: str
    description: str
    language: str
    default_branch: str


@dataclass
class FileInfo:
    path: str
    size: int
    sha: str


def _get_headers(pat: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "BWS-SecondBrain",
    }
    if pat and pat.strip():
        headers["Authorization"] = f"token {pat.strip()}"
    return headers


async def _get_credentials_from_db(db) -> tuple[str, str]:
    conn = await db.github_connections.find_one({"active": True})
    if conn:
        return conn.get("pat", ""), conn.get("org_name", "")
    return "", ""


async def list_all_repos(db) -> list[RepoInfo]:
    pat, org = await _get_credentials_from_db(db)
    if not pat:
        return []
    headers = _get_headers(pat)

    repos: list[RepoInfo] = []
    page = 1

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                if org:
                    url = f"https://api.github.com/orgs/{org}/repos?per_page=100&page={page}"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        # Fallback to user repos for the org name
                        url = f"https://api.github.com/users/{org}/repos?per_page=100&page={page}"
                        resp = await client.get(url, headers=headers)
                else:
                    url = f"https://api.github.com/user/repos?per_page=100&page={page}&affiliation=owner"
                    resp = await client.get(url, headers=headers)

                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"GitHub API error: {resp.status_code} - {resp.text[:200]}",
                    )

                data = resp.json()
                if not data:
                    break

                for r in data:
                    repos.append(RepoInfo(
                        full_name=r["full_name"],
                        name=r["name"],
                        description=r.get("description") or "",
                        language=r.get("language") or "",
                        default_branch=r.get("default_branch", "main"),
                    ))

                link_header = resp.headers.get("Link", "")
                if 'rel="next"' not in link_header:
                    break
                page += 1

    except httpx.HTTPError as exc:
        logger.error("GitHub API request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API request failed: {exc}",
        )

    return repos


async def get_repo_branches(repo_full_name: str, db) -> list[str]:
    pat, _ = await _get_credentials_from_db(db)
    if not pat:
        return []
    headers = _get_headers(pat)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/branches?per_page=100",
                headers=headers,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to fetch branches: {resp.status_code}",
                )
            return [b["name"] for b in resp.json()]
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch branches for %s: %s", repo_full_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API request failed: {exc}",
        )


async def fetch_repo_file_tree(
    repo_full_name: str,
    branch: str,
    db,
) -> list[FileInfo]:
    pat, _ = await _get_credentials_from_db(db)
    if not pat:
        return []
    headers = _get_headers(pat)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1",
                headers=headers,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to fetch file tree: {resp.status_code}",
                )

            tree_data = resp.json()
            files: list[FileInfo] = []

            for item in tree_data.get("tree", []):
                if item["type"] != "blob":
                    continue

                path = item["path"]

                # Skip files in excluded directories
                path_parts = path.split("/")
                if any(part in SKIP_DIRS for part in path_parts):
                    continue

                # Check file extension
                filename = path.split("/")[-1]
                ext = ""
                if "." in filename:
                    ext = "." + filename.rsplit(".", 1)[-1].lower()
                
                is_readme = filename.lower().startswith("readme")
                if ext not in ALLOWED_EXTENSIONS and not is_readme:
                    continue

                size = item.get("size", 0)
                if size > MAX_FILE_SIZE:
                    continue

                files.append(FileInfo(
                    path=path,
                    size=size,
                    sha=item.get("sha", ""),
                ))

            return files

    except httpx.HTTPError as exc:
        logger.error("Failed to fetch file tree for %s: %s", repo_full_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API request failed: {exc}",
        )


async def fetch_file_content(
    repo_full_name: str,
    file_path: str,
    branch: str,
    db,
) -> str:
    pat, _ = await _get_credentials_from_db(db)
    headers = _get_headers(pat)
    headers["Accept"] = "application/vnd.github.raw+json"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}?ref={branch}",
                headers=headers,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to fetch file content: {resp.status_code}",
                )
            return resp.text

    except httpx.HTTPError as exc:
        logger.error("Failed to fetch %s from %s: %s", file_path, repo_full_name, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API request failed: {exc}",
        )


async def validate_pat(pat: str, org_name: Optional[str] = None) -> str:
    headers = _get_headers(pat)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://api.github.com/user", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid GitHub PAT",
                )
            user_data = resp.json()
            return user_data.get("login", "")
    except httpx.HTTPError as exc:
        logger.error("PAT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API request failed: {exc}",
        )
