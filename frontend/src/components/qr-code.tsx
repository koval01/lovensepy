import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface Props {
  value: string;
  size?: number;
  className?: string;
  alt?: string;
}

/**
 * Renders a QR code client-side.
 *
 * Generating it in the browser (instead of asking the service for an image) keeps the
 * payload on-device and works offline, which matters because the code usually encodes
 * a private LAN address.
 */
export function QrCode({ value, size = 216, className, alt = "QR code" }: Props) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDataUrl(null);
    QRCode.toDataURL(value, {
      errorCorrectionLevel: "M",
      margin: 2,
      width: size * 2,
      color: { dark: "#0b0b0f", light: "#ffffff" },
    })
      .then((url) => {
        if (!cancelled) setDataUrl(url);
      })
      .catch(() => {
        if (!cancelled) setDataUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [size, value]);

  if (!dataUrl) {
    return <Skeleton className={cn("rounded-xl", className)} style={{ width: size, height: size }} />;
  }

  return (
    <img
      src={dataUrl}
      alt={alt}
      width={size}
      height={size}
      className={cn("rounded-xl bg-white p-2 shadow-sm", className)}
      style={{ width: size, height: size }}
    />
  );
}
