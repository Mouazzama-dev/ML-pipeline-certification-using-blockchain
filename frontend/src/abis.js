// Minimal human-readable ABIs — only the functions the frontend calls.
export const ROLE_MANAGER_ABI = [
  "function pipelineAdmin(uint256) view returns (address)",
  "function nextPipelineId() view returns (uint256)",
  "function hasRole(uint256 pipelineId, bytes32 role, address account) view returns (bool)",
  "function getStageRole(uint256 pipelineId, string stage) view returns (bytes32)",
  "function canCertify(uint256 pipelineId, string stage, address account) view returns (bool)",
  "function createPipeline() returns (uint256)",
  "function grantRole(uint256 pipelineId, bytes32 role, address account)",
  "function revokeRole(uint256 pipelineId, bytes32 role, address account)",
  "function setStageRole(uint256 pipelineId, string stage, bytes32 role)",
  "event PipelineCreated(uint256 indexed pipelineId, address indexed admin)",
  "event RoleGranted(uint256 indexed pipelineId, bytes32 indexed role, address indexed account)",
];

export const REGISTRY_ABI = [
  "function isCertified(uint256 pipelineId, bytes32 manifestHash) view returns (bool)",
  "function getCertificate(uint256 pipelineId, bytes32 manifestHash) view returns (string stage, bytes32[] parents, address submitter, uint256 timestamp)",
  "function certificateCount() view returns (uint256)",
  "function storeCertificate(uint256 pipelineId, bytes32 manifestHash, string stage, bytes32[] parents)",
  "event CertificateStored(uint256 indexed pipelineId, bytes32 indexed manifestHash, string stage, address indexed submitter, uint256 timestamp, uint256 parentCount)",
];
