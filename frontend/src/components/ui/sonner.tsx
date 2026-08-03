import { Toaster as Sonner, type ToasterProps } from "sonner";

import { useTheme } from "@/hooks/use-theme";

function Toaster(props: ToasterProps) {
  const { resolved } = useTheme();
  return (
    <Sonner
      theme={resolved}
      position="top-center"
      closeButton
      // Below the sticky header, above the safe area; keeps toasts reachable on phones.
      offset={16}
      toastOptions={{
        className:
          "text-sm !rounded-2xl !border-hairline !bg-card !text-foreground !shadow-lg",
      }}
      {...props}
    />
  );
}

export { Toaster };
