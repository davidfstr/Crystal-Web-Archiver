# How to make the wxPython wagon

It is important to precompile wxPython for Linux Continuous Integration jobs
because it otherwise takes about 40 minutes to compile wxPython from source.

To compile a new wagon containing wxPython:

* Start a Linux container

```bash
docker run -it --rm -v $(pwd):/usr/src ubuntu:22.04
```

* Install Python 3.8, if appropriate for this .wgn

```bash
# Install Python 3.8 (from source)
apt-get update
apt-get install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libsqlite3-dev libreadline-dev libffi-dev curl libbz2-dev
curl -O https://www.python.org/ftp/python/3.8.2/Python-3.8.2.tar.xz
tar -xf Python-3.8.2.tar.xz
cd Python-3.8.2
./configure
make -j
make install
python3.8 --version
```

* Install Python 3.9, if appropriate for this .wgn

```bash
# Install Python 3.9 (from source)
apt-get update
apt-get install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libsqlite3-dev libreadline-dev libffi-dev curl libbz2-dev
curl -O https://www.python.org/ftp/python/3.9.16/Python-3.9.16.tar.xz
tar -xf Python-3.9.16.tar.xz
cd Python-3.9.16
./configure
make  # NOTE: -j seems to crash Docker
make install
python3.9 --version
```

* Install Python 3.10, if appropriate for this .wgn

TODO: Add instructions, probably based on the Python 3.11 instructions below

* Install Python 3.11, if appropriate for this .wgn

```bash
# Install Python 3.11 and pip
apt-get update
apt-get install -y python3.11 build-essential wget
wget https://bootstrap.pypa.io/get-pip.py
python3.11 get-pip.py
```

* Install wxPython dependencies and wagon

```bash
# Install wxPython dependencies
apt-get install -y libgtk-3-dev

# Install wagon
pip3 install wagon[dist]  # or: python3.x -m pip install wagon[dist]
```

* Compile wagon

```bash
# Compile wagon
cd /usr/src  # shared folder with Docker host
wagon create wxPython==4.1.1  # use version from pyproject.toml
```

* Upload the .wgn file as a release artifact to a release tag on GitHub,
  such as the [v1.4.0b tag](https://github.com/davidfstr/Crystal-Web-Archiver/releases/tag/v1.4.0b)

* Copy the URL for that .wgn to push-github-action.yml, replacing the old .wgn

* Push up your commits on a new branch to GitHub, so that a Linux
  Continuous Integration job does start.

* Ensure the job completes successfully. In particular ensure that the
  "Install dependency wxPython from wagon" step does successfully install
  and the "Install remaining dependencies with Poetry" step does not timeout.
