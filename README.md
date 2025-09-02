## Sharing diffs of git repos

This is a simple tool to share diffs of git repositories with sandboxed environments. The shared files are encrypted.

Concretely, for a list of git repos, it creates binary files of the diffs of the current checked out branch to the stored last hash of that repo. 
These binary files are encrypted with the public key and can only be decrypted with the private key.