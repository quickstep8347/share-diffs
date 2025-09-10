## Sharing diffs of git repos

This is a simple tool to share diffs of git repositories with sandboxed environments. The shared files are encrypted.

Concretely, for a list of git repos, it creates binary files of the diffs of the current checked out branch to the stored last hash of that repo. 
These binary files are encrypted with the public key and can only be decrypted with the private key.

## How to

Imagine we want to sync git repos between a remote server that has access to github to our local environment that only has python installed.


### Remote side

In the following example we transfer the data via pdfs - for this to work you need to install the `pdf` extra dependencies (e.g. via `pip install share_diffs[pdf]`)

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

### Local side

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

## Sharing via QR Codes

This scenario assumes you have access to the display of the remote, but no connection is possible.

### Remote side

Make sure to install the `qr` extra dependencies (e.g. via `pip install share_diffs[qr]`)

Using compression is optional, but recommended. If it is used, encryption should be disabled to allow for better compression.

```python
from pathlib import Path
from share_diffs.repos import Repos
from share_diffs.pdfs import attach_to_pdfs
from share_diffs.qr import generate_qr_site
import zlib

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
def identity(x):
    return x
# create unencrypted bytes object
diff_data = remote_repos.create_diffs(encrypt_func=identity)
diff_data_compressed = zlib.compress(diff_data)
generate_qr_site(diff_data_compressed, out_dir="qr_sender")
```
This creates a website in the folder "qr_sender"

### Local side

Suggested way is to download the `qr_reader.html` file to your phone and host it on your phone (access rights to qr-reader are not granted if just opened as html document from your downloads)

1. Install Termux (from F-Droid).

2. In Termux:
```bash
pkg update
pkg install python
termux-setup-storage   # grant storage access
cd ~/storage/Download  # or wherever the file is
python -m http.server 8000
```

On the same phone, open Chrome and visit:
http://localhost:8000/qr_reader.html

(Chrome treats localhost as a secure context; camera works.)

Allow the Camera permission when prompted.

Tip: If you don’t see a prompt, long-press the URL bar → “Site settings” → set Camera to Allow, then reload.

3. Download the file

4. Recover diff

```python
import zlib
from share_diffs.repos import Repos

with open("downloaded_file.bin", "rb") as f:
    diff_data_compressed = f.read()

def identity(x):
    return x

diff_data = zlib.decompress(diff_data_compressed)
local_repos = Repos(base_path=self.local_git_dir)
local_repos.apply_diffs(combined_diff=diff_data, decrypt_func=identity)
```

### Efficiency and default settings

At the default 512 bytes chunk-size and 5 fps (which can be parsed quite reliably), the transfer rate is 2.5 KB/s.

To send 13.2 KB of data uncompressed, 30 2.6 MB of QR-Codes are generated with the default settings, a 200x increase.

In my tests, the best transfer rate was achieved with 1024 bytes chunk-size at 5 fps.