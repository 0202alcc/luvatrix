#!/usr/bin/env python3

content = open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'r').read()
lines = content.split('\n')
result = []

build_data = [
    ('6E4538410401CB52256AA3B1', '"$(BUILT_PRODUCTS_DIR)/$(PRODUCT_NAME).app"'),
    ('201FA979A1DBCE322493E721', '"$(BUILT_PRODUCTS_DIR)/$(PRODUCT_NAME).app/PyPackages"'),
    ('68D2DB353F2579E838C192BA', '"$(BUILT_PRODUCTS_DIR)/$(PRODUCT_NAME).app/python"'),
    ('9CF7EEB2C174760D1EA38506', '"$(BUILT_PRODUCTS_DIR)/$(PRODUCT_NAME).app/Frameworks"'),
]

for build_id, path_value in build_data:
    phase_start = None
    for idx, line in enumerate(lines):
        if build_id in line and '= {' in line:
            phase_start = idx
            break

    if phase_start is None:
        result.extend(lines)
        continue

    phase_block = []
    brace_count = 0
    for idx in range(phase_start, len(lines)):
        line = lines[idx]
        phase_block.append(line)
        brace_count += line.count('{') - line.count('}')
        if brace_count == 0:
            break

    modified = False
    for idx, line in enumerate(phase_block):
        if 'outputFileListPaths = (' in line:
            if idx + 1 < len(phase_block) and phase_block[idx + 1].strip() == ');':
                phase_block.insert(idx + 2, '\t\t\toutputPaths = (')
                phase_block.insert(idx + 3, '\t\t\t  ' + path_value + ',')
                phase_block.insert(idx + 4, '\t\t\t);')
                modified = True
            break

    result.extend(phase_block)

result.extend(lines)
content = '\n'.join(result)
open('/Users/aleccandidato/Projects/luvatrix/ios/Luvatrix.xcodeproj/project.pbxproj', 'w').write(content)
