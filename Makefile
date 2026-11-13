VERSION ?= 0.1.0-testnet
COMMIT  := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
LDFLAGS := -X github.com/cosmos/cosmos-sdk/version.Name=nexorum \
           -X github.com/cosmos/cosmos-sdk/version.AppName=nexorumd \
           -X github.com/cosmos/cosmos-sdk/version.Version=$(VERSION) \
           -X github.com/cosmos/cosmos-sdk/version.Commit=$(COMMIT)

.PHONY: build install testnet-init testnet-start testnet-stop testnet-status bots monitor clean

build:
	go build -trimpath -ldflags '$(LDFLAGS)' -o build/nexorumd ./cmd/nexorumd

install: build
	sudo install -m 0755 build/nexorumd /usr/local/bin/nexorumd

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
