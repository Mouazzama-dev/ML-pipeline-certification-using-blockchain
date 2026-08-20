// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {CertificationRegistry} from "../src/CertificationRegistry.sol";

/**
 * @title CertificationRegistryTest
 * @notice Foundry tests for the certification registry.
 *
 * Run with:  forge test            (summary)
 *            forge test -vv         (with console output)
 *            forge test -vvvv       (full traces, useful when debugging)
 *
 * Each test_* function is an independent scenario. Foundry redeploys a fresh
 * contract via setUp() before every test, so tests never affect one another.
 */
contract CertificationRegistryTest is Test {
    CertificationRegistry internal registry;

    // Fake manifest hashes for the pipeline stages.
    bytes32 internal datasetHash  = keccak256("dataset_manifest");
    bytes32 internal cleaningHash = keccak256("cleaning_manifest");
    bytes32 internal trainingHash = keccak256("training_manifest");

    // Runs before EACH test — gives every test a clean registry.
    function setUp() public {
        registry = new CertificationRegistry();
    }

    // 1. A root certificate (no parents) can be stored.
    function test_StoreRootCertificate() public {
        bytes32[] memory noParents = new bytes32[](0);
        registry.storeCertificate(datasetHash, "dataset", noParents);
        assertTrue(registry.isCertified(datasetHash));
    }

    // 2. A child certificate stores when its parent already exists.
    function test_StoreChildWithExistingParent() public {
        bytes32[] memory noParents = new bytes32[](0);
        registry.storeCertificate(datasetHash, "dataset", noParents);

        bytes32[] memory parents = new bytes32[](1);
        parents[0] = datasetHash;
        registry.storeCertificate(cleaningHash, "cleaning", parents);

        assertTrue(registry.isCertified(cleaningHash));
    }

    // 3. Storing with a MISSING parent must revert (chain enforcement).
    function test_RevertWhen_ParentMissing() public {
        bytes32[] memory parents = new bytes32[](1);
        parents[0] = keccak256("never_certified");

        vm.expectRevert(bytes("parent certificate not found"));
        registry.storeCertificate(trainingHash, "training", parents);
    }

    // 4. Storing the same certificate twice must revert (no duplicates).
    function test_RevertWhen_Duplicate() public {
        bytes32[] memory noParents = new bytes32[](0);
        registry.storeCertificate(datasetHash, "dataset", noParents);

        vm.expectRevert(bytes("certificate already exists"));
        registry.storeCertificate(datasetHash, "dataset", noParents);
    }

    // 5. An empty (zero) hash must revert.
    function test_RevertWhen_EmptyHash() public {
        bytes32[] memory noParents = new bytes32[](0);
        vm.expectRevert(bytes("empty manifest hash"));
        registry.storeCertificate(bytes32(0), "dataset", noParents);
    }

    // 6. A stored certificate can be read back with correct data.
    function test_GetCertificateReturnsStoredData() public {
        bytes32[] memory noParents = new bytes32[](0);
        registry.storeCertificate(datasetHash, "dataset", noParents);

        bytes32[] memory parents = new bytes32[](1);
        parents[0] = datasetHash;
        registry.storeCertificate(cleaningHash, "cleaning", parents);

        (string memory stage, bytes32[] memory gotParents, address submitter, ) =
            registry.getCertificate(cleaningHash);

        assertEq(stage, "cleaning");
        assertEq(gotParents.length, 1);
        assertEq(gotParents[0], datasetHash);
        assertEq(submitter, address(this)); // the test contract submitted it
    }

    // 7. The certificate count reflects how many were stored.
    function test_CertificateCount() public {
        assertEq(registry.certificateCount(), 0);

        bytes32[] memory noParents = new bytes32[](0);
        registry.storeCertificate(datasetHash, "dataset", noParents);
        assertEq(registry.certificateCount(), 1);

        bytes32[] memory parents = new bytes32[](1);
        parents[0] = datasetHash;
        registry.storeCertificate(cleaningHash, "cleaning", parents);
        assertEq(registry.certificateCount(), 2);
    }

    // 8. A full chain: dataset -> cleaning -> training stores end to end.
    function test_FullChain() public {
        bytes32[] memory noParents = new bytes32[](0);
        registry.storeCertificate(datasetHash, "dataset", noParents);

        bytes32[] memory p1 = new bytes32[](1);
        p1[0] = datasetHash;
        registry.storeCertificate(cleaningHash, "cleaning", p1);

        bytes32[] memory p2 = new bytes32[](1);
        p2[0] = cleaningHash;
        registry.storeCertificate(trainingHash, "training", p2);

        assertTrue(registry.isCertified(trainingHash));
        assertEq(registry.certificateCount(), 3);
    }
}
