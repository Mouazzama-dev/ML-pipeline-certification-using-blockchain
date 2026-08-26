import { useState } from "react";
import { short } from "../ui";
import Dashboard from "./Dashboard";
import CreatePipeline from "./CreatePipeline";
import CertifyRoots from "./CertifyRoots";
import RoleManagement from "./RoleManagement";
import PipelineView from "./PipelineView";
import ChainAudit from "./ChainAudit";

const NAV = [
  { key: "dashboard", label: "Dashboard" },
  { key: "create",    label: "Create Pipeline" },
  { key: "certify",   label: "Certify Dataset/Env" },
  { key: "roles",     label: "Role Management" },
  { key: "pipeline",  label: "Pipeline View" },
  { key: "audit",     label: "Chain Audit" },
];

export default function AdminShell({ address, chainOk, onLogout, getReadContracts, getWriteContracts }) {
  const [tab, setTab] = useState("dashboard");
  const [selectedPipeline, setSelectedPipeline] = useState(1);

  const ctx = { address, getReadContracts, getWriteContracts,
                selectedPipeline, setSelectedPipeline, goToPipeline: (id) => { setSelectedPipeline(id); setTab("pipeline"); } };

  return (
    <div className="min-h-screen flex bg-gray-50">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 text-gray-300 flex flex-col">
        <div className="px-5 py-5 border-b border-gray-800">
          <div className="text-white font-medium">Admin Portal</div>
          <div className="text-xs text-gray-500 mt-0.5">Pipeline governance</div>
        </div>
        <nav className="flex-1 py-3">
          {NAV.map((n) => (
            <button key={n.key} onClick={() => setTab(n.key)}
              className={`w-full text-left px-5 py-2.5 text-sm transition ${tab === n.key ? "bg-blue-600 text-white" : "hover:bg-gray-800"}`}>
              {n.label}
            </button>
          ))}
        </nav>
        <div className="px-5 py-4 border-t border-gray-800 text-xs">
          <div className="text-gray-400">{short(address)}</div>
          <div className={chainOk ? "text-green-500" : "text-amber-500"}>{chainOk ? "● Amoy" : "● wrong network"}</div>
          <button onClick={onLogout} className="mt-2 text-gray-400 hover:text-white">Log out</button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-4xl mx-auto px-8 py-8">
          {tab === "dashboard" && <Dashboard ctx={ctx} />}
          {tab === "create"    && <CreatePipeline ctx={ctx} />}
          {tab === "certify"   && <CertifyRoots ctx={ctx} />}
          {tab === "roles"     && <RoleManagement ctx={ctx} />}
          {tab === "pipeline"  && <PipelineView ctx={ctx} />}
          {tab === "audit"     && <ChainAudit ctx={ctx} />}
        </div>
      </main>
    </div>
  );
}
