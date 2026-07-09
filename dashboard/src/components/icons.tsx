import type { SVGProps } from "react";

export type IconProps = SVGProps<SVGSVGElement>;

const strokeBase = {
  viewBox: "0 0 24 24",
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function HomeIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M4 11.5 12 4l8 7.5" />
      <path d="M6 10v9a1 1 0 0 0 1 1h3v-6h4v6h3a1 1 0 0 0 1-1v-9" />
    </svg>
  );
}

export function TradeIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M4 15 9 9l4 4 7-8" />
      <path d="M15 5h5v5" />
    </svg>
  );
}

export function AnalyticsIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M4 20V10" />
      <path d="M11 20V4" />
      <path d="M18 20v-7" />
    </svg>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <circle cx="12" cy="12" r="3.2" />
      <line x1="12" y1="3" x2="12" y2="6" />
      <line x1="12" y1="18" x2="12" y2="21" />
      <line x1="3" y1="12" x2="6" y2="12" />
      <line x1="18" y1="12" x2="21" y2="12" />
      <line x1="5.6" y1="5.6" x2="7.8" y2="7.8" />
      <line x1="16.2" y1="16.2" x2="18.4" y2="18.4" />
      <line x1="5.6" y1="18.4" x2="7.8" y2="16.2" />
      <line x1="16.2" y1="7.8" x2="18.4" y2="5.6" />
    </svg>
  );
}

export function PlayIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" stroke="none" {...props}>
      <path d="M7 5.5v13l11-6.5-11-6.5Z" />
    </svg>
  );
}

export function StopIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" stroke="none" {...props}>
      <rect x="6.5" y="6.5" width="11" height="11" rx="1.5" />
    </svg>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M12 3.5 21.5 20h-19L12 3.5Z" />
      <path d="M12 10v4" />
      <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="m9 5 7 7-7 7" />
    </svg>
  );
}

export function ArrowUpRightIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export function ArrowDownRightIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M7 7l10 10M17 7v10H7" />
    </svg>
  );
}

export function BellIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M6 10a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5h-15S6 14 6 10Z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </svg>
  );
}

export function ShieldIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M12 3.5 19 6v6c0 4.5-3 7.5-7 8.5-4-1-7-4-7-8.5V6l7-2.5Z" />
    </svg>
  );
}

export function ServerIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <rect x="4" y="4" width="16" height="6.5" rx="1.5" />
      <rect x="4" y="13.5" width="16" height="6.5" rx="1.5" />
      <path d="M7.5 7.25h.01M7.5 16.75h.01" />
    </svg>
  );
}

export function CpuIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
      <line x1="12" y1="2.5" x2="12" y2="5.5" />
      <line x1="12" y1="18.5" x2="12" y2="21.5" />
      <line x1="2.5" y1="12" x2="5.5" y2="12" />
      <line x1="18.5" y1="12" x2="21.5" y2="12" />
    </svg>
  );
}

export function MessageIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M4 5.5h16v11H9l-4 3.5v-3.5H4Z" />
    </svg>
  );
}

export function LinkIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="M9.5 14.5 14.5 9.5" />
      <path d="M11 7l1.5-1.5a3.5 3.5 0 0 1 5 5L16 12" />
      <path d="M13 17l-1.5 1.5a3.5 3.5 0 0 1-5-5L8 12" />
    </svg>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <svg {...strokeBase} {...props}>
      <path d="m5 12.5 4.5 4.5L19 7" />
    </svg>
  );
}
