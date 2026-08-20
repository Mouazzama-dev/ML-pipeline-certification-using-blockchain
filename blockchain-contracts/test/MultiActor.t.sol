// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {RoleManager} from "../src/RoleManager.sol";
import {CertificationRegistry} from "../src/CertificationRegistryV2.sol";

/**
 * Integration tests: RoleManager + CertificationRegistry together.
 * Run: forge test --match-contract MultiActorTest -vv
 */
contract MultiActorTest is Test {
    RoleManager internal roles;
    CertificationRegistry internal registry;

    bytes32 internal DATA_CLEANER  = keccak256("DATA_CLEANER");
    bytes32 internal MODEL_TRAINER = keccak256("MODEL_TRAINER");

    address internal admin   = address(this);     // creates the pipeline
    address internal personA = address(0xA11CE);  // cleaner
    address internal personB = address(0xB0B);    // trainer
    address internal outsider= address(0xDEAD);

    uint256 internal pid;

    bytes32 internal cleaningHash = keccak256("cleaning_manifest");
    bytes32 internal trainingHash = keccak256("training_manifest");
    bytes32 internal datasetHash  = keccak256("dataset_manifest");

    function setUp() public {
        roles = new RoleManager();
        registry = new CertificationRegistry(address(roles));

        // admin creates a pipeline and wires up per-pipeline roles
        pid = roles.createPipeline();
        roles.grantRole(pid, DATA_CLEANER, personA);
        roles.grantRole(pid, MODEL_TRAINER, personB);
        roles.setStageRole(pid, "cleaning", DATA_CLEANER);
        roles.setStageRole(pid, "training", MODEL_TRAINER);
        // dataset stage intentionally left with no role (root)
    }

    function test_AdminIsPipelineCreator() public view {
        assertEq(roles.pipelineAdmin(pid), admin);
    }

    // Root stage (no role) can be certified by anyone.
    function test_RootStageAnyone() public {
        bytes32[] memory none = new bytes32[](0);
        vm.prank(outsider);
        registry.storeCertificate(pid, datasetHash, "dataset", none);
        assertTrue(registry.isCertified(pid, datasetHash));
    }

    // Correct actor certifies cleaning.
    function test_CleanerCertifies() public {
        bytes32[] memory none = new bytes32[](0);
        vm.prank(personA);
        registry.storeCertificate(pid, cleaningHash, "cleaning", none);
        assertTrue(registry.isCertified(pid, cleaningHash));
    }

    // Wrong actor (trainer doing cleaning) reverts.
    function test_RevertWhen_WrongActor() public {
        bytes32[] memory none = new bytes32[](0);
        vm.prank(personB);
        vm.expectRevert(bytes("caller not authorized for stage"));
        registry.storeCertificate(pid, cleaningHash, "cleaning", none);
    }

    // Outsider with no role reverts.
    function test_RevertWhen_Outsider() public {
        bytes32[] memory none = new bytes32[](0);
        vm.prank(outsider);
        vm.expectRevert(bytes("caller not authorized for stage"));
        registry.storeCertificate(pid, cleaningHash, "cleaning", none);
    }

    // Non-admin cannot grant roles.
    function test_RevertWhen_NonAdminGrants() public {
        vm.prank(personA);
        vm.expectRevert(bytes("not pipeline admin"));
        roles.grantRole(pid, DATA_CLEANER, outsider);
    }

    // Full multi-actor chain: A certifies cleaning, B certifies training.
    function test_FullMultiActorChain() public {
        bytes32[] memory none = new bytes32[](0);
        vm.prank(personA);
        registry.storeCertificate(pid, cleaningHash, "cleaning", none);

        bytes32[] memory parents = new bytes32[](1);
        parents[0] = cleaningHash;
        vm.prank(personB);
        registry.storeCertificate(pid, trainingHash, "training", parents);

        (, , address submitter, ) = registry.getCertificate(pid, trainingHash);
        assertEq(submitter, personB);
    }

    // Per-pipeline isolation: a role in pipeline 1 does NOT apply to pipeline 2.
    function test_PerPipelineIsolation() public {
        // admin creates a second pipeline; personA gets NO role there
        uint256 pid2 = roles.createPipeline();
        roles.setStageRole(pid2, "cleaning", DATA_CLEANER);

        bytes32[] memory none = new bytes32[](0);
        vm.prank(personA);
        vm.expectRevert(bytes("caller not authorized for stage"));
        registry.storeCertificate(pid2, cleaningHash, "cleaning", none);
    }

    // Same manifest hash can exist independently in two pipelines.
    function test_SameHashDifferentPipelines() public {
        bytes32[] memory none = new bytes32[](0);

        // pipeline 1: personA certifies
        vm.prank(personA);
        registry.storeCertificate(pid, cleaningHash, "cleaning", none);

        // pipeline 2: set up personA as cleaner there too, then certify same hash
        uint256 pid2 = roles.createPipeline();
        roles.grantRole(pid2, DATA_CLEANER, personA);
        roles.setStageRole(pid2, "cleaning", DATA_CLEANER);
        vm.prank(personA);
        registry.storeCertificate(pid2, cleaningHash, "cleaning", none);

        assertTrue(registry.isCertified(pid, cleaningHash));
        assertTrue(registry.isCertified(pid2, cleaningHash));
    }
}
