// Shared transaction options for Amoy.
//
// Amoy enforces a MINIMUM priority fee (gas tip) of 25 gwei at times, but
// MetaMask/ethers sometimes auto-estimate below it -> "transaction gas price
// below minimum" (which MetaMask unhelpfully shows as "could not coalesce
// error"). We set the fees explicitly with comfortable headroom so writes
// go through consistently.

import { parseUnits } from "ethers";

// Build tx options: explicit gas fees + an estimated gas limit (with headroom).
export async function amoyTxOpts(contractFn, ...args) {
  const opts = {
    // priority fee (tip) — well above Amoy's minimum of 25 gwei
    maxPriorityFeePerGas: parseUnits("30", "gwei"),
    // max total fee per gas — tip + base fee cushion
    maxFeePerGas: parseUnits("50", "gwei"),
  };

  // estimate gas limit so a revert surfaces its real reason, and add headroom
  try {
    const est = await contractFn.estimateGas(...args);
    opts.gasLimit = (est * 12n) / 10n;
  } catch (e) {
    // rethrow with the real revert reason instead of a vague error
    throw new Error(e.reason || e.shortMessage || e.message || "gas estimate failed");
  }
  return opts;
}
