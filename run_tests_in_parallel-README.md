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
2. Creates a work queue with all tests
3. Launches 2 `crystal test --interactive` subprocesses in parallel
4. Each worker pulls tests from the queue on-demand as it becomes available
5. Streams output from both subprocesses in real-time
6. Displays each test result immediately as it completes
7. Formats and displays final summary matching `crystal --test` format

### Features

- **Dynamic test assignment**: Tests are assigned to workers on-demand, ensuring balanced load distribution even when test durations vary significantly
- **Real-time output streaming**: See test results as they complete
- **Consistent formatting**: Output matches `crystal --test` format exactly

### Current Limitations

- Fixed at 2 workers (not configurable)
- No fault tolerance for subprocess crashes

### Future Enhancements

See the plan in `parallel_tests.md` for planned improvements:
- Fault tolerance for subprocess crashes
- Configurable number of workers
