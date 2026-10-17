import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 2_000, retry: 1, refetchOnWindowFocus: false } },
});

const root = document.getElementById("root");
if (!root) throw new Error("#root missing from index.html");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">
        <App />
        <Toaster theme="dark" position="top-right" richColors closeButton /> {/* top-right: never over the verdict or the graph */}
      </MotionConfig>
    </QueryClientProvider>
  </StrictMode>,
);
