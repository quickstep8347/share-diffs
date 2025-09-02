import subprocess
from typing import Callable
import unittest
import tempfile
import shutil
from pydantic import TypeAdapter
from pathlib import Path
from share_diffs.main import (
    checkout_all_repos,
    get_diff,
    apply_diff,
    Repo
)
from git import Repo as GitRepo
import json
import hashlib
from pathlib import Path

def file_hash(file_path):
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with file_path.open('rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def standard_filter_file(p: Path) -> bool:
    """excludes all files folders (and all its subfolders and files) that start with "."
    """
    return not any(part.startswith(".") for part in p.relative_to(p.anchor).parts)


def folders_identical(folder1: str|Path, folder2: str|Path, filter_fn: None|Callable[[Path],bool]=standard_filter_file) -> bool:
    """Compare the contents of two folders recursively by file hashes. Returns true if they are identical.
    filter_fn is a function that takes a Path and can decide to filter it or not. E.g. used to filter out
    all folders starting with a "."
    """
    folder1, folder2 = Path(folder1), Path(folder2)
    
    def filtered_files(folder):
        return {
            p.relative_to(folder) for p in folder.rglob('*')
            if p.is_file() and (filter_fn is None or filter_fn(p))
        }
    
    files1 = filtered_files(folder1)
    files2 = filtered_files(folder2)
    print(f"Checking {len(files1)} vs {len((files2))} files")

    only_in_folder1 = files1 - files2
    only_in_folder2 = files2 - files1
    common_files = files1 & files2
    
    if only_in_folder1:
        print("Files only in", folder1)
        for file in sorted(only_in_folder1):
            print("  ", file)
    
    if only_in_folder2:
        print("Files only in", folder2)
        for file in sorted(only_in_folder2):
            print("  ", file)
    
    differing_files = []
    for file in common_files:
        hash1 = file_hash(folder1 / file)
        hash2 = file_hash(folder2 / file)
        if hash1 != hash2:
            differing_files.append(file)
    
    if differing_files:
        print("Files with different contents:")
        for file in differing_files:
            print("  ", file)
    
    if not (only_in_folder1 or only_in_folder2 or differing_files):
        return True
    
    return False


class TestShareDiffsIntegration(unittest.TestCase):
    def setUp(self):
        # Create two temporary directories for old and new repositories
        self.temp_dir_old = tempfile.mkdtemp(prefix="repo_old_")
        self.temp_dir_new = tempfile.mkdtemp(prefix="repo_new_")
        
        # Define separate repo.json files for each
        self.repo_file_old = Path(self.temp_dir_old) / "repos.json"
        self.repo_file_new = Path(self.temp_dir_new) / "repos.json"
        
        # Repository URL to be used for the test
        self.repo_url = "https://github.com/githubtraining/hellogitworld.git"
        
        # List containing only the test repository
        self.repo_links = [self.repo_url]
        
        # Initialize both repositories
        # After cloning, checkout to HEAD~10 in the old repo
        self.old_repo_path = Path(self.temp_dir_old) / "hellogitworld"
        self.old_repo = GitRepo.clone_from(self.repo_url, self.old_repo_path)

        subprocess.run(
            ["git", "reset", "--hard", 'HEAD~10'],
            cwd=self.old_repo_path,
            check=True,  # Raise an error if git apply fails
        )
        
        # Update the repos.json for the old repository with the specific commit
        ta = TypeAdapter(list[Repo])
        repos_old = [Repo(path=str(self.old_repo_path))]
        with open(self.repo_file_old, "wb") as f:
            f.write(ta.dump_json(repos_old))

        self.new_repo_path = Path(self.temp_dir_new) / "hellogitworld"
        self.new_repo = GitRepo.clone_from(self.repo_url, self.new_repo_path)
        subprocess.run(
            ["git", "reset", "--hard", 'HEAD~10'],
            cwd=self.new_repo_path,
            check=True,  # Raise an error if git apply fails
        )
        repos_new = [Repo(path=str(self.new_repo_path), last_commit=self.new_repo.head.commit.hexsha)]
        with open(self.repo_file_new, "wb") as f:
            f.write(ta.dump_json(repos_new))

    def tearDown(self):
        # Remove temporary directories after the test
        shutil.rmtree(self.temp_dir_old)
        shutil.rmtree(self.temp_dir_new)

    def test_diff_and_apply(self):
        checkout_all_repos(
            repo_links=self.repo_links,
            root_folder=self.temp_dir_new,
            repo_file=str(self.repo_file_new)
        )

        self.assertTrue(
            self.new_repo.active_branch.commit.hexsha == "ef7bebf8bdb1919d947afe46ab4b2fb4278039b3",
            "It seems like the git pull didn't work properly"
        )
        self.assertTrue(
            self.old_repo.active_branch.commit.hexsha == "bf7a9a5ee025edee0e610bd7ba23c0704b53c6db",
            "This should be at Head~10"
        )
        
        # Generate diffs based on the old repository state
        diffs = get_diff(
            repo_links=self.repo_links,
            repo_file=str(self.repo_file_new)
        )
        
        print("Applying diffs to the old repository...")
        # Apply the diffs to the old repository
        apply_diff(
            diff=diffs,
            root_folder=self.temp_dir_old
        )
        
        # Note: In this setup, the commit hashes are not identical because the commit history is different.

        # # Now, the old repository should be at the latest commit
        # updated_old_repo = GitRepo(Path(self.temp_dir_old) / "hellogitworld")
        
        # # Ensure both repositories are on the same commit
        # old_commit = updated_old_repo.head.commit.hexsha
        # new_commit = self.new_repo.head.commit.hexsha
        
        # print(f"Old Repo Commit after applying diffs: {old_commit}")
        # print(f"New Repo Commit: {new_commit}")
        
        self.assertTrue(
            folders_identical(self.old_repo_path, self.new_repo_path),
            "After applying diffs, the old repository should match the new repository."
        )
        

class TestShareDiffsIntegrationEmptyRepo(unittest.TestCase):
    def setUp(self):
        # Create two temporary directories for old and new repositories
        self.temp_dir_old = tempfile.mkdtemp(prefix="repo_old_")
        self.temp_dir_new = tempfile.mkdtemp(prefix="repo_new_")
        
        
        # Repository URL to be used for the test
        self.repo_url = "https://github.com/githubtraining/hellogitworld.git"
        
        # List containing only the test repository
        self.repo_links = [self.repo_url]
        
        # Initialize both repositories
        # After cloning, checkout to HEAD~10 in the old repo
        self.old_repo_path = Path(self.temp_dir_old) / "hellogitworld"

        self.new_repo_path = Path(self.temp_dir_new) / "hellogitworld"
        self.repo_file_new = Path(self.temp_dir_new) / "repos.json"
        self.new_repo = GitRepo.clone_from(self.repo_url, self.new_repo_path)
        repos_new = [Repo(path=str(self.new_repo_path))]
        ta = TypeAdapter(list[Repo])
        with open(Path(self.temp_dir_new) / "repos.json", "wb") as f:
            f.write(ta.dump_json(repos_new))

    def tearDown(self):
        # Remove temporary directories after the test
        shutil.rmtree(self.temp_dir_old)
        shutil.rmtree(self.temp_dir_new)

    def test_diff_and_apply(self):
        self.assertTrue(
            self.new_repo.active_branch.commit.hexsha == "ef7bebf8bdb1919d947afe46ab4b2fb4278039b3",
            "It seems like the git pull didn't work properly"
        )
        
        # Generate diffs based on the old repository state
        diffs = get_diff(
            repo_links=self.repo_links,
            repo_file=str(self.repo_file_new)
        )
        
        print("Applying diffs to the old repository...")
        # Apply the diffs to the old repository
        apply_diff(
            diff=diffs,
            root_folder=self.temp_dir_old
        )
        
        self.assertTrue(
            folders_identical(self.old_repo_path, self.new_repo_path),
            "After applying diffs, the old repository should match the new repository."
        )
        

if __name__ == "__main__":
    unittest.main()
