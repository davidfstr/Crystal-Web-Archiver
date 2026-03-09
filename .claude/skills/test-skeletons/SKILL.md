---
name: test-skeletons
description: >
  Work with test skeletons: transcribe test names from a design document into
  code stubs, add a test skeleton to a design document, or draft a new design
  document that includes a test skeleton. Use when the user mentions "test
  skeleton", "test stubs", "transcribe tests", or when a task involves creating
  placeholder tests from a plan.
---

# Test Skeletons

A **test skeleton** is a series of *test stubs* — tests whose names specify
behavior but whose bodies are not yet implemented. Test skeletons appear in
two places:

1. **In code** — functions decorated with `@skip('not yet automated')`, or
   subtests containing `raise SkipTest('not yet automated')`.
2. **In a design document** — a markdown outline listing test names grouped
   under section headings.

## Key Concepts

### Test names are specifications

Test names are full **sentences**, frequently in **given-when-then** format.
They *specify* how the feature should work; failures usually indicate an
improper change in product behavior.

Less commonly a test name may *characterise* current behavior without
requiring it to stay the same (recognised by qualifiers like "currently does X"
or "but may change in the future"). These act as change detectors.

Because names are descriptive, **docstrings are usually unnecessary** on test
functions — they would duplicate the name.

### Skip annotations

| Pattern | Meaning |
|---------|---------|
| `@skip('not yet automated')` | Stub awaiting implementation. |
| `@skip('covered by: test_other_test_name')` | Deliberately not implemented; the named test already covers this scenario. |
| `@skip('fails: not yet implemented')` | The *product* code for this case is not implemented yet. |
| `raise SkipTest('not yet automated')` | Same as `@skip(...)` but used inside a `with subtests.test(...):` block. |

### Subtests and layers

Many tests use `@awith_subtests` to run multiple variants. A common dimension
is **layer**:

```python
@awith_subtests
async def test_example(subtests: SubtestsContext) -> None:
    with subtests.test(layer='model'):
        # Tests the behavior by directly instantiating model objects
        ...

    with subtests.test(layer='cli'):
        # Tests the behavior by launching Crystal via the CLI
        ...

    with subtests.test(layer='ui'):
        # Tests the behavior through the wxPython UI
        raise SkipTest('not yet automated')
```

Other subtest dimensions (e.g. `major_version=`, `case=`) can be nested inside
a layer.

When a layer subtest is just a placeholder with no implementation planned, use
a comment instead of `raise SkipTest`:

```python
with subtests.test(layer='ui'):
    # (Not possible to do X from the UI)
    pass
```

---

## Operations

### 1. Transcribe a test skeleton from a design document into code

Given a design document that lists test names under section headings, produce
corresponding test stubs in the target test file.

**Procedure:**

1. Read the design document section that lists the tests.
2. Read the target test file to understand the existing structure: imports,
   section comments, helper utilities, and the conventions already in use.
3. For each test in the design document:
   - If the test **already exists** in the code, check whether it needs a new
     subtest (e.g. a `layer='ui'` subtest added to an existing test that only
     has `layer='model'`).
   - If the test is **new**, create a stub function:
     - `async def test_<name>() -> None:` with `@skip('not yet automated')`
       (or the appropriate skip annotation from the design document).
     - If the design document includes notes or bullet points under a test
       name, transcribe them as comments inside the function body.
   - If an existing test needs to be **wrapped in subtests** (e.g. wrapping
     its original body in `layer='model'` and adding `layer='ui'`):
     - Add `@awith_subtests` decorator.
     - Add `subtests: SubtestsContext` parameter.
     - Indent the original body inside `with subtests.test(layer='model'):`.
     - Add the new layer subtest after it.
     - Preserve all existing indentation and blank-line conventions.
4. Verify the file compiles: `python -m py_compile <file>`.

**Indentation rule:** when wrapping existing code inside a new `with` block,
increase indentation of every line in the wrapped block by 4 spaces. Do this
carefully for multi-line `with` statements and continuation lines.

### 2. Add a test skeleton to an existing design document

When extending a design document with new tests:

1. Read the existing document to understand its structure and grouping.
2. Place new tests under the appropriate `# === Test: ... ===` section, or
   create a new section if none fits.
3. Use the same bullet/indentation style as the rest of the document.
4. Each test entry is a bullet with the full function name in backticks,
   optionally followed by sub-bullets with notes:

```markdown
- `test_given_X_when_Y_then_Z`
  - Note about what this test verifies
  - `@skip('covered by: test_other')`
```

### 3. Draft a design document that includes a test skeleton

When drafting a new design document (or a "Step N: Tests" section):

1. **Group tests by theme** using section headings that match the code's
   `# === Test: ... ===` comment style:
   ```markdown
   - `# === Test: Happy Path Cases ===`
   - `# === Test: Error Cases ===`
   - `# === Test: Edge Cases ===`
   ```
2. **Name each test as a full sentence** in given-when-then format where
   appropriate.
3. **Note layer coverage**: indicate which tests need `layer='model'`,
   `layer='cli'`, and/or `layer='ui'` subtests, especially when extending
   existing model-layer tests with UI coverage.
4. **Mark skip relationships**: if a test is covered by another, note it:
   ```markdown
   - `test_given_dialog_and_no_creds_when_press_open_then_shows_error`
     - `@skip('covered by: test_when_open_with_no_creds_then_raises_PermissionError')`
   ```
5. **Include implementation notes** as sub-bullets under test names where
   the test requires non-obvious setup or assertions.
