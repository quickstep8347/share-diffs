import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from git import Repo as GitRepo
from pydantic import BaseModel, Field, TypeAdapter

from share_diffs.crypto import decrypt, encrypt


def get_minimal_repo_diff(last_commit: str, path: str) -> bytes:
    """This assumes that the repo is on a newer version than last_commit.

    last_commit: commit to which the diff should be calculated.
    """

    diff_command = [
        "git",
        "diff",
        "--binary",
        "--diff-algorithm=minimal",
        ("4b825dc642cb6eb9a060e54bf8d69288fbee4904" if last_commit in ["", None] else last_commit),
        "HEAD",
    ]
    # Capture diff output in-memory
    return subprocess.run(diff_command, cwd=path, capture_output=True, check=True).stdout


def apply_repo_diff(path: str, diff: bytes) -> None:
    """Applies diff, if necessary creates folder and git init."""
    if not diff:
        # empty update
        return
    if not diff.endswith(b"\n"):
        diff += b"\n"

    repo_path = Path(path)
    if not repo_path.exists():
        # Create the directory if needed
        repo_path.mkdir(parents=True, exist_ok=True)
        # Optionally initialize a new Git repository
        subprocess.run(["git", "init", "."], cwd=repo_path, check=True)
    # Use git apply to apply the patch from memory
    try:
        subprocess.run(
            ["git", "apply", "--binary"],
            # ["git", "apply", "--binary", "--whitespace=fix"],
            cwd=path,
            input=diff,  # Supply patch data via stdin
            capture_output=True,  # Capture both stdout and stderr
            check=True,  # Raise an error if git apply fails
        )
    except subprocess.CalledProcessError as e:
        # Print the error output (usually from stderr) to stdout
        # print("Error applying patch:", e.stderr)
        failed_path = Path(path) / "failed_patch.txt"
        failed_path.write_bytes(diff)
        # Re-raise the exception if you still want the traceback
        raise
        # print("Patch applied successfully!")


def _repo_link_to_name(repo_link: str):
    return repo_link.rstrip("/").split("/")[-1].replace(".git", "")


class Repo(BaseModel):
    path: str = Field(description="folder-path where the Repo is checked out")
    repo_link: str | None = Field(default=None, description="github link")
    last_commit: str | None = Field(default=None, description="last commit that was synced to/from this repo")

    @property
    def name(self):
        return Path(self.path).name

    @property
    def current_commit(self) -> str | None:
        path = Path(self.path)
        if not path.exists():
            return None
        else:
            return GitRepo(path).head.commit.hexsha

    @classmethod
    def from_repo_link(cls, repo_link: str, base_path: str = "repos"):
        repo_name = _repo_link_to_name(repo_link)
        return cls(path=str(Path(base_path) / repo_name), repo_link=repo_link)

    def checkout(self) -> None:
        """
        If folder doesnt exist, create and clone repo into it. If already exists, do a git pull.
        Warning: This assumes you never tempered witht he repo, e.g. checked out a different branch.
        """
        path = Path(self.path)
        if not path.exists():
            repo = GitRepo.clone_from(self.repo_link, path)
        else:
            git_repo = GitRepo(path)
            origin = git_repo.remotes.origin
            origin.pull()

    def create_diff(self, preserve_commit_hash: bool = False) -> bytes:
        if preserve_commit_hash:
            raise NotImplementedError("preserving hash is not yet implemented")
        return get_minimal_repo_diff(last_commit=self.last_commit, path=self.path)

    def apply_diff(self, diff: bytes) -> None:
        """
        diff has to be decrypted
        """
        apply_repo_diff(self.path, diff)


class Repos:
    def __init__(
        self,
        base_path: str | Path,
        encrypt_func: Callable[[bytes], bytes] = encrypt,
        decrypt_func: Callable[[bytes], bytes] = decrypt,
    ):
        """
        base_path: str = Field(description="folder in which contains all repo-folders")
        encrypt_func: Callable[[bytes], bytes]=Field(default=encrypt, exclude=True)
        decrypt_func: Callable[[bytes], bytes]=Field(default=decrypt, exclude=True)
        """
        self.base_path = Path(base_path)
        self.encrypt_func = encrypt_func
        self.decrypt_func = decrypt_func
        if not self.base_path.exists() or not (self.base_path / "repos.json").exists():
            self.base_path.mkdir(parents=True, exist_ok=True)
            self.repos = []
        else:
            ta = TypeAdapter(list[Repo])
            with open(self.base_path / "repos.json", "rb") as f:
                self.repos = ta.validate_json(f.read())

    def _write_repos_json(self):
        ta = TypeAdapter(list[Repo])
        with open(self.base_path / "repos.json", "wb") as f:
            f.write(ta.dump_json(self.repos))

    def add_repo(self, repo_link: str) -> None:
        repo = Repo.from_repo_link(repo_link, base_path=self.base_path)
        if repo.name in self._repo_index:
            return  # repo already exists
        self.repos.append(repo)
        self._write_repos_json()

    @property
    def _repo_index(self) -> dict[str, Repo]:
        """Returns a reverse index for repo-name -> Repo"""
        return {repo.name: Repo for repo in self.repos}

    def checkout_all(self) -> None:
        for repo in self.repos:
            repo.checkout()

    def create_diffs(
        self, encrypt_func: Callable[[bytes], bytes] | None = None, preserve_commit_hash: bool = False
    ) -> bytes:
        """
        creating the encrypted diffs.
        Consider calling .update_commit_hashes() afterwards!
        """
        encrypt_func = encrypt_func or self.encrypt_func
        combined_diff = b""
        for repo in self.repos:
            repo_name_encrypted = encrypt_func(repo.name.encode())
            combined_diff += (
                b"---NEW REPO---"
                + repo_name_encrypted
                + b"---CONTENT STARTS---"
                + encrypt_func(repo.create_diff(preserve_commit_hash=preserve_commit_hash))
            )
        return combined_diff

    def update_commit_hashes(self):
        """This method should be called after syncing so that repos.json contains the current commit hashes"""
        for r in self.repos:
            r.last_commit = r.current_commit
        self._write_repos_json()

    def apply_diffs(self, combined_diff: bytes, decrypt_func: Callable[[bytes], bytes] | None = None) -> None:
        """
        This applies diff and updates Last_commit hashes in repos.json
        THEREFORE THIS METHOD IS NOT IDEMPOTENT
        """
        decrypt_func = decrypt_func or self.decrypt_func
        pattern = rb"---NEW REPO---(.*?)---CONTENT STARTS---(.*?)(?=---NEW REPO---|$)"
        matches = re.findall(pattern, combined_diff, flags=re.DOTALL)
        for encrypted_name, encrypted_diff in matches:
            repo_name = decrypt(encrypted_name).decode()
            repo = self._repo_index.get(repo_name)
            if not repo:
                repo = Repo(path=str(Path(self.base_path) / repo_name))
                self.repos.append(repo)
            try:
                repo.apply_diff(decrypt_func(encrypted_diff))
            except Exception as e:
                continue
        # self.update_commit_hashes()  # only makes sense if preserve_commit_hash=True was selected for diff
