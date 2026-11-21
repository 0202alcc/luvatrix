# EME probe (SL-30) — builds EMEProbe.app with Xcode CLT only (swiftc).
# No external dependencies; AppKit/WebKit are system frameworks.

APP       := EMEProbe.app
BINARY    := .build/release/eme-probe
BUNDLE_BIN := $(APP)/Contents/MacOS/EMEProbe

.PHONY: build bundle sign run clean

build:
	swift build -c release

bundle: build
	mkdir -p $(APP)/Contents/MacOS
	cp $(BINARY) $(BUNDLE_BIN)
	cp Resources/Info.plist $(APP)/Contents/Info.plist

# Ad-hoc signature is enough for local runs. If every EME call rejects even
# ClearKey, re-sign with a real Apple Development identity (see README).
sign: bundle
	codesign --force --sign - $(APP)

run: sign
	./$(BUNDLE_BIN) $(ARGS)

clean:
	rm -rf .build $(APP) eme-probe-results.json
