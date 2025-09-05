## Sharing diffs of git repos

This is a simple tool to share diffs of git repositories with sandboxed environments. The shared files are encrypted.

Concretely, for a list of git repos, it creates binary files of the diffs of the current checked out branch to the stored last hash of that repo. 
These binary files are encrypted with the public key and can only be decrypted with the private key.

## How to

First, in the remote environment with the git repos:

```python
    from pathlib import Path
    from share_diffs.repos import Repos
    from share_diffs.pdfs import attach_to_pdfs

    repo_links = [
        "https://github.com/githubtraining/hellogitworld.git",
        "https://github.com/example-repo/lerna-example"
    ]
    remote_repos = Repos(base_path="repos_remote")

    # this is only necessary the first time, the next times
    # this info is loaded automatically from repos.json when Repos is initiated.
    # but new repos can be added at any time with this syntax
    for repo_link in repo_links:
        remote_repos.add_repo(repo_link=repo_link)
    
    # clone/ pull the current branches:
    remote_repos.checkout_all()
    # create bytes object
    diff_data = remote_repos.create_diffs()

    # how you transport the bytes from remote to local is up to you
    # but we provide a simple tool to add it as pdf attachments.
    # the pdfs in the pdf_out folder can then be shared to local.
    pdf_out_folder = Path("pdf_out")
    attach_to_pdfs(pdf_input_folder="tests/pdfs", pdf_output_folder=pdf_out_folder, data=diff_data)
    # now make sure that for the next time, the git diff is calculated from the now shared state:
    remote_repos.update_commit_hashes()
```

Then, on local side: 

```python
    from pathlib import Path
    from share_diffs.repos import Repos
    from share_diffs.pdfs import recover_from_pdfs
    
    pdf_out_folder = Path("pdf_out")
    diff_data_pdf = recover_from_pdfs(pdf_out_folder)
    local_repos = Repos(base_path=self.local_git_dir)
    local_repos.apply_diffs(combined_diff=diff_data_pdf)
```

Thats it :)