// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @dev Minimal interface to the RoleManager. The registry only needs to ask
 *      one question: may this account certify this stage in this pipeline?
 */
interface IRoleManager {
    function canCertify(uint256 pipelineId, string calldata stage, address account)
        external
        view
        returns (bool);
}

/**
 * @title CertificationRegistry
 * @notice Per-pipeline, role-aware registry for ML-pipeline stage certificates.
 *
 * Separation of concerns: this contract records provenance (manifest hash,
 * stage, parents, submitter, time) and enforces the parent-child chain. It
 * delegates ALL access control to an external RoleManager, which it queries
 * before storing a certificate. This keeps certification data independent from
 * role logic -- roles can be changed (or the RoleManager upgraded) without
 * touching the certificates already recorded here.
 *
 * Only the manifest HASH is stored on-chain; msg.sender records which actor
 * anchored each stage. Certificates are scoped by pipelineId so multiple
 * pipelines can run against the same registry without collisions.
 */
contract CertificationRegistry {

    IRoleManager public immutable roleManager;

    constructor(address roleManagerAddress) {
        require(roleManagerAddress != address(0), "roleManager required");
        roleManager = IRoleManager(roleManagerAddress);
    }

    struct Certificate {
        uint256   pipelineId;
        bytes32   manifestHash;
        string    stage;
        bytes32[] parents;
        address   submitter;
        uint256   timestamp;
        bool      exists;
    }

    // Certificates are keyed by (pipelineId, manifestHash) so the same hash can
    // exist in different pipelines. We hash the pair into a single key.
    mapping(bytes32 => Certificate) private certificates;
    bytes32[] public allKeys;

    event CertificateStored(
        uint256 indexed pipelineId,
        bytes32 indexed manifestHash,
        string stage,
        address indexed submitter,
        uint256 timestamp,
        uint256 parentCount
    );

    /// Internal composite key for (pipelineId, manifestHash).
    function _key(uint256 pipelineId, bytes32 manifestHash)
        internal
        pure
        returns (bytes32)
    {
        return keccak256(abi.encodePacked(pipelineId, manifestHash));
    }

    /**
     * @notice Anchor a stage certificate in a pipeline.
     *
     * Reverts if:
     *   - the manifest hash is empty or already certified in this pipeline,
     *   - the RoleManager says the caller may not certify this stage, or
     *   - any named parent certificate does not exist in this pipeline.
     */
    function storeCertificate(
        uint256 pipelineId,
        bytes32 manifestHash,
        string calldata stage,
        bytes32[] calldata parents
    ) external {
        require(manifestHash != bytes32(0), "empty manifest hash");

        bytes32 key = _key(pipelineId, manifestHash);
        require(!certificates[key].exists, "certificate already exists");

        // Access control delegated to the RoleManager.
        require(
            roleManager.canCertify(pipelineId, stage, msg.sender),
            "caller not authorized for stage"
        );

        // Parent chain check, scoped to this pipeline.
        for (uint256 i = 0; i < parents.length; i++) {
            require(
                certificates[_key(pipelineId, parents[i])].exists,
                "parent certificate not found"
            );
        }

        certificates[key] = Certificate({
            pipelineId: pipelineId,
            manifestHash: manifestHash,
            stage: stage,
            parents: parents,
            submitter: msg.sender,
            timestamp: block.timestamp,
            exists: true
        });
        allKeys.push(key);

        emit CertificateStored(
            pipelineId, manifestHash, stage, msg.sender, block.timestamp, parents.length
        );
    }

    // ------------------------------------------------------------- views
    function isCertified(uint256 pipelineId, bytes32 manifestHash)
        external
        view
        returns (bool)
    {
        return certificates[_key(pipelineId, manifestHash)].exists;
    }

    function getCertificate(uint256 pipelineId, bytes32 manifestHash)
        external
        view
        returns (
            string memory stage,
            bytes32[] memory parents,
            address submitter,
            uint256 timestamp
        )
    {
        Certificate storage c = certificates[_key(pipelineId, manifestHash)];
        require(c.exists, "certificate not found");
        return (c.stage, c.parents, c.submitter, c.timestamp);
    }

    function certificateCount() external view returns (uint256) {
        return allKeys.length;
    }
}
