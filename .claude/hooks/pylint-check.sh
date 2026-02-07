#!/bin/bash
# Hook script to run pylint after Python file edits and report results

# Read the hook input from stdin
INPUT=$(cat)

# Extract the file path - only process .py files
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE_PATH" ]] || [[ ! "$FILE_PATH" =~ \.py$ ]]; then
  # Not a Python file, skip
  exit 0
fi

# Run pylint and capture output (always succeeds, even if pylint finds issues)
LINT_OUTPUT=$(./venv3.14/bin/pylint "$FILE_PATH" 2>&1 || true)

# Check if pylint found any issues
if [[ -z "$LINT_OUTPUT" ]]; then
  # No output = no issues
  exit 0
fi

# Return the pylint output as JSON with additionalContext for Claude to see
jq -n \
  --arg output "$LINT_OUTPUT" \
  '{
    "hookSpecificOutput": {
      "hookEventName": "PostToolUse",
      "additionalContext": ("Pylint output:\n" + $output)
    }
  }'

exit 0
