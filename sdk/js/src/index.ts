/**
 * @nexorum/sdk — work with the NEXORUM blockchain from JavaScript / TypeScript.
 *
 * Built on CosmJS. Works in Node.js and in the browser.
 *
 *   import { NEXORUM_TESTNET, createWallet, connect, toNexo } from "@nexorum/sdk";
 *   const { mnemonic, address } = await createWallet();
 *   const client = await connect({ mnemonic });
 *   console.log(toNexo(await client.balance(address)));
 */
import {
  DirectSecp256k1HdWallet,
  DirectSecp256k1Wallet,
  type OfflineSigner,
} from "@cosmjs/proto-signing";
import {
  GasPrice,
  QueryClient,
  SigningStargateClient,
  StargateClient,
  setupDistributionExtension,
  setupStakingExtension,
  type DeliverTxResponse,
  type DistributionExtension,
  type StakingExtension,
} from "@cosmjs/stargate";
import { connectComet, type CometClient } from "@cosmjs/tendermint-rpc";

// ------------------------------------------------------------------ network config

export interface NexorumNetwork {
  chainId: string;
  chainName: string;
  rpc: string;
  rest: string;
  /** bech32 prefix of account addresses: nexo1... */
  prefix: string;
  /** base denomination on chain */
  denom: string;
  /** display symbol */
  symbol: string;
  /** 1 NEXO = 10^decimals unexo */
  decimals: number;
  /** minimum gas price accepted by validators, in denom */
  gasPrice: number;
  /** BIP44 coin type used for key derivation (118 = standard Cosmos) */
  coinType: number;
}

export const NEXORUM_TESTNET: NexorumNetwork = {
  chainId: "nexorum-testnet-1",
  chainName: "NEXORUM Testnet",
  rpc: "http://127.0.0.1:26657",
  rest: "http://127.0.0.1:1317",
  prefix: "nexo",
  denom: "unexo",
  symbol: "NEXO",
  decimals: 6,
  gasPrice: 0.0025,
  coinType: 118,
};

/** Same network with your own public endpoints, e.g. withEndpoints("https://rpc.example", "https://api.example"). */
export function withEndpoints(rpc: string, rest: string, net: NexorumNetwork = NEXORUM_TESTNET): NexorumNetwork {
  return { ...net, rpc: rpc.replace(/\/$/, ""), rest: rest.replace(/\/$/, "") };
}

// ------------------------------------------------------------------ amounts

/** "12.5" NEXO -> "12500000" unexo (string, exact, no floating point). */
export function fromNexo(nexo: string | number, net: NexorumNetwork = NEXORUM_TESTNET): string {
  const s = String(nexo).trim();
  if (!/^\d+(\.\d+)?$/.test(s)) throw new Error(`Invalid amount: ${s}`);
  const [whole, frac = ""] = s.split(".");
  if (frac.length > net.decimals) throw new Error(`Too many decimals (max ${net.decimals}): ${s}`);
  const units = BigInt(whole) * 10n ** BigInt(net.decimals) + BigInt(frac.padEnd(net.decimals, "0") || "0");
  return units.toString();
}

/** "12500000" unexo -> "12.5" NEXO (string, exact). */
export function toNexo(units: string | number | bigint, net: NexorumNetwork = NEXORUM_TESTNET): string {
  const v = BigInt(units);
  const neg = v < 0n;
  const abs = neg ? -v : v;
  const base = 10n ** BigInt(net.decimals);
  const whole = abs / base;
  const frac = (abs % base).toString().padStart(net.decimals, "0").replace(/0+$/, "");
  return (neg ? "-" : "") + whole.toString() + (frac ? "." + frac : "");
}

/** True if the string is a valid-looking NEXORUM account address. */
export function isAddress(address: string, net: NexorumNetwork = NEXORUM_TESTNET): boolean {
  return new RegExp(`^${net.prefix}1[02-9ac-hj-np-z]{38,58}$`).test(address);
}

// ------------------------------------------------------------------ wallets

export interface NewWallet {
  /** 24-word recovery phrase. Show it to the user once; never send it to a server. */
  mnemonic: string;
  address: string;
}

/** Create a new wallet locally (keys never leave this process / browser). */
export async function createWallet(net: NexorumNetwork = NEXORUM_TESTNET): Promise<NewWallet> {
  const w = await DirectSecp256k1HdWallet.generate(24, { prefix: net.prefix });
  const [acc] = await w.getAccounts();
  return { mnemonic: w.mnemonic, address: acc.address };
}

/** Signer from a recovery phrase. */
export async function walletFromMnemonic(mnemonic: string, net: NexorumNetwork = NEXORUM_TESTNET): Promise<OfflineSigner> {
  return DirectSecp256k1HdWallet.fromMnemonic(mnemonic.trim(), { prefix: net.prefix });
}

