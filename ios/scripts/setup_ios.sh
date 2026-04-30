#!/usr/bin/env bash
# Sets up the iOS build prerequisites:
#   1. Downloads python-apple-support XCFramework → ios/Python/
#   2. Installs rubicon-objc + numpy + Pillow iOS/simulator wheels → ios/PyPackages/
#   3. Copies luvatrix_core + hello_world into ios/PyPackages/
#
# Requirements: curl, pip3 (macOS system Python is fine for the pip step)
# Run from the repo root: bash ios/scripts/setup_ios.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IOS_DIR="$REPO_ROOT/ios"
PYTHON_DIR="$IOS_DIR/Python"
LEGACY_PACKAGES_DIR="$IOS_DIR/PyPackages"
SIM_PACKAGES_DIR="$IOS_DIR/PyPackages-simulator"
DEVICE_PACKAGES_DIR="$IOS_DIR/PyPackages-device"

# ── 1. python-apple-support ────────────────────────────────────────────────────
# Keep this aligned with the iOS NumPy wheel ABI below.
PYTHON_VER="${LUVATRIX_IOS_PYTHON_VERSION:-3.12}"
SUPPORT_TAG="${LUVATRIX_IOS_PYTHON_SUPPORT_TAG:-3.12-b8}"
SUPPORT_URL="https://github.com/beeware/Python-Apple-support/releases/download/${SUPPORT_TAG}/Python-${PYTHON_VER}-iOS-support.${SUPPORT_TAG##*-}.tar.gz"

echo "→ Downloading python-apple-support ${SUPPORT_TAG}..."
PYTHON_STAGE="$(mktemp -d -t luvatrix-python-support)"
TMPFILE="$(mktemp -t python-apple-support).tar.gz"
cleanup_downloads() {
    rm -f "${TMPFILE:-}"
    if [ -n "${PYTHON_STAGE:-}" ]; then
        rm -rf "$PYTHON_STAGE"
    fi
}
trap cleanup_downloads EXIT
curl -L --fail --retry 5 --retry-delay 2 --retry-all-errors --progress-bar -o "$TMPFILE" "$SUPPORT_URL"
echo "→ Extracting..."
tar -xzf "$TMPFILE" -C "$PYTHON_STAGE"
rm "$TMPFILE"
TMPFILE=""

# Normalize: ensure ios/Python/PythonSupport.xcframework exists
if [ ! -d "$PYTHON_STAGE/PythonSupport.xcframework" ] && [ -d "$PYTHON_STAGE/Python.xcframework" ]; then
    mv "$PYTHON_STAGE/Python.xcframework" "$PYTHON_STAGE/PythonSupport.xcframework"
fi
if [ ! -d "$PYTHON_STAGE/PythonSupport.xcframework" ]; then
    echo "error: Expected PythonSupport.xcframework inside ios/Python/ — check release asset structure."
    exit 1
fi
rm -rf "$PYTHON_DIR"
mkdir -p "$(dirname "$PYTHON_DIR")"
mv "$PYTHON_STAGE" "$PYTHON_DIR"
PYTHON_STAGE=""
echo "✓ PythonSupport.xcframework ready"

mkdir -p "$SIM_PACKAGES_DIR" "$DEVICE_PACKAGES_DIR"

install_pure_package() {
    local target_dir="$1"
    local package_spec="$2"
    pip3 install \
        --target "$target_dir" \
        --upgrade \
        --no-deps \
        "$package_spec"
}

# ── 2. rubicon-objc (pure Python — installs anywhere) ─────────────────────────
echo "→ Installing rubicon-objc..."
install_pure_package "$SIM_PACKAGES_DIR" "rubicon-objc>=0.4.9"
install_pure_package "$DEVICE_PACKAGES_DIR" "rubicon-objc>=0.4.9"
echo "✓ rubicon-objc installed"

# ── 3. numpy ──────────────────────────────────────────────────────────────────
# BeeWare publishes iOS binary wheels on its Anaconda index. Force the Python
# ABI/platform tags so an ambient desktop/uv pip cannot install a mismatched
# cpython-314 wheel into the embedded Python 3.12 bundle.
NUMPY_VER="${LUVATRIX_IOS_NUMPY_VERSION:-1.26.2}"
BEEWARE_PACKAGE_INDEX="https://pypi.anaconda.org/beeware/simple"

