/** Logo Rekamind. Bentuknya identik dengan docs/assets/logo.svg, favicon, dan ikon aplikasi desktop. */
export function Logo({ className = "size-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden focusable="false">
      <rect width="32" height="32" rx="8" fill="#4f46e5" />
      <circle cx="16" cy="16" r="6" fill="#fff" />
      <circle cx="16" cy="16" r="2.5" fill="#4f46e5" />
    </svg>
  );
}
