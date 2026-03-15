#!/bin/bash
set -e

echo "======================="
echo "Building wxPython wagon"
echo "======================="

echo "Architecture check:"
uname -m

echo ""
echo "Installing build dependencies..."
apt-get update
apt-get install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libsqlite3-dev libreadline-dev libffi-dev curl libbz2-dev wget libgtk-3-dev

echo ""
echo "Building Python 3.13 from source..."
cd /tmp
curl -O https://www.python.org/ftp/python/3.13.5/Python-3.13.5.tar.xz
tar -xf Python-3.13.5.tar.xz
cd Python-3.13.5
echo "Configure..."
./configure
echo "Compile (this will take a few minutes)..."
make -j4
make install

echo ""
echo "Python version:"
python3.13 --version

echo ""
echo "Installing pip..."
curl -O https://bootstrap.pypa.io/get-pip.py
python3.13 get-pip.py

echo ""
echo "Installing wagon..."
python3.13 -m pip install wagon[dist]

echo ""
echo "Building wxPython wagon (this will take 30-60 minutes)..."
cd /usr/src
python3.13 -m wagon create wxPython==4.2.5

echo ""
echo "Build complete!"
ls -lh /usr/src/*.wgn
