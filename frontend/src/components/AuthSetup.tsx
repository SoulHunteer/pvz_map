import { FormEvent, useState } from "react";

import { useSession } from "../lib/session";

export function AuthSetup(): JSX.Element {
  const { auth, setAuth, authError, loadingMe } = useSession();
  const [telegramId, setTelegramId] = useState(auth.telegramId || "");
  const [username, setUsername] = useState(auth.username || "");
  const [fullName, setFullName] = useState(auth.fullName || "");

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    await setAuth({
      telegramId: telegramId.trim(),
      username: username.trim(),
      fullName: fullName.trim()
    });
  };

  return (
    <main className="auth-shell">
      <section className="panel auth-panel">
        <p className="eyebrow">PVZ monitor</p>
        <h1>Web cabinet login</h1>
        <p className="muted">
          MVP uses dev-auth headers. Enter your Telegram ID to load your tracked items.
        </p>

        <form className="auth-form" onSubmit={onSubmit}>
          <label>
            Telegram ID
            <input
              required
              value={telegramId}
              onChange={(event) => setTelegramId(event.target.value)}
              placeholder="321704377"
            />
          </label>

          <label>
            Username
            <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="sereg" />
          </label>

          <label>
            Full name
            <input
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              placeholder="Sergey Example"
            />
          </label>

          <button type="submit" className="btn btn-primary" disabled={loadingMe}>
            {loadingMe ? "Checking access..." : "Continue"}
          </button>

          {authError && <p className="error-text">{authError}</p>}
        </form>
      </section>
    </main>
  );
}
