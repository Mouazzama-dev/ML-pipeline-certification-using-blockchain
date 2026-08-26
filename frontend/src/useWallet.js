import { useState, useEffect, useCallback } from "react";
import { BrowserProvider, Contract } from "ethers";
import { AMOY, CONTRACTS } from "./config";
import { ROLE_MANAGER_ABI, REGISTRY_ABI } from "./abis";

export function useWallet() {
  const [address, setAddress] = useState(null);
  const [provider, setProvider] = useState(null);
  const [chainOk, setChainOk] = useState(false);
  const [error, setError] = useState(null);

  const hasMetaMask = typeof window !== "undefined" && window.ethereum;

  const ensureAmoy = useCallback(async () => {
    try {
      await window.ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: AMOY.chainIdHex }],
      });
      return true;
    } catch (switchErr) {
      if (switchErr.code === 4902) {
        await window.ethereum.request({
          method: "wallet_addEthereumChain",
          params: [{
            chainId: AMOY.chainIdHex,
            chainName: AMOY.chainName,
            rpcUrls: [AMOY.rpcUrl],
            nativeCurrency: AMOY.currency,
            blockExplorerUrls: [AMOY.explorer],
          }],
        });
        return true;
      }
      throw switchErr;
    }
  }, []);

  const connect = useCallback(async () => {
    setError(null);
    if (!hasMetaMask) {
      setError("MetaMask not found. Please install the MetaMask extension.");
      return;
    }
    try {
      const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
      await ensureAmoy();
      const p = new BrowserProvider(window.ethereum);
      setProvider(p);
      setAddress(accounts[0]);
      setChainOk(true);
    } catch (e) {
      setError(e.message || "Failed to connect wallet.");
    }
  }, [hasMetaMask, ensureAmoy]);

  const disconnect = useCallback(() => {
    setAddress(null);
    setProvider(null);
    setChainOk(false);
  }, []);

  useEffect(() => {
    if (!hasMetaMask) return;
    const onAccounts = (accts) => setAddress(accts[0] || null);
    const onChain = () => window.location.reload();
    window.ethereum.on("accountsChanged", onAccounts);
    window.ethereum.on("chainChanged", onChain);
    return () => {
      window.ethereum.removeListener("accountsChanged", onAccounts);
      window.ethereum.removeListener("chainChanged", onChain);
    };
  }, [hasMetaMask]);

  const getReadContracts = useCallback(async () => {
    if (!provider) return null;
    return {
      roleManager: new Contract(CONTRACTS.roleManager, ROLE_MANAGER_ABI, provider),
      registry: new Contract(CONTRACTS.registry, REGISTRY_ABI, provider),
    };
  }, [provider]);

  const getWriteContracts = useCallback(async () => {
    if (!provider) return null;
    const signer = await provider.getSigner();
    return {
      roleManager: new Contract(CONTRACTS.roleManager, ROLE_MANAGER_ABI, signer),
      registry: new Contract(CONTRACTS.registry, REGISTRY_ABI, signer),
    };
  }, [provider]);

  return { address, provider, chainOk, error, hasMetaMask, connect, disconnect, getReadContracts, getWriteContracts };
}
