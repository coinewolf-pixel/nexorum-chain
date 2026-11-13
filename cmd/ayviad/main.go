package main

import (
	"fmt"
	"os"

	clientv2helpers "cosmossdk.io/client/v2/helpers"

	svrcmd "github.com/cosmos/cosmos-sdk/server/cmd"
	sdk "github.com/cosmos/cosmos-sdk/types"

	app "github.com/coinewolf-pixel/ayvia/app"
	"github.com/coinewolf-pixel/ayvia/cmd/ayviad/cmd"
)

// Address prefixes of the AYVIA network: ayv1..., ayvvaloper1..., ayvvalcons1...
const (
	Bech32PrefixAccAddr  = "ayv"
	Bech32PrefixAccPub   = "ayvpub"
	Bech32PrefixValAddr  = "ayvvaloper"
	Bech32PrefixValPub   = "ayvvaloperpub"
	Bech32PrefixConsAddr = "ayvvalcons"
	Bech32PrefixConsPub  = "ayvvalconspub"
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
