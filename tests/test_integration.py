import subprocess
from typing import Callable
import unittest
import tempfile
import shutil
from pathlib import Path
from share_diffs.repos import Repos
from share_diffs.pdfs import attach_to_pdfs, recover_from_pdfs
import hashlib

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
    return (not any(part.startswith(".") for part in p.relative_to(p.anchor).parts)) and p.name != "repos.json"


def folders_identical(folder1: str|Path, folder2: str|Path, filter_fn: None|Callable[[Path],bool]=standard_filter_file) -> bool:
    """Compare the contents of two folders recursively by file hashes. Returns true if they are identical.
    filter_fn is a function that takes a Path and can decide to filter it out or not. path that evaluates to
    true are kept. E.g. used to filter out all folders starting with a ".", like ".git/*"
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
        self.remote_git_dir = tempfile.mkdtemp(prefix="remote")
        self.local_git_dir = tempfile.mkdtemp(prefix="local")

    def tearDown(self):
        # Remove temporary directories after the test
        shutil.rmtree(self.remote_git_dir)
        shutil.rmtree(self.local_git_dir)

    def test_diff_and_apply(self):
        # first create local repo and check if files are the same
        repo_links = [
            "https://github.com/githubtraining/hellogitworld.git",
            "https://github.com/example-repo/lerna-example.git"
        ]
        remote_repos = Repos(base_path=self.remote_git_dir)
        for repo_link in repo_links:
            remote_repos.add_repo(repo_link=repo_link)
        
        remote_repos.checkout_all()
        subprocess.run(
            ["git", "reset", "--hard", 'HEAD~10'],
            cwd=Path(self.remote_git_dir)/"hellogitworld",
            check=True,  # Raise an error if git apply fails
        )
        diff_data = remote_repos.create_diffs()
        local_repos = Repos(base_path=self.local_git_dir)
        local_repos.apply_diffs(combined_diff=diff_data)
        remote_repos.update_commit_hashes()
        self.assertTrue(
            folders_identical(self.local_git_dir, self.remote_git_dir),
            "After applying diffs, the old repository should match the new repository."
        )

        # now again but with newest version of hellogitworld
        remote_repos = Repos(base_path=self.remote_git_dir)
        remote_repos.checkout_all()
        diff_data = remote_repos.create_diffs()
        local_repos = Repos(base_path=self.local_git_dir)
        local_repos.apply_diffs(combined_diff=diff_data)
        remote_repos.update_commit_hashes()
        self.assertTrue(
            folders_identical(self.local_git_dir, self.remote_git_dir),
            "After applying diffs, the old repository should match the new repository."
        )


class TestShareDiffsPDFIntegration(unittest.TestCase):
    def setUp(self):
        # Create two temporary directories for old and new repositories
        self.remote_git_dir = tempfile.mkdtemp(prefix="remote")
        self.local_git_dir = tempfile.mkdtemp(prefix="local")
        # pdfs gets their own folder to make the check for identical folders work on local vs remote:
        self.pdf_dir = tempfile.mkdtemp(prefix="pdf")

    def tearDown(self):
        # Remove temporary directories after the test
        shutil.rmtree(self.remote_git_dir)
        shutil.rmtree(self.local_git_dir)
        shutil.rmtree(self.pdf_dir)

    def test_diff_and_apply(self):
        # first create local repo and check if files are the same
        repo_links = [
            "https://github.com/githubtraining/hellogitworld.git",
            "https://github.com/example-repo/lerna-example"
        ]
        remote_repos = Repos(base_path=self.remote_git_dir)
        for repo_link in repo_links:
            remote_repos.add_repo(repo_link=repo_link)
        
        remote_repos.checkout_all()
        diff_data = remote_repos.create_diffs()
        pdf_out_folder = Path(self.pdf_dir)
        attach_to_pdfs(pdf_input_folder="tests/pdfs", pdf_output_folder=pdf_out_folder, data=diff_data)
        
        diff_data_pdf = recover_from_pdfs(pdf_out_folder)
        assert(diff_data == diff_data_pdf)
        local_repos = Repos(base_path=self.local_git_dir)
        local_repos.apply_diffs(combined_diff=diff_data_pdf)
        remote_repos.update_commit_hashes()
        self.assertTrue(
            folders_identical(self.local_git_dir, self.remote_git_dir),
            "After applying diffs, the old repository should match the new repository."
        )


if __name__ == "__main__":
    unittest.main()
