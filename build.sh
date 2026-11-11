#!/bin/bash

# VSP Agent Build Script for Linux/Mac

echo "===================================="
echo "VSP Agent - Build Script"
echo "===================================="
echo ""

# Check if build tools are installed
echo "[1/4] Checking build tools..."
if ! pip show build &> /dev/null; then
    echo "Installing build tools..."
    pip install build twine
else
    echo "Build tools already installed!"
fi
echo ""

# Clean previous builds
echo "[2/4] Cleaning previous builds..."
rm -rf build/ dist/ *.egg-info
echo "Previous builds cleaned!"
echo ""

# Build the package
echo "[3/4] Building package..."
python -m build
if [ $? -ne 0 ]; then
    echo "ERROR: Build failed!"
    exit 1
fi
echo "Package built successfully!"
echo ""

# Check the package
echo "[4/4] Checking package..."
twine check dist/*
if [ $? -ne 0 ]; then
    echo "WARNING: Package check failed!"
else
    echo "Package check passed!"
fi
echo ""

echo "===================================="
echo "Build Complete!"
echo "===================================="
echo ""
echo "Next steps:"
echo "1. Test locally: pip install -e ."
echo "2. Upload to PyPI: twine upload dist/*"
echo ""
echo "See README.md for install and release steps."
echo ""


