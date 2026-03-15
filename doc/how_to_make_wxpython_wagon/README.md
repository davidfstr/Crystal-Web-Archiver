# wxPython Wagon Build Scripts

This directory contains Scripts to build a wxPython .wgn for Linux, 
given a version of wxPython, a Python version, and a build architecture.

See <how_to_make_wxpython_wagon.md> to understand how these scripts work.

## Examples

Assuming `uname -m` reports `arm64` for your local machine...

Build {wxPython 4.2.5, Python 3.13, x86_64}:

```
$ export DOCKER_DEFAULT_PLATFORM=linux/amd64  # create x86_64 wheel
$ docker run -it --name=build_py313_wgn -v $(pwd):/usr/src ubuntu:22.04
$$ cd /usr/src
$$ bash doc/how_to_make_wxpython_wagon/build_wagon_wx425_py313.sh
... (30-90 minutes)
Wagon created successfully at: ./wxPython-4.2.5-py313-none-linux_x86_64.wgn
$$ exit
$ ls *.wgn
wxPython-4.2.5-py314-none-linux_x86_64.wgn
$ docker rm build_py313_wgn
build_py313_wgn
```

Build {wxPython 4.2.5, Python 3.13, aarch64}:

```
$ export DOCKER_DEFAULT_PLATFORM=linux/arm64  # create aarch64 wheel
$ docker run -it --name=build_py313_wgn -v $(pwd):/usr/src ubuntu:22.04
$$ cd /usr/src
$$ bash doc/how_to_make_wxpython_wagon/build_wagon_wx425_py313.sh
... (30-90 minutes)
Wagon created successfully at: ./wxPython-4.2.5-py313-none-linux_aarch64.wgn
$$ exit
$ ls *.wgn
wxPython-4.2.5-py314-none-linux_aarch64.wgn
$ docker rm build_py313_wgn
build_py313_wgn
```

For other versions of wxPython or Python, use different .sh scripts from
this directory. At the time of writing scripts available include:
- build_wagon_wx425_py313.sh
- build_wagon_wx425_py314.sh
