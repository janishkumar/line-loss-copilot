import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { endSession, getSession, getUsers, startSession, type DemoUser } from "./api";

export interface Session {
  user: DemoUser | null;
  users: DemoUser[];
  signIn: (userId: string) => Promise<void>;
  signOut: () => Promise<void>;
}

export const SessionContext = createContext<Session>({
  user: null,
  users: [],
  signIn: async () => {},
  signOut: async () => {},
});
export const useSession = () => useContext(SessionContext);

/** Holds the session user. The cookie is HttpOnly, so the page asks the API who it belongs to. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<DemoUser | null>(null);
  const [users, setUsers] = useState<DemoUser[]>([]);
  useEffect(() => {
    getUsers().then(setUsers).catch(() => setUsers([]));
    getSession().then((s) => setUser(s.user)).catch(() => setUser(null));
  }, []);
  const signIn = useCallback(async (id: string) => setUser(await startSession(id)), []);
  const signOut = useCallback(async () => {
    await endSession();
    setUser(null);
  }, []);
  return <SessionContext.Provider value={{ user, users, signIn, signOut }}>{children}</SessionContext.Provider>;
}

export default function UserSwitcher() {
  const { user, users, signIn, signOut } = useSession();
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="switcher">
      <label>
        <span className="muted">Demo user</span>{" "}
        <select
          value={user?.user_id ?? ""}
          onChange={(e) => e.target.value && signIn(e.target.value).then(() => setErr(null), (x: Error) => setErr(x.message))}
        >
          <option value="">Pick a user</option>
          {users.map((u) => (
            <option key={u.user_id} value={u.user_id}>
              {u.display_name}
            </option>
          ))}
        </select>
      </label>
      {user ? (
        <>
          <span className="muted">{user.role}</span>
          <span className="badge" title="Demo users are generated for the demo, not real people">
            Synthetic demo user
          </span>
          <button type="button" onClick={() => signOut()}>Sign out</button>
        </>
      ) : (
        <span className="muted">Not signed in</span>
      )}
      {err && <span role="alert">{err}</span>}
    </div>
  );
}