install_binary_package_for_platform() {
    local target_dir="$1"
    local package_spec="$2"
    local platform_tag="$3"
    echo "  trying ${package_spec} --platform ${platform_tag}..."
    pip3 install \
        --target "$target_dir" \
        --upgrade \
        --platform "$platform_tag" \
        --python-version "$PYTHON_VER" \
        --implementation cp \
        --abi "cp${PYTHON_VER/./}" \
        --only-binary :all: \
        --no-deps \
        --extra-index-url "$BEEWARE_PACKAGE_INDEX" \
        "$package_spec"
}

echo "→ Installing numpy ${NUMPY_VER} for iOS..."
if [ "$(uname -m)" = "arm64" ]; then
    SIM_PLATFORM="ios_13_0_arm64_iphonesimulator"
else
    SIM_PLATFORM="ios_13_0_x86_64_iphonesimulator"
fi
DEVICE_PLATFORM="ios_13_0_arm64_iphoneos"

rm -rf "$SIM_PACKAGES_DIR"/numpy "$SIM_PACKAGES_DIR"/numpy-*.dist-info "$SIM_PACKAGES_DIR"/bin/numpy-config
rm -rf "$DEVICE_PACKAGES_DIR"/numpy "$DEVICE_PACKAGES_DIR"/numpy-*.dist-info "$DEVICE_PACKAGES_DIR"/bin/numpy-config
NUMPY_SIM_OK=0
NUMPY_DEVICE_OK=0
install_binary_package_for_platform "$SIM_PACKAGES_DIR" "numpy==${NUMPY_VER}" "$SIM_PLATFORM" && NUMPY_SIM_OK=1 || true
install_binary_package_for_platform "$DEVICE_PACKAGES_DIR" "numpy==${NUMPY_VER}" "$DEVICE_PLATFORM" && NUMPY_DEVICE_OK=1 || true

if [ "$NUMPY_SIM_OK" -eq 1 ] && [ "$NUMPY_DEVICE_OK" -eq 1 ]; then
    echo "✓ numpy installed"
else
    echo ""
    echo "error: Could not install numpy automatically."
    echo "   Luvatrix iOS requires numpy by default so simulator/device runs do not"
    echo "   silently fall back to the slow pure-Python array backend."
    echo "   To install numpy manually, install BeeWare wheels into ios/PyPackages-simulator and ios/PyPackages-device."
    echo "   To intentionally allow the slow fallback, rerun with:"
    echo "   LUVATRIX_ALLOW_PURE_PYTHON_IOS=1 bash ios/scripts/setup_ios.sh"
    if [ "${LUVATRIX_ALLOW_PURE_PYTHON_IOS:-0}" != "1" ]; then
        exit 1
    fi
fi

# ── 4. Pillow ─────────────────────────────────────────────────────────────────
# MatrixUIFrameRenderer can run without Pillow, but real font rasterization
# (Comic Mono instead of the emergency bitmap font) needs Pillow on iOS.
PILLOW_VER="${LUVATRIX_IOS_PILLOW_VERSION:-11.0.0}"
echo "→ Installing Pillow ${PILLOW_VER} for iOS..."
rm -rf "$SIM_PACKAGES_DIR"/PIL "$SIM_PACKAGES_DIR"/pillow-*.dist-info "$SIM_PACKAGES_DIR"/Pillow-*.dist-info
rm -rf "$DEVICE_PACKAGES_DIR"/PIL "$DEVICE_PACKAGES_DIR"/pillow-*.dist-info "$DEVICE_PACKAGES_DIR"/Pillow-*.dist-info
PILLOW_SIM_OK=0
PILLOW_DEVICE_OK=0
install_binary_package_for_platform "$SIM_PACKAGES_DIR" "pillow==${PILLOW_VER}" "$SIM_PLATFORM" && PILLOW_SIM_OK=1 || true
install_binary_package_for_platform "$DEVICE_PACKAGES_DIR" "pillow==${PILLOW_VER}" "$DEVICE_PLATFORM" && PILLOW_DEVICE_OK=1 || true
if [ "$PILLOW_SIM_OK" -eq 1 ] && [ "$PILLOW_DEVICE_OK" -eq 1 ]; then
    echo "✓ Pillow installed"
