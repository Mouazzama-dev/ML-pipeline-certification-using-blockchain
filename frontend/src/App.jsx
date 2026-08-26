import { useState } from "react";
import { useWallet } from "./useWallet";
import { useRole } from "./useRole";
import AdminShell from "./admin/AdminShell";
import UserPortal from "./UserPortal";
import { short } from "./ui";

export default function App() {
  const [portal, setPortal] = useState(null);
  const { address, chainOk, error, connect, disconnect, getReadContracts, getWriteContracts } = useWallet();
  const { loading, isAdmin, actorStages, role, error: roleError } = useRole(getReadContracts, address);

  const goBack = () => { disconnect(); setPortal(null); };

  if (!portal) {
    return (
      <Shell>
        <h1 className="text-xl font-medium text-gray-900 mb-1">Blockchain ML Certification</h1>
        <p className="text-sm text-gray-500 mb-6">Multi-actor pipeline · Polygon Amoy</p>
        <div className="space-y-3">
          <ChoiceButton title="Admin login" desc="Manage pipelines and assign roles" onClick={() => setPortal("admin")} />
          <ChoiceButton title="User login" desc="Certify your assigned stage" onClick={() => setPortal("user")} />
        </div>
      </Shell>
    );
  }

  const isAdminPortal = portal === "admin";

  if (!address) {
    return (
      <Shell>
        <BackLink onClick={goBack} />
        <h1 className="text-xl font-medium text-gray-900 mb-1">{isAdminPortal ? "Admin login" : "User login"}</h1>
        <p className="text-sm text-gray-500 mb-6">Connect the wallet {isAdminPortal ? "that owns this pipeline" : "assigned to your stage"}.</p>
        <button onClick={connect} className="w-full rounded-lg bg-blue-600 text-white py-2.5 text-sm font-medium hover:bg-blue-700 transition">Connect wallet</button>
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      </Shell>
    );
  }

  if (loading) return (<Shell><BackLink onClick={goBack} /><p className="text-sm text-gray-500">Verifying wallet…</p></Shell>);

  const authorized = isAdminPortal ? isAdmin : actorStages.length > 0;
  if (!authorized) {
    return (
      <Shell>
        <BackLink onClick={goBack} />
        <h1 className="text-lg font-medium text-gray-900 mb-2">Access denied</h1>
        <p className="text-sm text-gray-600 mb-1">Wallet <span className="font-medium">{short(address)}</span>{isAdminPortal ? " is not the admin of this pipeline." : " has no role assigned in this pipeline."}</p>
        <button onClick={goBack} className="mt-4 w-full rounded-lg border border-gray-300 text-gray-700 py-2 text-sm hover:bg-gray-50 transition">Back</button>
        {roleError && <p className="mt-4 text-sm text-red-600">{roleError}</p>}
      </Shell>
    );
  }

  // Admin -> full sidebar shell. User -> single portal card.
  if (isAdminPortal) {
    return <AdminShell address={address} chainOk={chainOk} onLogout={goBack}
      getReadContracts={getReadContracts} getWriteContracts={getWriteContracts} />;
  }
  return (
    <Shell wide>
      <div className="flex items-center justify-between mb-5">
        <BackLink onClick={goBack} label="Log out" />
        <span className="text-sm text-gray-500">{short(address)} · {chainOk ? "Amoy" : "wrong network"}</span>
      </div>
      <UserPortal address={address} role={role} actorStages={actorStages}
        getReadContracts={getReadContracts} getWriteContracts={getWriteContracts} />
    </Shell>
  );
}

function Shell({ children, wide }) {
  return (<div className="min-h-screen flex items-center justify-center p-6">
    <div className={`w-full ${wide ? "max-w-2xl" : "max-w-md"} bg-white rounded-2xl border border-gray-200 p-8`}>{children}</div>
  </div>);
}
function ChoiceButton({ title, desc, onClick }) {
  return (<button onClick={onClick} className="w-full rounded-lg border border-gray-300 py-3 px-4 text-left hover:bg-gray-50 transition">
    <span className="block text-sm font-medium text-gray-800">{title}</span><span className="block text-xs text-gray-500 mt-0.5">{desc}</span></button>);
}
function BackLink({ onClick, label = "Back" }) {
  return (<button onClick={onClick} className="text-sm text-gray-500 hover:text-gray-800 transition inline-flex items-center gap-1">← {label}</button>);
}
