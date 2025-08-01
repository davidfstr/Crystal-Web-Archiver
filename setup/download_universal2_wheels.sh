#!/bin/bash
# Downloads universal2 and pure Python wheels for all dependencies to .uwheels
# 
# Input environment variables:
# - $NUM_WORKERS -- (optional) number of parallel workers to use (default: CPU count)

# Create/clean output directories
mkdir -p .uwheels
rm -rf .uwheels/*
mkdir .uwheels/forge

# Convert poetry.lock to requirements-local.txt
poetry export --format requirements.txt --all-groups --without-hashes > requirements.txt
cat requirements.txt | python setup/localize_requirements.py > requirements-local.txt

export BEST_UNIVERSAL2_PLATFORM=$(python -c "import packaging.tags; print([t.platform for t in packaging.tags.sys_tags() if 'universal2' in t.platform][0])")
export BEST_X86_64_PLATFORM=$(echo "$BEST_UNIVERSAL2_PLATFORM" | sed 's/universal2/x86_64/')
export BEST_ARM64_PLATFORM=$(echo "$BEST_UNIVERSAL2_PLATFORM" | sed 's/universal2/arm64/')

# Determine the number of parallel workers (default to number of CPU cores)
NUM_WORKERS=${NUM_WORKERS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)}

# For each requirement, download the best universal2 or pure Python wheel in parallel
echo "Downloading $(echo $(wc -l < requirements-local.txt)) requirements using $NUM_WORKERS parallel workers..."
# NOTE: Use `tail -r` rather than `cat` to process requirements in reverse order,
#       because the wxPython wheel (which is close to the end of the list)
#       takes a long time to download and is useful to process early
tail -r requirements-local.txt | xargs -n 1 -P "$NUM_WORKERS" ./setup/download_universal2_wheels-worker.sh
if [ $? -ne 0 ]; then
    echo "*** One or more workers failed. Aborting."
    exit 1
fi

# Clean up
rm -rf .uwheels/forge
rm requirements.txt requirements-local.txt
