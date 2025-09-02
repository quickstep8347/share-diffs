import re

from git import Repo as GitRepo
from pathlib import Path
from pydantic import TypeAdapter
import json

from share_diffs.repos import get_repo_diffs, apply_repo_diffs, Repo
from share_diffs.crypto import decrypt


def checkout_all_repos(
    repo_links: list[str], root_folder: str = "repos", repo_file: str = "repos.json"
) -> None:
    """
    Clones or pulls the latest commits for all repositories listed in repo_links.
    Updates or creates the repos.json file with the current state of all repositories.

    Args:
        repo_links (list[str]): List of Git repository URLs.
        root_folder (str): The root directory where repositories will be cloned.
        repo_file (str): Path to the JSON file storing repository information.
    """
    repos = []
    ta = TypeAdapter(list[Repo])

    # Load existing repos if the repo_file exists
    if Path(repo_file).exists():
        with open(repo_file, "r") as f:
            try:
                repos = ta.validate_json(f.read())
            except json.JSONDecodeError:
                print(
                    f"Warning: {repo_file} is not a valid JSON. Starting with an empty repo list."
                )
                repos = []
    else:
        repos = []

    # Create root_folder if it doesn't exist
    Path(root_folder).mkdir(parents=True, exist_ok=True)

    for link in repo_links:
        repo_name = link.rstrip("/").split("/")[-1].replace(".git", "")
        repo_path = Path(root_folder) / repo_name
        existing_repo = next((r for r in repos if Path(r.path).name == repo_name), None)

        if not repo_path.exists():
            # Clone the repository
            GitRepo.clone_from(link, repo_path)
            git_repo = GitRepo(repo_path)
            # last_commit must be None so that the first diff is against the default empty repo
            repos.append(Repo(path=str(repo_path)))
        else:
            # Pull the latest changes
            git_repo = GitRepo(repo_path)
            origin = git_repo.remotes.origin
            origin.pull()
            if not existing_repo:
                repos.append(Repo(path=str(repo_path)))

    # Save the updated repos to repo_file
    with open(repo_file, "wb") as f:
        f.write(ta.dump_json(repos))


def get_diff(repo_links: list[str], repo_file: str = "repos.json") -> bytes:
    """
    Checks out all repos, then gets the repo diffs and returns as a string.

    Args:
        repo_links (list[str]): List of Git repository URLs.
        repo_file (str): Path to the JSON file storing repository information.

    Returns:
        str: The combined diffs of all repositories as a string.
    """
    checkout_all_repos(repo_links=repo_links, root_folder="repos", repo_file=repo_file)
    return get_repo_diffs(repo_file=repo_file)


def repos_in_diff(diff: bytes, root_folder: str = "repos") -> list[Repo]:
    """
    Extracts repository names from the diff string using regex and decrypts them.

    Args:
        diff (str): The combined diff string containing encrypted repository names.

    Returns:
        list[Repo]: A list of Repo objects with decrypted repository names.
    """

    repo_pattern = rb"---NEW REPO---(.*?)---CONTENT STARTS---"
    matches = re.findall(repo_pattern, diff, re.DOTALL)
    repos = []

    for encrypted_repo_name in matches:
        try:
            decrypted_name = decrypt(encrypted_repo_name)
            # Assuming the decrypted name corresponds to the folder name
            repo_path = Path(root_folder) / decrypted_name
            repos.append(Repo(path=str(repo_path)))
        except Exception as e:
            print(
                f"Failed to decrypt or find repository for {encrypted_repo_name}: {e}"
            )
            continue

    return repos


def apply_diff(diff: bytes, root_folder: str = "repos"):
    """
    Applies the combined diff string to the corresponding repositories.

    Args:
        diff (str): The combined diff string containing encrypted repository names and patch data.
    """
    repos = repos_in_diff(diff, root_folder=root_folder)
    apply_repo_diffs(repos, diff)
