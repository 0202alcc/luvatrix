#!/usr/bin/env python3
import re

with open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'rb') as f:
    raw = f.read()

# Find the second SIGN_IDENTITY="-" (in Process PyPackages native extensions)
idx = raw.find(b'SIGN_IDENTITY=\\"-\\"')
print(f"Found SIGN_IDENTITY at byte offset: {idx}")
if idx >= 0:
    ctx = raw[max(0, idx-80):idx+40]
    print(f"Context: {ctx}")

# Get the pattern
search_area = raw[max(0, idx - 60):idx + 50]
print(f"Search area: {search_area}")

# The pattern from earlier output:
# if [ -z "$SIGN_IDENTITY" ]; then\n        SIGN_IDENTITY="-"\n      fi\n      /usr/bin
pattern = search_area[search_area.find(b'\n        SIGN_IDENTITY'):search_area.find(b'      /usr/bin')+20]
print(f"\nPattern to replace: {pattern}")

# New pattern
new_pattern = b'\n        echo "Signing skipped: no valid CODE_SIGN_IDENTITY provided"\n        exit 0\n      fi\n      /usr/bin'
print(f"New pattern: {new_pattern}")

# Replace
if pattern in raw:
    print("Found pattern in raw!")
    raw = raw.replace(pattern, new_pattern)
    print("Replaced!")
else:
    print("Pattern not found in raw")
    # Try to find it another way
    for i in range(len(raw) - 60):
        chunk = raw[i:i+60]
        if b'SIGN_IDENTITY="-"' in chunk:
            print(f"Found SIGN_IDENTITY=\"-\" at position {i}")
            print(f"Context: {chunk}")
