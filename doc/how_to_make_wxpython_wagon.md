# How to make the wxPython wagon

It is important to precompile wxPython for Linux Continuous Integration jobs
because it otherwise takes about 40 minutes to compile wxPython from source.

To compile a new wagon containing wxPython:

* Start a Linux container

```bash
export DOCKER_DEFAULT_PLATFORM=linux/amd64  # create x86_64 wheel
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
time ./configure
    # real  0m29.421s
time make -j4
    # real  1m16.073s
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
time ./configure
    # real  0m28.451s
time make -j4  # NOTE: -j seems to crash Docker
    # real  1m11.544s
make install
python3.9 --version
```

* Install Python 3.10, if appropriate for this .wgn

TODO: Add instructions, probably based on the Python 3.11 instructions below

* Install Python 3.11, if appropriate for this .wgn

```bash
# Install Python 3.11 and pip
apt-get update
apt-get install -y python3.11 python3.11-dev build-essential wget
wget https://bootstrap.pypa.io/get-pip.py
python3.11 get-pip.py
```

* Install Python 3.12, if appropriate for this .wgn

```bash
# Install Python 3.12 (from source)
apt-get update
apt-get install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libsqlite3-dev libreadline-dev libffi-dev curl libbz2-dev wget
curl -O https://www.python.org/ftp/python/3.12.9/Python-3.12.9.tar.xz
tar -xf Python-3.12.9.tar.xz
cd Python-3.12.9
time ./configure
    # real  0m28.451s
time make -j4
    # real  1m11.544s
make install
python3.12 --version
# Install pip for Python 3.12
wget https://bootstrap.pypa.io/get-pip.py
python3.12 get-pip.py
```

* Install Python 3.13, if appropriate for this .wgn

```bash
# Install Python 3.13.5 (from source)
apt-get update
apt-get install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libsqlite3-dev libreadline-dev libffi-dev curl libbz2-dev wget
curl -O https://www.python.org/ftp/python/3.13.5/Python-3.13.5.tar.xz
tar -xf Python-3.13.5.tar.xz
cd Python-3.13.5
time ./configure
    # real  9m55.020s
time make -j4
    # real  13m31.239s
./python --version
# Install pip for Python 3.13
wget https://bootstrap.pypa.io/get-pip.py
./python get-pip.py
```

* Install wxPython dependencies and wagon

```bash
# Install wxPython dependencies
time apt-get install -y libgtk-3-dev

# Upgrade pip
python3 -m pip install --upgrade pip  # or: python3.x -m pip install --upgrade pip

# Install wagon
python3 -m pip install wagon[dist]  # or: python3.x -m pip install wagon[dist]
```

* Compile wagon

```bash
# Compile wagon
cd /usr/src  # shared folder with Docker host
time wagon create wxPython==4.2.3  # use version from pyproject.toml
    # real  81m6.382s (Python 3.9)
    # real  ~80m+ (Python 3.12.9)
    # real  ~80m+ (Python 3.13.5)
```

If using a locally built Python from source:

```bash
time ./python -m wagon create wxPython==4.2.3  # use version from pyproject.toml
```

* Upload the .wgn file as a release artifact to a release tag on GitHub,
  such as the [v1.4.0b tag](https://github.com/davidfstr/Crystal-Web-Archiver/releases/tag/v1.4.0b)

* Copy the URL for that .wgn to ci.yaml, replacing the old .wgn

* Push up your commits on a new branch to GitHub, so that a Linux
  Continuous Integration job does start.

* Ensure the job completes successfully. In particular ensure that the
  "Install dependency wxPython from wagon" step does successfully install
  and the "Install remaining dependencies with Poetry" step does not timeout.
