import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Evidence from "./pages/Evidence";
import Overview from "./pages/Overview";
import Validation from "./pages/Validation";

export default function App() {
  return (
    <>
      <header className="top">
        <h1>Line loss copilot</h1>
        <nav>
          <NavLink to="/">Overview</NavLink>
          <NavLink to="/validation">Validation</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/validation" element={<Validation />} />
          <Route path="/evidence/:eventId" element={<Evidence />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}