else
    echo "warning: Could not install Pillow automatically for all iOS targets; affected targets will use the emergency bitmap font."
fi

# ── 5. luvatrix packages ──────────────────────────────────────────────────────
copy_luvatrix_packages() {
    local target_dir="$1"
    echo "→ Copying luvatrix_core → ${target_dir#$REPO_ROOT/}"
    rsync -a --delete \
        --exclude "__pycache__" \
        --exclude "*.pyc" \
        "$REPO_ROOT/luvatrix_core/" \
        "$target_dir/luvatrix_core/"

    echo "→ Copying luvatrix_ui → ${target_dir#$REPO_ROOT/}"
    rsync -a --delete \
        --exclude "__pycache__" \
        --exclude "*.pyc" \
        "$REPO_ROOT/luvatrix_ui/" \
        "$target_dir/luvatrix_ui/"
}
copy_luvatrix_packages "$SIM_PACKAGES_DIR"
copy_luvatrix_packages "$DEVICE_PACKAGES_DIR"

# ── 6. Comic Mono font asset ──────────────────────────────────────────────────
echo "→ Looking for Comic Mono font..."
FONT_DIRS=("$SIM_PACKAGES_DIR/luvatrix_assets/fonts" "$DEVICE_PACKAGES_DIR/luvatrix_assets/fonts")
for font_dir in "${FONT_DIRS[@]}"; do
    mkdir -p "$font_dir"
done
COMIC_MONO_FOUND=0
for candidate in \
    "$HOME/Library/Fonts/ComicMono.ttf" \
    "$HOME/Library/Fonts/Comic Mono.ttf" \
    "$HOME/Library/Fonts/ComicMono-Regular.ttf" \
    "/Library/Fonts/ComicMono.ttf" \
    "/Library/Fonts/Comic Mono.ttf" \
    "/Library/Fonts/ComicMono-Regular.ttf"
do
    if [ -f "$candidate" ]; then
        for font_dir in "${FONT_DIRS[@]}"; do
            cp "$candidate" "$font_dir/ComicMono.ttf"
        done
        COMIC_MONO_FOUND=1
        break
    fi
done
for candidate in \
    "$HOME/Library/Fonts/ComicMono-Bold.ttf" \
    "$HOME/Library/Fonts/Comic Mono Bold.ttf" \
    "/Library/Fonts/ComicMono-Bold.ttf" \
    "/Library/Fonts/Comic Mono Bold.ttf"
do
    if [ -f "$candidate" ]; then
        for font_dir in "${FONT_DIRS[@]}"; do
            cp "$candidate" "$font_dir/ComicMono-Bold.ttf"
        done
        break
    fi
done
if [ "$COMIC_MONO_FOUND" -eq 1 ]; then
    echo "✓ Comic Mono bundled"
else
    echo "warning: Comic Mono not found in local font directories; iOS text will use the next available font."
fi

# ── 7. hello_world example app ────────────────────────────────────────────────
echo "→ Copying hello_world app..."
for target_dir in "$SIM_PACKAGES_DIR" "$DEVICE_PACKAGES_DIR"; do
    rsync -a --delete \
        --exclude "__pycache__" \
        --exclude "*.pyc" \
        "$REPO_ROOT/examples/hello_world/" \
        "$target_dir/hello_world/"
done

# Keep ios/PyPackages as the simulator package set for older project files and
# manual workflows. Xcode and run-app now select target-specific package dirs.
rm -rf "$LEGACY_PACKAGES_DIR"
cp -a "$SIM_PACKAGES_DIR" "$LEGACY_PACKAGES_DIR"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "✓ Setup complete."
echo ""
echo "Next steps:"
echo "  1. brew install xcodegen   (if not already installed)"
echo "  2. cd ios && xcodegen generate"
echo "  3. open ios/Luvatrix.xcodeproj"
echo "  4. Select 'iPhone 15 Simulator' target and press ⌘R"
