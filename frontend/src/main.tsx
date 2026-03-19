import ReactDOM from "react-dom/client";

import App from "./App";
import { SessionProvider } from "./lib/session";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <SessionProvider>
    <App />
  </SessionProvider>
);
