# Publishing Guide

## 1. Create a GitHub Release
To create a new release and trigger PyPI publishing:
```bash
git tag v1.0.2
git push origin v1.0.2
```
Then go to the GitHub web interface and create a Release from this tag.

## 2. PyPI Publishing
The CI handles this automatically! Once a GitHub Release is published, the `.github/workflows/publish.yml` workflow uses Trusted Publishing to securely build and upload the package to PyPI. No API tokens are needed.

## 3. AUR Submission Process
To submit for the first time:
1. Ensure you have an account on [aur.archlinux.org](https://aur.archlinux.org).
2. Upload your SSH key to your AUR account settings.
3. Clone the new package repository (replace `<pkgname>` with `hypr-session` or `hypr-session-git`):
   ```bash
   git clone ssh://aur@aur.archlinux.org/<pkgname>.git
   ```
4. Copy the `PKGBUILD` and `PKGBUILD.install` into the directory.
5. Generate the `.SRCINFO` file:
   ```bash
   makepkg --printsrcinfo > .SRCINFO
   ```
6. Commit and push:
   ```bash
   git add PKGBUILD .SRCINFO PKGBUILD.install
   git commit -m "Initial release"
   git push
   ```

## 4. Updating the AUR Package
When a new version is released:
1. Update `pkgver` in the `PKGBUILD`.
2. Update checksums (if not using SKIP):
   ```bash
   updpkgsums
   ```
3. Regenerate `.SRCINFO`:
   ```bash
   makepkg --printsrcinfo > .SRCINFO
   ```
4. Commit and push:
   ```bash
   git add PKGBUILD .SRCINFO
   git commit -m "Bump version to v1.0.2"
   git push
   ```
