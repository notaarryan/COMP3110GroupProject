# LHDiff interface contract

The data every stage passes along and the signatures we agreed on. These are
final unless we agree to change them here first.

## Who owns what

- `preprocess.py` (P1, Ujwal): normalizes lines, runs diff, builds the left
  and right lists, and provides `get_context`.
- `similarity.py` (P2, Tobi): Levenshtein, cosine and the combined score.
- `simhash.py` (P3, Aryan): SimHash fingerprints, Hamming distance and the
  top-k candidate sets.
- `resolve.py` (P4, Nand): re-scores candidates, picks the best match and
  resolves conflicts.
- `split.py` (P5, Nifemi): line-split detection.
- `lhdiff.py` (P5, Nifemi): the CLI. It runs every stage and prints
  `old-new` pairs.

Each stage takes the previous stage's mapping and returns a new one. Nobody
mutates `old`, `new` or `result.mapping`.

## Conventions

- Line indices are 0-indexed everywhere in code. They become 1-indexed only
  when printed, and only `lhdiff.py` does that conversion.
- A mapping is a `dict[int, list[int]]` from an old index to new indices.
  The values are lists so a line split can be recorded as
  `{39: [19, 20, 21]}`. After stage 1 every list has exactly one element.
- An old line missing from the mapping was deleted. A new index that appears
  in no mapping value was added.
- A line's context is the 4 lines above it and the 4 below, not counting the
  line itself.
- The combined score is `0.6 * content + 0.4 * context`. Tobi owns this.
- Candidate sets hold k = 15 lines. Aryan owns this.

## Stage 1 data

```python
@dataclass
class FileVersion:
    path: str
    original: list[str]     # lines as written, newlines stripped
    normalized: list[str]   # same length, same indices

@dataclass
class DiffResult:
    old: FileVersion
    new: FileVersion
    mapping: dict[int, list[int]]   # old index -> new indices
    left_list: list[int]            # unmatched OLD indices, ascending
    right_list: list[int]           # unmatched NEW indices, ascending
    backend: str                    # "gnu" or "difflib"
```

`DiffResult` also has `old_context(i)` and `new_context(i)`, which call
`get_context` on the right file.

## Functions

```python
# preprocess.py
normalize(line: str) -> str
read_lines(path: str) -> list[str]
preprocess_file(path: str) -> FileVersion
get_context(lines: list[str], index: int, window: int = 4) -> str
detect_unchanged(old, new, backend="auto") -> DiffResult
preprocess(old_path, new_path, backend="auto") -> DiffResult   # entry point

# similarity.py
content_similarity(a: str, b: str) -> float       # normalized Levenshtein, 0..1
context_similarity(a: str, b: str) -> float       # cosine over tokens, 0..1
combined_similarity(content_a, content_b, context_a, context_b) -> float
                                                  # 0.6 * content + 0.4 * context

# simhash.py
candidate_sets(result, k=15) -> dict[int, list[int]]
    # left index -> up to k right indices, ranked by Hamming distance

# resolve.py
DEFAULT_THRESHOLD = 0.45
resolve(result, candidates, threshold=DEFAULT_THRESHOLD) -> dict[int, list[int]]

# split.py
detect_splits(result, mapping) -> dict[int, list[int]]
```

`resolve` and `detect_splits` return a new mapping and leave their inputs
alone. `DEFAULT_THRESHOLD` is a proposal, not an agreed value. Everything
else inside these modules is private and up to its owner.

## Stage 1 decisions

- Lines are lowercased, whitespace runs collapsed to one space, ends
  stripped, and diff runs on these normalized lines.
- Blank lines stay as `""` so indices don't shift.
- `get_context` returns a space-joined string of normalized lines, excludes
  the target line, clamps at file edges and skips blanks.

We use GNU diff because the paper specifies Unix diff and the two disagree on
roughly 2% of unchanged pairs. It falls back to `difflib` when `diff` isn't on
PATH, and `DiffResult.backend` records which ran.

## Worked example (slides 24 to 28)

There is no CLI yet, so run stage 1 on its own. Expected output, 1-indexed:

```
python preprocess.py tests/data/slide24_old.java tests/data/slide24_new.java

mapping     1-1, 2-3, 4-5, 8-9
left_list   3, 5, 6, 7
right_list  2, 4, 6, 7, 8
```

Old lines 7 and 8 both normalize to `}`. GNU diff pairs the closing brace with
the closing brace (`8-9`); `difflib` picks `7-9`, which later becomes a crossing.

## Open questions for the group

1. What is the threshold? The deck only says "a predefined threshold". Nand
   owns tuning it in Phase 2, but P4 needs a starting value in Phase 1. I
   propose 0.45 and revisiting it with real data.
2. Who writes mapping entries? P4 writes matches and P5 writes splits, so
   both touch the same mapping. The current signatures assume P4 and P5 each
   return a new dict instead of mutating, so a bug in one stage can't
   silently corrupt the other. Confirm this.
3. Is normalization too aggressive? Collapsing whitespace keeps `a+b` and
   `a + b` different but makes `a  +  b` and `a + b` identical. That's fine
   for tracking, but it's worth a sentence in the report.
