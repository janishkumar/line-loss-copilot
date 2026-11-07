import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Evidence from "./pages/Evidence";
import ShiftEvidence from "./pages/ShiftEvidence";
import Overview from "./pages/Overview";
import Validation from "./pages/Validation";
import Losses from "./pages/Losses";
import Reliability from "./pages/Reliability";
import StopRisk from "./pages/StopRisk";
import Notes from "./pages/Notes";

export default function App() {
  return (
    <>
      <header className="top">
        <h1>Line loss copilot</h1>
        <nav>
          <NavLink to="/">Overview</NavLink>
          <NavLink to="/losses">Losses</NavLink>
          <NavLink to="/reliability">Reliability</NavLink>
          <NavLink to="/risk">Stop risk</NavLink>
          <NavLink to="/notes">Notes</NavLink>
          <NavLink to="/validation">Validation</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/losses" element={<Losses />} />
          <Route path="/reliability" element={<Reliability />} />
          <Route path="/risk" element={<StopRisk />} />
          <Route path="/notes" element={<Notes />} />
          <Route path="/validation" element={<Validation />} />
          <Route path="/evidence/shift/:shiftId" element={<ShiftEvidence />} />
          <Route path="/evidence/:eventId" element={<Evidence />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}
