from typing import Optional

from pydantic import BaseModel


class ConnectRequest(BaseModel):
    pat: str
    org_name: Optional[str] = None


class ConnectResponse(BaseModel):
    valid: bool
    user_login: str


class RepoInfo(BaseModel):
    full_name: str
    name: str
    description: str = ""
    language: str = ""
    default_branch: str = "main"
    is_selected: bool = False
    selected_branch: str = ""


class SelectRepoRequest(BaseModel):
    repo_full_name: str
    branch: str


class ActivateConnectionRequest(BaseModel):
    user_login: str
    org_name: str = ""