/** Signer from a raw 32-byte private key in hex (e.g. `nexorumd keys export NAME --unarmored-hex --unsafe`). */
export async function walletFromPrivateKey(hex: string, net: NexorumNetwork = NEXORUM_TESTNET): Promise<OfflineSigner> {
  const clean = hex.trim().replace(/^0x/, "");
  if (!/^[0-9a-fA-F]{64}$/.test(clean)) throw new Error("Private key must be 64 hex characters");
  const bytes = Uint8Array.from(clean.match(/../g)!.map((b) => parseInt(b, 16)));
  return DirectSecp256k1Wallet.fromKey(bytes, net.prefix);
}

// ------------------------------------------------------------------ Keplr / Leap

/** Chain description in the format Keplr and Leap expect for experimentalSuggestChain. */
export function keplrChainInfo(net: NexorumNetwork = NEXORUM_TESTNET) {
  const currency = { coinDenom: net.symbol, coinMinimalDenom: net.denom, coinDecimals: net.decimals };
  return {
    chainId: net.chainId,
    chainName: net.chainName,
    rpc: net.rpc,
    rest: net.rest,
    bip44: { coinType: net.coinType },
    bech32Config: {
      bech32PrefixAccAddr: net.prefix,
      bech32PrefixAccPub: `${net.prefix}pub`,
      bech32PrefixValAddr: `${net.prefix}valoper`,
      bech32PrefixValPub: `${net.prefix}valoperpub`,
      bech32PrefixConsAddr: `${net.prefix}valcons`,
      bech32PrefixConsPub: `${net.prefix}valconspub`,
    },
    currencies: [currency],
    feeCurrencies: [{ ...currency, gasPriceStep: { low: net.gasPrice, average: net.gasPrice * 2, high: net.gasPrice * 4 } }],
    stakeCurrency: currency,
  };
}

interface BrowserWallet {
  experimentalSuggestChain(info: unknown): Promise<void>;
  enable(chainId: string): Promise<void>;
  getOfflineSigner(chainId: string): OfflineSigner;
}

/**
 * Browser only: add NEXORUM to Keplr (or Leap) if needed, ask the user to connect,
 * and return a signer. Pass window.keplr or window.leap.
 */
export async function connectBrowserWallet(wallet: BrowserWallet | undefined, net: NexorumNetwork = NEXORUM_TESTNET): Promise<OfflineSigner> {
  if (!wallet) throw new Error("Wallet extension not found (install Keplr or Leap)");
  await wallet.experimentalSuggestChain(keplrChainInfo(net));
  await wallet.enable(net.chainId);
  return wallet.getOfflineSigner(net.chainId);
}

// ------------------------------------------------------------------ client

export interface ValidatorInfo {
  operator: string;
  moniker: string;
  tokens: string;
  status: "bonded" | "unbonding" | "unbonded" | "unspecified";
  jailed: boolean;
  commission: string;
}

const STATUS = ["unspecified", "unbonded", "unbonding", "bonded"] as const;

/** Read-only client: balances, blocks, transactions, validators. */
export class NexorumReader {
  protected constructor(
    readonly net: NexorumNetwork,
    readonly stargate: StargateClient,
    protected readonly query: QueryClient & StakingExtension & DistributionExtension,
    protected readonly comet: CometClient,
  ) {}

  static async connect(net: NexorumNetwork = NEXORUM_TESTNET): Promise<NexorumReader> {
    const comet = await connectComet(net.rpc);
    const stargate = await StargateClient.create(comet);
    return new NexorumReader(net, stargate, QueryClient.withExtensions(comet, setupStakingExtension, setupDistributionExtension), comet);
  }

  /** Balance in base units (unexo) as a string. Use toNexo() for display. */
  async balance(address: string): Promise<string> {
    return (await this.stargate.getBalance(address, this.net.denom)).amount;
  }

  async height(): Promise<number> {
    return this.stargate.getHeight();
  }

  async chainId(): Promise<string> {
    return this.stargate.getChainId();
  }

  async tx(hash: string) {
    return this.stargate.getTx(hash);
  }

  async validators(): Promise<ValidatorInfo[]> {
    const out: ValidatorInfo[] = [];
    for (const status of ["BOND_STATUS_BONDED", "BOND_STATUS_UNBONDING", "BOND_STATUS_UNBONDED"] as const) {
      let key: Uint8Array | undefined;
      do {
        const r = await this.query.staking.validators(status, key);
        for (const v of r.validators) {
          out.push({
            operator: v.operatorAddress,
            moniker: v.description?.moniker ?? "",
            tokens: v.tokens,
            status: ((STATUS as readonly string[])[v.status] ?? "unspecified") as ValidatorInfo["status"],
            jailed: v.jailed,
            // commission rate is an 18-decimal fixed-point integer string
            commission: (Number(v.commission?.commissionRates?.rate ?? "0") / 1e18).toString(),
          });
        }
        key = r.pagination?.nextKey?.length ? r.pagination.nextKey : undefined;
      } while (key);
    }
    return out.sort((a, b) => (BigInt(b.tokens) > BigInt(a.tokens) ? 1 : -1));
  }

