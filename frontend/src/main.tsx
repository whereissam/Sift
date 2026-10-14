import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";
import { ThemeProvider } from "@/components/theme-provider";
import { DesktopSplash } from "@/components/DesktopSplash";
import { installDesktopFetch } from "@/lib/desktop";
import "./index.css";

// Desktop app: relative /api calls must reach the embedded backend.
installDesktopFetch();

const router = createRouter({ routeTree });

const rootElement = document.getElementById("root")!;
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
        <DesktopSplash>
          <RouterProvider router={router} />
        </DesktopSplash>
      </ThemeProvider>
    </React.StrictMode>
  );
}
