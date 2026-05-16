#!/usr/bin/env python3

with open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'rb') as f:
    raw = f.read()

# The exact pattern from position 14220
old = b'\n        SIGN_IDENTITY=\\"-\\"\\n      fi\\n      /usr/bin/codesign'
new = b'\n        echo "Signing skipped: no valid CODE_SIGN_IDENTITY provided"\\n        exit 0\\n      fi\\n      /usr/bin/codesign'

print(f'Old pattern: {old}')
print(f'New pattern: {new}')

if old in raw:
    print('Found!')
    raw = raw.replace(old, new)
    print('Replaced!')
    with open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'wb') as f:
        f.write(raw)
else:
    print('NOT found')
    # Debug: try to find it
    for i in range(len(raw) - 100):
        if b'SIGN_IDENTITY="-"' in raw[i:i+100]:
            print(f'Found at position {i}')
