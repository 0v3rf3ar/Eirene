#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
apt-get update
apt-get upgrade -y -o Dpkg::Options::=--force-confnew
apt-get install -y python python-pip python-cryptography python-pillow python-rpds-py maturin clang make pkg-config patchelf binutils
python -m pip install setuptools wheel typing-extensions==4.16.0
python /workspace/scripts/build_termux.py /output
