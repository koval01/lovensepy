import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "@/App";
import { Toaster } from "@/components/ui/sonner";
import { ServiceProvider } from "@/hooks/use-service";
import "@/index.css";

const container = document.getElementById("root");
if (!container) throw new Error("Missing #root element");

createRoot(container).render(
  <StrictMode>
    <ServiceProvider>
      <App />
      <Toaster />
    </ServiceProvider>
  </StrictMode>,
);
