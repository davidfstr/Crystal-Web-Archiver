# How to make the wxPython wagon

It is important to precompile wxPython for Linux Continuous Integration jobs
because it otherwise takes about 40 minutes to compile wxPython from source.

To compile a new wagon containing wxPython:

* Start a Linux container

```bash
docker run -it --rm -v $(pwd):/usr/src ubuntu:latest
```

* Install Python 3.8, wxPython dependencies, and wagon

```bash
# Install Python 3.8 (from source)
apt update
apt install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libsqlite3-dev libreadline-dev libffi-dev curl libbz2-dev
curl -O https://www.python.org/ftp/python/3.8.2/Python-3.8.2.tar.xz
tar -xf Python-3.8.2.tar.xz
cd Python-3.8.2
./configure
make -j
make install  # maybe use "altinstall" instead? (to avoid override of system Python)
python3.8 --version

# Install wxPython dependencies
apt-get install -y libgtk-3-dev

# Install wagon
pip3.8 install wagon[dist]
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
