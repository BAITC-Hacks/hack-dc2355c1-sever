import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { Supervisor } from "./Supervisor";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{location.pathname.endsWith("/supervisor") ? <Supervisor /> : <App />}</React.StrictMode>,
);
