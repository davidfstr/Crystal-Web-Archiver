Obtain a copy of the "vcruntime140" DLLs by:

1. Downloading `vc_redist.x86.exe` from Microsoft Visual C++ 2015 Redistributable [1] and installing it.

2. Run the installer in the Command Prompt with the /install and /log switches to run the installer and output log files.

3. Look in the log file named with a suffix similar to:
       log_000_vcRuntimeMinimum_x86.txt
   for lines containing fragments like:
       KeyPath=C:\WINDOWS\SysWOW64\vcruntime140.dll
   Copy all of these referenced files inside the "vcruntime140" directory
   beside this text file.

[1]: https://docs.microsoft.com/en-US/cpp/windows/latest-supported-vc-redist?view=msvc-170
