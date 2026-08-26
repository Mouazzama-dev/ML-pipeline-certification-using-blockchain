// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title RoleManager
 * @notice Per-pipeline role management for the multi-actor certification system.
 *
 * Separation of concerns: this contract governs WHO may act in WHICH pipeline,
 * and in what role. It knows nothing about certificates. The CertificationRegistry
 * queries it (hasRole / stageRole) before allowing a stage to be certified.
 *
 * Everything is scoped by pipelineId, so the same actor address can be a
 * DATA_CLEANER in pipeline 1 and have no role in pipeline 2. Each pipeline has
 * its own admin (the person who created it), who assigns and revokes roles and
 * maps each stage to the role required to certify it.
 *
 * Roles are bytes32 tags, e.g. keccak256("DATA_CLEANER").
 */
contract RoleManager {

    // Global owner of the RoleManager (can create pipelines). Kept minimal;
    // per-pipeline control lives with each pipeline's admin.
    address public owner;

    // pipelineId => admin address (the creator / manager of that pipeline)
    mapping(uint256 => address) public pipelineAdmin;

    // pipelineId => role => account => hasRole?
    mapping(uint256 => mapping(bytes32 => mapping(address => bool))) private roles;

    // pipelineId => stage name => required role tag
    mapping(uint256 => mapping(string => bytes32)) public stageRole;

    // incrementing id for new pipelines
    uint256 public nextPipelineId = 1;

    event PipelineCreated(uint256 indexed pipelineId, address indexed admin);
    event RoleGranted(uint256 indexed pipelineId, bytes32 indexed role, address indexed account);
    event RoleRevoked(uint256 indexed pipelineId, bytes32 indexed role, address indexed account);
    event StageRoleSet(uint256 indexed pipelineId, string stage, bytes32 role);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyPipelineAdmin(uint256 pipelineId) {
        require(pipelineAdmin[pipelineId] == msg.sender, "not pipeline admin");
        _;
    }

    /**
     * @notice Create a new pipeline. The caller becomes its admin.
     * @return pipelineId the id assigned to the new pipeline.
     */
    function createPipeline() external returns (uint256 pipelineId) {
        pipelineId = nextPipelineId++;
        pipelineAdmin[pipelineId] = msg.sender;
        emit PipelineCreated(pipelineId, msg.sender);
    }

    /**
     * @notice Grant a role to an actor within a pipeline. Admin only.
     */
    function grantRole(uint256 pipelineId, bytes32 role, address account)
        external
        onlyPipelineAdmin(pipelineId)
    {
        roles[pipelineId][role][account] = true;
        emit RoleGranted(pipelineId, role, account);
    }

    /**
     * @notice Revoke a role from an actor within a pipeline. Admin only.
     */
    function revokeRole(uint256 pipelineId, bytes32 role, address account)
        external
        onlyPipelineAdmin(pipelineId)
    {
        roles[pipelineId][role][account] = false;
        emit RoleRevoked(pipelineId, role, account);
    }

    /**
     * @notice Map a stage name to the role required to certify it, per pipeline.
     * @dev role == bytes32(0) means "no role required" (e.g. root stages).
     */
    function setStageRole(uint256 pipelineId, string calldata stage, bytes32 role)
        external
        onlyPipelineAdmin(pipelineId)
    {
        stageRole[pipelineId][stage] = role;
        emit StageRoleSet(pipelineId, stage, role);
    }

    // ------------------------------------------------------------- views
    function hasRole(uint256 pipelineId, bytes32 role, address account)
        external
        view
        returns (bool)
    {
        return roles[pipelineId][role][account];
    }

    function getStageRole(uint256 pipelineId, string calldata stage)
        external
        view
        returns (bytes32)
    {
        return stageRole[pipelineId][stage];
    }

    /**
     * @notice Convenience check used by the CertificationRegistry: is `account`
     *         allowed to certify `stage` in `pipelineId`? True if the stage
     *         requires no role, or the account holds the required role.
     */
    function canCertify(uint256 pipelineId, string calldata stage, address account)
        external
        view
        returns (bool)
    {
        bytes32 required = stageRole[pipelineId][stage];
        if (required == bytes32(0)) {
            // no role set: only the pipeline admin may certify (root stages);
            // gated stages without a role stay locked (fail-closed)
            return account == pipelineAdmin[pipelineId];
        }
        return roles[pipelineId][required][account];
    }
}
