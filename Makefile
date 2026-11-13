VERSION ?= 0.1.0-testnet
# Cosmos SDK v0.53 dependencies (bytedance/sonic) do not build with Go 1.26 yet.
# Go downloads and uses this exact, tested toolchain automatically.
export GOTOOLCHAIN ?= go1.24.7
COMMIT  := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
LDFLAGS := -X github.com/cosmos/cosmos-sdk/version.Name=ayvia \
           -X github.com/cosmos/cosmos-sdk/version.AppName=ayviad \
           -X github.com/cosmos/cosmos-sdk/version.Version=$(VERSION) \
           -X github.com/cosmos/cosmos-sdk/version.Commit=$(COMMIT)

.PHONY: build install testnet-init testnet-start testnet-stop testnet-status bots monitor clean

build:
	go build -trimpath -ldflags '$(LDFLAGS)' -o build/ayviad ./cmd/ayviad

install: build
	sudo install -m 0755 build/ayviad /usr/local/bin/ayviad

testnet-init: build
	scripts/testnet.sh init

testnet-start:
	scripts/testnet.sh start

testnet-stop:
	scripts/testnet.sh stop

testnet-status:
	scripts/testnet.sh status

bots:
	python3 scripts/loadbots.py --duration 60 --rate 2

monitor:
	python3 scripts/monitor.py

clean:
	rm -rf build
