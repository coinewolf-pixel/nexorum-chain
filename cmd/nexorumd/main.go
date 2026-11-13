package main

import (
	"fmt"
	"os"

	clientv2helpers "cosmossdk.io/client/v2/helpers"

	svrcmd "github.com/cosmos/cosmos-sdk/server/cmd"
	sdk "github.com/cosmos/cosmos-sdk/types"

	app "github.com/coinewolf-pixel/nexorum/app"
	"github.com/coinewolf-pixel/nexorum/cmd/nexorumd/cmd"
)

// Address prefixes of the NEXORUM network: nexo1..., nexovaloper1..., nexovalcons1...
const (
	Bech32PrefixAccAddr  = "nexo"
	Bech32PrefixAccPub   = "nexopub"
	Bech32PrefixValAddr  = "nexovaloper"
	Bech32PrefixValPub   = "nexovaloperpub"
	Bech32PrefixConsAddr = "nexovalcons"
	Bech32PrefixConsPub  = "nexovalconspub"
)

func main() {
	config := sdk.GetConfig()
	config.SetBech32PrefixForAccount(Bech32PrefixAccAddr, Bech32PrefixAccPub)
	config.SetBech32PrefixForValidator(Bech32PrefixValAddr, Bech32PrefixValPub)
	config.SetBech32PrefixForConsensusNode(Bech32PrefixConsAddr, Bech32PrefixConsPub)
	config.Seal()

	rootCmd := cmd.NewRootCmd()
	if err := svrcmd.Execute(rootCmd, clientv2helpers.EnvPrefix, app.DefaultNodeHome); err != nil {
		fmt.Fprintln(rootCmd.OutOrStderr(), err)
		os.Exit(1)
	}
}
