# Parallel Test Runner

This directory contains scripts for running Crystal's end-to-end tests in parallel.

## run_tests_in_parallel.py

A script that runs Crystal tests in parallel across 2 subprocesses, streaming output in real-time.

### Usage

Run all tests in parallel:
```bash
python run_tests_in_parallel.py
```

Run specific test modules or functions in parallel:
```bash
python run_tests_in_parallel.py crystal.tests.test_about_box crystal.tests.test_bulkheads
```

Run with help:
```bash
python run_tests_in_parallel.py --help
```

### Output Format

The script outputs results in the same format as `crystal --test`, including:
- Individual test results streamed as they complete (not sorted)
- Status for each test (OK, SKIP, FAILURE, ERROR)
- Summary with character representation (. for pass, s/c for skip, F for failure, E for error)
- Total runtime and pass/fail counts
- Command to rerun failed tests

### How It Works

1. Discovers all tests (or uses provided test names)
2. Splits tests into 2 groups using round-robin distribution
3. Launches 2 `crystal --test` subprocesses in parallel
4. Streams output from both subprocesses in real-time
5. Displays each test result immediately as it completes
6. Formats and displays final summary matching `crystal --test` format

### Current Limitations

- Fixed at 2 workers (not configurable)
- Simple round-robin test distribution (doesn't account for test duration)
- No fault tolerance for subprocess crashes
- Tests are assigned to workers up-front (no dynamic redistribution)

### Future Enhancements

See the plan in `parallel_tests.md` for planned improvements:
- Dynamic test assignment for better load balancing
- Fault tolerance for subprocess crashes
- Configurable number of workers
