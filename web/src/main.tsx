import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ModelGate } from "./ModelGate";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ModelGate>
      <App />
    </ModelGate>
  </StrictMode>,
);
