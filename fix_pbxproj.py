#!/usr/bin/env python3
import re

with open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'rb') as f:
    raw = f.read()

# Find SIGN_IDENTITY=\"-\"
idx = raw.find(b'SIGN_IDENTITY=\\"-\\"')
print(f"Found SIGN_IDENTITY at byte offset: {idx}")
if idx >= 0:
    ctx = raw[max(0, idx-50):idx+30]
    print(f"Context: {ctx}")

# Get the full pattern around it
# Looking for: ...then\\n  SIGN_IDENTITY="-"\\nfi\nPY_ROOT
search_start = max(0, idx - 100)
search_end = min(len(raw), idx + 20)
search_area = raw[search_start:search_end]
print(f"Search area: {search_area}")

# Now let's try a different approach - use the actual substring
# Find where the pattern starts
pattern_start = search_area.find(b'\\nif [ -z')
if pattern_start >= 0:
    pattern = search_area[pattern_start:pattern_start+100]
    print(f"\nPattern to replace: {pattern}")
    
    # New pattern
    new_pattern = b'\\nif [ -z "$SIGN_IDENTITY" ]; then\\n  echo "Signing skipped: no valid CODE_SIGN_IDENTITY provided"\\n  exit 0\\nfi\\n'
    print(f"New pattern: {new_pattern}")
    
    # Now do the replacement in raw
    if pattern in raw:
        print("Found pattern in raw!")
        raw = raw.replace(pattern, new_pattern)
        print("Replaced!")
    else:
        print(f"Pattern not found in raw. Searching...")
        # Try to find the exact bytes
        for i in range(len(raw) - 100):
            if raw[i:i+10] == b'\\nif [ -z':
                print(f"Found at position {i}")
                print(f"Context: {raw[i:i+100]}")
