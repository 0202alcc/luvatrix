#!/usr/bin/env python3
import re

with open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'rb') as f:
    raw = f.read()

# Simple approach: replace SIGN_IDENTITY="-" with the echo statement
# This will work for both occurrences

old = b'SIGN_IDENTITY=\\"-\\"'
new = b'echo "Signing skipped: no valid CODE_SIGN_IDENTITY provided"'

print(f'Searching for: {old}')
print(f'Replacing with: {new}')

if old in raw:
    print(f'Found {raw.count(old)} occurrence(s)')
    raw = raw.replace(old, new)
    print('Replaced!')
    
    with open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'wb') as f:
        f.write(raw)
    
    print('File written!')
else:
    print('NOT found')
