// Deployed contract addresses on Polygon Amoy testnet (public — safe in frontend).
export const AMOY = {
  chainIdHex: "0x13882",            // 80002
  chainId: 80002,
  chainName: "Polygon Amoy Testnet",
  rpcUrl: "https://polygon-amoy-bor-rpc.publicnode.com",
  explorer: "https://amoy.polygonscan.com",
  currency: { name: "POL", symbol: "POL", decimals: 18 },
};

export const CONTRACTS = {
  roleManager: "0xFE1c043B2BeB69E49E8A218544DDEd2707dd421B",
  registry: "0xFfE959f46D2E86208805747e76aefFd094A28A17",
};

export const PIPELINE_ID = 1;

export const ROLES = {
  DATA_CLEANER: "DATA_CLEANER",
  MODEL_TRAINER: "MODEL_TRAINER",
  REVIEWER: "REVIEWER",
};

// Pipeline stages in order. requiredRole=null means root (no role gate).
export const STAGES = [
  { name: "dataset",     label: "Dataset",      requiredRole: null,            parents: [] },
  { name: "environment", label: "Environment",  requiredRole: null,            parents: [] },
  { name: "cleaning",    label: "Cleaning",     requiredRole: "DATA_CLEANER",  parents: ["dataset", "environment"] },
  { name: "training",    label: "Training",     requiredRole: "MODEL_TRAINER", parents: ["cleaning", "environment"] },
  { name: "model",       label: "Model review", requiredRole: "REVIEWER",      parents: ["training"] },
];

// Manifest hashes per stage. These identify each stage's certificate on-chain.
// Fill these from your receipts (manifest_sha256). Left as null until known;
// the UI shows "not certified" for a stage whose hash is null.
export const STAGE_HASHES = {
  dataset: null,
  environment: null,
  cleaning: null,
  training: null,
  model: null,
};
