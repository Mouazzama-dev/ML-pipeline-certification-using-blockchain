// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title CertificationRegistry
 * @notice On-chain registry for ML-pipeline stage certificates.
 *
 * Each certificate anchors the SHA-256 hash of a stage manifest (dataset,
 * cleaning, training, model, ...) together with references to its parent
 * certificates. The contract enforces the parent-child chain on-chain:
 * a stage cannot be certified unless all the parents it names already exist.
 *
 * Only the manifest HASH is stored on-chain, never the manifest contents or any
 * evidence file. Verification re-computes the hash off-chain and compares it to
 * the stored value, exactly as in the original design.
 *
 * The same contract deploys unchanged on any EVM chain (Polygon, Ethereum, ...),
 * which is what makes the certification layer blockchain-agnostic.
 */
contract CertificationRegistry {

    struct Certificate {
        bytes32 manifestHash;   // SHA-256 of the stage manifest
        string  stage;          // "dataset", "cleaning", "training", "model", ...
        bytes32[] parents;      // manifestHash of each parent certificate
        address submitter;      // who anchored it
        uint256 timestamp;      // block time when anchored
        bool    exists;         // guard flag (mapping default is all-zero)
    }

    // manifestHash => Certificate. The hash is the natural unique key.
    mapping(bytes32 => Certificate) private certificates;

    // Simple audit list of every hash ever certified, in order.
    bytes32[] public allHashes;

    event CertificateStored(
        bytes32 indexed manifestHash,
        string stage,
        address indexed submitter,
        uint256 timestamp,
        uint256 parentCount
    );

    /**
     * @notice Anchor a new stage certificate.
     * @param manifestHash SHA-256 of the manifest (as bytes32).
     * @param stage        Human-readable stage name.
     * @param parents      Hashes of parent certificates that must already exist.
     *
     * Reverts if this hash is already certified, or if any named parent is
     * missing -- this is the on-chain enforcement of the pipeline chain.
     */
    function storeCertificate(
        bytes32 manifestHash,
        string calldata stage,
        bytes32[] calldata parents
    ) external {
        require(manifestHash != bytes32(0), "empty manifest hash");
        require(!certificates[manifestHash].exists, "certificate already exists");

        // Every named parent must already be on-chain.
        for (uint256 i = 0; i < parents.length; i++) {
            require(
                certificates[parents[i]].exists,
                "parent certificate not found"
            );
        }

        certificates[manifestHash] = Certificate({
            manifestHash: manifestHash,
            stage: stage,
            parents: parents,
            submitter: msg.sender,
            timestamp: block.timestamp,
            exists: true
        });
        allHashes.push(manifestHash);

        emit CertificateStored(
            manifestHash,
            stage,
            msg.sender,
            block.timestamp,
            parents.length
        );
    }

    /**
     * @notice Return whether a manifest hash has been certified.
     */
    function isCertified(bytes32 manifestHash) external view returns (bool) {
        return certificates[manifestHash].exists;
    }

    /**
     * @notice Read back a stored certificate.
     * @dev Reverts if the certificate does not exist.
     */
    function getCertificate(bytes32 manifestHash)
        external
        view
        returns (
            string memory stage,
            bytes32[] memory parents,
            address submitter,
            uint256 timestamp
        )
    {
        Certificate storage c = certificates[manifestHash];
        require(c.exists, "certificate not found");
        return (c.stage, c.parents, c.submitter, c.timestamp);
    }

    /**
     * @notice Total number of certificates stored (for auditing / iteration).
     */
    function certificateCount() external view returns (uint256) {
        return allHashes.length;
    }
}
