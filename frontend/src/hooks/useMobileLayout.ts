import { useEffect, useState } from "react";
import { isMobileLayout } from "@/lib/connection";

export function useMobileLayout(): boolean {
  const [mobile, setMobile] = useState(() => isMobileLayout());
  useEffect(() => {
    const sync = () => setMobile(isMobileLayout());
    const mq = window.matchMedia("(max-width: 720px)");
    mq.addEventListener("change", sync);
    sync();
    return () => mq.removeEventListener("change", sync);
  }, []);
  return mobile;
}
