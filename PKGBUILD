pkgname=hypr-session
pkgver=1.0.1
pkgrel=1
pkgdesc="The missing native session manager for the Hyprland Wayland compositor"
arch=('any')
url="https://github.com/krishiv2489/hypr-session"
license=('MIT')
depends=('python' 'python-typer' 'python-rich')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
source=("https://github.com/krishiv2489/hypr-session/archive/refs/tags/v${pkgver}.tar.gz")
sha256sums=('SKIP')
install=PKGBUILD.install

build() {
    cd "$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
