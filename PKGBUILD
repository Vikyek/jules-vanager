# Maintainer: Vikyek <https://github.com/Vikyek>
pkgname=jules-vanager
pkgver=1.0.0
pkgrel=3
pkgdesc="Google Jules API Manager, Listener Daemon, Interactive TUI, and Conky HUD"
arch=('any')
url="https://github.com/Vikyek/jules-vanager"
license=('GPL-3.0-only')
depends=('python' 'python-requests' 'python-textual' 'github-cli' 'systemd')
optdepends=(
    'xclip: Clipboard support for X11'
    'wl-clipboard: Clipboard support for Wayland'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
    cd "$pkgname-$pkgver"

    # Install Python modules into /usr/share/jules-vanager
    install -d "$pkgdir/usr/share/$pkgname"
    install -Dm644 *.py "$pkgdir/usr/share/$pkgname/"

    # Install wrapper executables in /usr/bin
    install -d "$pkgdir/usr/bin"
    for cmd in manager listener tui hud scraper cookie-extractor start; do
        py_file="jules_${cmd}.py"
        [[ "$cmd" == "start" ]] && py_file="jules_start.py"

        cat <<EOF > "$pkgdir/usr/bin/jules-$cmd"
#!/bin/sh
export PYTHONPATH="/usr/share/$pkgname:\$PYTHONPATH"
exec python3 /usr/share/$pkgname/$py_file "\$@"
EOF
        chmod 755 "$pkgdir/usr/bin/jules-$cmd"
    done

    ln -s jules-manager "$pkgdir/usr/bin/jules-vanager"

    # Install system units, desktop launchers, and docs
    install -Dm644 jules-tui.desktop "$pkgdir/usr/share/applications/jules-tui.desktop"
    install -Dm644 jules-hud.desktop "$pkgdir/usr/share/applications/jules-hud.desktop"
    install -Dm644 jules-listener.service "$pkgdir/usr/lib/systemd/user/jules-listener.service"
    install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"

    # Install manpages
    if [ -d "man1" ]; then
        install -d "$pkgdir/usr/share/man/man1"
        for manfile in man1/*.1; do
            [ -f "$manfile" ] && install -Dm644 "$manfile" "$pkgdir/usr/share/man/man1/"
        done
        ln -sf jules-manager.1.gz "$pkgdir/usr/share/man/man1/jules-vanager.1.gz" 2>/dev/null || \
        ln -sf jules-manager.1 "$pkgdir/usr/share/man/man1/jules-vanager.1"
    fi
}
