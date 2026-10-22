import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("EduPath could not find the application root.");
}

createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
