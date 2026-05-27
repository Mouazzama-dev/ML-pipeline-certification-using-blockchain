# Blockchain-Certified AI Pipeline for Iris Classification

## Project Purpose

This is a terminal-based MVP for certifying an AI pipeline through blockchain.  
The project uses the Iris dataset for a simple classification model so that the primary focus remains on certificate-based provenance, integrity verification and traceability.

## Certification Strategy

Each pipeline stage will produce a manifest containing SHA-256 hashes of the relevant artifacts, source code, documentation and environment snapshot. The manifest will then be submitted as a certificate to the Circular testnet blockchain.

Planned certified stages:

1. Raw Dataset Baseline
2. Data Cleaning
3. Model Training
4. Final Model Certification and Verification

## Current Stage

**Stage 01: Raw Dataset Baseline — In Progress**

The raw Iris dataset has already been hashed, submitted to the blockchain and verified locally against its on-chain certificate.

## Raw Dataset Artifact

- Artifact path: `data/raw/IRIS.csv`
- Artifact SHA-256: `9194e2b71f7144e7d192a1c38f9a54f26b0e8f705c0929b8225b0cd10275efd1`
- Dataset manifest path: `certificates/manifests/dataset_manifest.json`
- Dataset manifest SHA-256: `e961ffd2d1500a99b274c3e202372a941db633f55ef5e725161a970d6a3f0cef`

## Existing Dataset Certificate Reference

- Network: Circular Testnet
- Certificate type: `C_TYPE_CERTIFICATE`
- Transaction status: `Executed`
- Transaction ID: `aa61c7c8d508cbfb95e53f2a5137a57f635ea97933ebbf1322d319120443bc0d`
- Block ID: `70660`

## Stage 01 Evidence to Be Certified

Stage 01 will create a new blockchain certificate referencing the existing dataset certificate and hashing the following evidence:

- Raw dataset: `data/raw/IRIS.csv`
- Dataset manifest: `certificates/manifests/dataset_manifest.json`
- Exact Python dependency snapshot: `requirements.lock.txt`
- Project documentation: `README.md`
- Current source-code files in `src/`
- Runtime/system information captured for Stage 01

## Development Note

The currently configured wallet is being used for development/testing. A fresh wallet and private key must be used before producing the final trusted certification chain.
