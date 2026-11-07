import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Evidence from "./pages/Evidence";
import ShiftEvidence from "./pages/ShiftEvidence";
import Overview from "./pages/Overview";
import Validation from "./pages/Validation";
import Losses from "./pages/Losses";
import Reliability from "./pages/Reliability";
import StopRisk from "./pages/StopRisk";
import Notes from "./pages/Notes";
import Chat from "./pages/Chat";
import Approvals from "./pages/Approvals";
import ApprovalDetail from "./pages/ApprovalDetail";
import Actions from "./pages/Actions";
import NewAction from "./pages/NewAction";
import Plan from "./pages/Plan";
import Shortages from "./pages/Shortages";
import Order from "./pages/Order";
import Audit from "./pages/Audit";
import UserSwitcher, { SessionProvider } from "./UserSwitcher";

export default function App() {
  return (
    <SessionProvider>
      <header className="top">
        <h1>Line loss copilot</h1>
        <nav>
          <NavLink to="/">Overview</NavLink>
          <NavLink to="/losses">Losses</NavLink>
          <NavLink to="/reliability">Reliability</NavLink>
          <NavLink to="/risk">Stop risk</NavLink>
          <NavLink to="/notes">Notes</NavLink>
          <NavLink to="/chat">Ask</NavLink>
          <NavLink to="/plan">Plan</NavLink>
          <NavLink to="/shortages">Shortages</NavLink>
          <NavLink to="/validation">Validation</NavLink>
          <NavLink to="/approvals">Approvals</NavLink>
          <NavLink to="/actions" end>Actions</NavLink>
          <NavLink to="/audit">Audit</NavLink>
        </nav>
        <UserSwitcher />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/losses" element={<Losses />} />
          <Route path="/reliability" element={<Reliability />} />
          <Route path="/risk" element={<StopRisk />} />
          <Route path="/notes" element={<Notes />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/plan" element={<Plan />} />
          <Route path="/shortages" element={<Shortages />} />
          <Route path="/orders/:id" element={<Order />} />
          <Route path="/validation" element={<Validation />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/approvals/:id" element={<ApprovalDetail />} />
          <Route path="/actions" element={<Actions />} />
          <Route path="/actions/new" element={<NewAction />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/evidence/shift/:shiftId" element={<ShiftEvidence />} />
          <Route path="/evidence/:eventId" element={<Evidence />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </SessionProvider>
  );
}
