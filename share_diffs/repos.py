from pathlib import Path
import re
from pydantic import BaseModel, Field, TypeAdapter

from share_diffs.crypto import encrypt, decrypt


class Repo(BaseModel):
    path: str
    last_commit: str | None = Field(default=None)


def get_repo_diff(repo: Repo) -> bytes:
    import subprocess
    import io

    diff_command = [
        "git",
        "diff",
        "--binary",
        "--diff-algorithm=minimal",
        (
            "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
            if repo.last_commit in ["", None]
            else repo.last_commit
        ),
        "HEAD",
    ]

    # Capture diff output in-memory
    result = subprocess.run(diff_command, cwd=repo.path, capture_output=True, check=True)
    return result.stdout


def apply_repo_diff(repo: Repo, patch_data: bytes) -> None:
    import subprocess
    from pathlib import Path


    if not patch_data.endswith(b"\n"):
        patch_data += b"\n"

    repo_path = Path(repo.path)
    if not repo_path.exists():
        # Create the directory if needed
        repo_path.mkdir(parents=True, exist_ok=True)
        # Optionally initialize a new Git repository
        subprocess.run(["git", "init", "."], cwd=repo_path, check=True)
    # Use git apply to apply the patch from memory
    try:
        result = subprocess.run(
            ['git', 'apply', '--binary'],
            # ["git", "apply", "--binary", "--whitespace=fix"],
            cwd=repo.path,
            input=patch_data,  # Supply patch data via stdin
            capture_output=True, # Capture both stdout and stderr
            check=True,  # Raise an error if git apply fails
        )
    except subprocess.CalledProcessError as e:
        # Print the error output (usually from stderr) to stdout
        print("Error applying patch:\n", e.stderr)
        # Re-raise the exception if you still want the traceback
        raise
    else:
        # If no error, you can process result.stdout or ignore it
        print("Patch applied successfully!")


def get_repo_diffs(repo_file: str = "repos.json") -> bytes:
    from git import Repo as GitRepo

    ta = TypeAdapter(list[Repo])
    with open(repo_file, "r") as f:
        repos = ta.validate_json(f.read())
    combined_patch_data = b""

    for repo in repos:
        repo_path = Path(repo.path)
        repo_name_encrypted = encrypt(repo_path.name.encode())
        combined_patch_data += b"---NEW REPO---" + repo_name_encrypted + b"---CONTENT STARTS---" + get_repo_diff(repo)
        repo.last_commit = GitRepo(repo_path).head.commit.hexsha
    ta.dump_json(repos)
    return combined_patch_data


def apply_repo_diffs(repos: list[Repo], combined_patch_data: bytes) -> None:
    """
    Parses the combined patch data and applies each segment (one per repo)
    by matching the corresponding `Repo` via its (decrypted) folder name.

    The combined patch data is assumed to have the form:
      ---NEW REPO---encrypted_repo_name_1
      <patch-data-for-repo-1>
      ---NEW REPO---encrypted_repo_name_2
      <patch-data-for-repo-2>
      ...
    """
    repo_index = {Path(r.path).name: r for r in repos}
    pattern = rb'---NEW REPO---(.*?)---CONTENT STARTS---(.*?)(?=---NEW REPO---|$)'
    # Explanation:
    # 1) '---NEW REPO---' is our sentinel
    # 2) (.*?) captures the repo name until the first newline (non-greedy)
    # 3) \n consumes the newline
    # 4) (.*?) captures any bytes (including newlines) until we encounter:
    #       '---NEW REPO---' or the end of the entire string ($).
    #    We use DOTALL to allow '.' to span multiple lines
    #    (otherwise '.' won't match newlines).
    
    matches = re.findall(pattern, combined_patch_data, flags=re.DOTALL)
    for (encrypted_name, current_patch_data) in matches:
        repo_name = decrypt(encrypted_name)
        repo = repo_index.get(repo_name)
        if not repo:
            print(f"Didn't find repo {repo_name=}")
            continue
        apply_repo_diff(repo, current_patch_data)