  /** Delegations of an address: validator -> amount in unexo. */
  async delegations(address: string): Promise<{ validator: string; amount: string }[]> {
    const r = await this.query.staking.delegatorDelegations(address);
    return r.delegationResponses.map((d) => ({ validator: d.delegation!.validatorAddress, amount: d.balance!.amount }));
  }

  /** Pending staking rewards of an address in unexo (whole units, rounded down). */
  async rewards(address: string): Promise<string> {
    const r = await this.query.distribution.delegationTotalRewards(address);
    const coin = r.total.find((c) => c.denom === this.net.denom);
    // DecCoin amounts are 18-decimal fixed-point strings
    return coin ? (BigInt(coin.amount) / 10n ** 18n).toString() : "0";
  }

  disconnect(): void {
    this.stargate.disconnect();
  }
}

/** Client that can also sign and send transactions. */
export class NexorumClient extends NexorumReader {
  private constructor(
    net: NexorumNetwork,
    stargate: StargateClient,
    query: QueryClient & StakingExtension & DistributionExtension,
    comet: CometClient,
    readonly signer: SigningStargateClient,
    readonly address: string,
  ) {
    super(net, stargate, query, comet);
  }

  static async withSigner(signer: OfflineSigner, net: NexorumNetwork = NEXORUM_TESTNET): Promise<NexorumClient> {
    const comet = await connectComet(net.rpc);
    const stargate = await StargateClient.create(comet);
    const signing = await SigningStargateClient.createWithSigner(comet, signer, {
      gasPrice: GasPrice.fromString(`${net.gasPrice}${net.denom}`),
    });
    const [acc] = await signer.getAccounts();
    const q = QueryClient.withExtensions(comet, setupStakingExtension, setupDistributionExtension);
    return new NexorumClient(net, stargate, q, comet, signing, acc.address);
  }

  private check(r: DeliverTxResponse): DeliverTxResponse {
    if (r.code !== 0) throw new Error(`Transaction failed (code ${r.code}): ${r.rawLog ?? ""}`);
    return r;
  }

  /** Send NEXO. `amount` is in NEXO, e.g. "12.5". Fee is calculated automatically. */
  async send(to: string, amount: string | number, memo = ""): Promise<DeliverTxResponse> {
    if (!isAddress(to, this.net)) throw new Error(`Not a ${this.net.prefix} address: ${to}`);
    return this.check(
      await this.signer.sendTokens(this.address, to, [{ denom: this.net.denom, amount: fromNexo(amount, this.net) }], "auto", memo),
    );
  }

  /** Stake NEXO with a validator (operator address nexovaloper1...). */
  async delegate(validator: string, amount: string | number): Promise<DeliverTxResponse> {
    return this.check(
      await this.signer.delegateTokens(this.address, validator, { denom: this.net.denom, amount: fromNexo(amount, this.net) }, "auto"),
    );
  }

  /** Start unstaking (tokens return after the unbonding period). */
  async undelegate(validator: string, amount: string | number): Promise<DeliverTxResponse> {
    return this.check(
      await this.signer.undelegateTokens(this.address, validator, { denom: this.net.denom, amount: fromNexo(amount, this.net) }, "auto"),
    );
  }

  /** Collect staking rewards from a validator. */
  async claimRewards(validator: string): Promise<DeliverTxResponse> {
    return this.check(await this.signer.withdrawRewards(this.address, validator, "auto"));
  }

  disconnect(): void {
    this.signer.disconnect();
    super.disconnect();
  }
}

/**
 * Shortcut: connect with a recovery phrase, a private key or a ready signer.
 *   const c = await connect({ mnemonic: "..." });
 */
export async function connect(
  opts: { mnemonic?: string; privateKey?: string; signer?: OfflineSigner; network?: NexorumNetwork },
): Promise<NexorumClient> {
  const net = opts.network ?? NEXORUM_TESTNET;
  const signer = opts.signer
    ?? (opts.mnemonic ? await walletFromMnemonic(opts.mnemonic, net)
      : opts.privateKey ? await walletFromPrivateKey(opts.privateKey, net)
        : undefined);
  if (!signer) throw new Error("Pass mnemonic, privateKey or signer");
  return NexorumClient.withSigner(signer, net);
}
