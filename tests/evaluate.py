"""
Measure accuracy + speed of the AI module.

    python -m tests.evaluate                    # default model
    python -m tests.evaluate --model qwen3:1.7b # compare another model

Some sentences are answered by the local fast path (no model call) - that is expected.
A list in "expected" means any of the listed values is acceptable.
Add new sentences to tests/test_cases.json whenever the system gets one wrong.
"""
import argparse
import json
import time
from pathlib import Path

from ai import understand_command, warmup

CASES = Path(__file__).with_name("test_cases.json")


def _value_matches(got, value) -> bool:
    """Compare one field. A list of values means 'any of these is acceptable'."""
    if isinstance(value, list):
        return any(_value_matches(got, option) for option in value)
    if isinstance(value, str) and isinstance(got, str):
        return got.strip().lower() == value.strip().lower()
    return got == value


def matches(result: dict, expected: dict) -> bool:
    for key, value in expected.items():          # only compare the fields listed in "expected"
        if not _value_matches(result.get(key), value):
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    print("Loading model (warm-up)...")
    warmup(args.model)

    correct, total_time, failures = 0, 0.0, []
    for case in cases:
        start = time.time()
        try:
            result = understand_command(case["text"], model=args.model)
        except Exception as e:                    # Ollama down / model error -> count as failure, keep going
            failures.append((case["text"], case["expected"], {"action": "unknown", "_error": str(e)}))
            continue
        total_time += time.time() - start
        if matches(result, case["expected"]):
            correct += 1
        else:
            failures.append((case["text"], case["expected"], result))

    print(f"\nModel: {args.model or 'default'}")
    print(f"Accuracy: {correct}/{len(cases)} = {100 * correct / len(cases):.1f}%")
    print(f"Average time per command: {total_time / len(cases):.2f}s")

    if failures:
        print("\nFailures:")
        for text, expected, got in failures:
            print(f"  - {json.dumps(text, ensure_ascii=True)}\n      expected: {json.dumps(expected, ensure_ascii=True)}\n      got:      {json.dumps(got, ensure_ascii=True)}")


if __name__ == "__main__":
    main()
