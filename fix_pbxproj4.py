#!/usr/bin/env python3
import re

with open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'rb') as f:
    raw = f.read()

# Get exact context around position 14220
idx = 14220
start = max(0, idx - 50)
end = min(len(raw), idx + 70)
ctx = raw[start:end]

print('Context:')
print(repr(ctx))

# Find SIGN_IDENTITY="-" in this context
pos_in_ctx = ctx.find(b'SIGN_IDENTITY=\\"-\\"')
print(f'Position in context: {pos_in_ctx}')

if pos_in_ctx >= 0:
    # Get the pattern ending at the newline after fi
    pattern = ctx[pos_in_ctx:pos_in_ctx+60]
    print(f'Pattern: {repr(pattern)}')
    
    # New pattern - replace SIGN_IDENTITY="-"\\n      fi with echo + exit
    new_pattern = ctx.replace(b'SIGN_IDENTITY=\\"-\\"\\n      fi', b'\n        echo "Signing skipped: no valid CODE_SIGN_IDENTITY provided"\\n        exit 0\\n      fi', 1)
    print(f'New pattern: {repr(new_pattern)}')
    
    # But we need to include the surrounding context properly
    # Let's do it by finding the full block
    
    # Actually simpler: just replace the specific line
    old_block = b'SIGN_IDENTITY=\\"-\\"'
    new_block = b'echo "Signing skipped: no valid CODE_SIGN_IDENTITY provided"'
    
    print(f'\nSimple replacement:')
    print(f'Old: {old_block}')
    print(f'New: {new_block}')
