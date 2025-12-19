import re
import logging

# Current Regex in google.py
# r'(data:image/[^;]+;base64,[a-zA-Z0-9+/=]+)'
OLD_REGEX = re.compile(r'(data:image/[^;]+;base64,[a-zA-Z0-9+/=]+)')

# Proposed Regex
# Match until ", ), space, or >
NEW_REGEX = re.compile(r'(data:image/[^;]+;base64,[^"\)\s\>]+)')

def test_leak(regex, name):
    print(f"Testing {name}...")

    # Case 1: Standard Base64 (Clean)
    payload_clean = "Prefix data:image/png;base64,ABCDEF123456+/= Suffix"
    parts = regex.split(payload_clean)
    # Expected: ['Prefix ', 'data:...', ' Suffix']
    print(f"  Clean Case: {parts}")
    if len(parts) > 1 and parts[1].startswith("data:"):
        print("    -> Captured")
    else:
        print("    -> FAILED capture")

    # Case 2: Base64 with newline (Invalid for standard, but maybe happens?)
    # If regex expects [a-zA-Z0-9...], \n breaks it.
    payload_newline = "Prefix data:image/png;base64,ABCDEF\n123456 Suffix"
    parts = regex.split(payload_newline)
    print(f"  Newline Case: {parts}")
    # Old regex: Matches 'data:...ABCDEF'. Remainder '\n123456 Suffix' is text. -> LEAK!

    # Case 3: URL Safe Base64 (uses - and _)
    payload_urlsafe = "Prefix data:image/png;base64,ABC-DEF_123 Suffix"
    parts = regex.split(payload_urlsafe)
    print(f"  URLSafe Case: {parts}")
    # Old regex: Matches 'data:...ABC'. Remainder '-DEF_123 Suffix' is text. -> LEAK!

    # Case 4: Markdown context
    payload_md = "![alt](data:image/png;base64,ABCDEF123)"
    parts = regex.split(payload_md)
    print(f"  Markdown Case: {parts}")

if __name__ == "__main__":
    print("--- OLD REGEX ---")
    test_leak(OLD_REGEX, "OLD")
    print("\n--- NEW REGEX ---")
    test_leak(NEW_REGEX, "NEW")
