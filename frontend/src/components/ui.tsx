import Link from "next/link";
import { ArrowUpRight, CircleAlert, LoaderCircle } from "lucide-react";

export function Heading({ title, description, action }: { eyebrow?: string; title: string; description?: string; action?: React.ReactNode }) {
  return <div className="mb-6 flex flex-wrap items-center justify-between gap-4"><div><h1 className="text-[24px] font-semibold tracking-[-.03em]">{title}</h1>{description && <p className="mt-1 max-w-2xl text-[13px] leading-5 text-[var(--muted)]">{description}</p>}</div>{action}</div>;
}
export function Panel({ title, detail, action, children, className = "" }: { title?: React.ReactNode; detail?: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return <section className={`surface ${className}`}>{(title || action) && <div className="flex items-center justify-between gap-3 border-b border-[var(--line)] px-4 py-3.5 md:px-5"><div>{title && <h2 className="text-[13px] font-semibold">{title}</h2>}{detail && <p className="mt-1 text-[11px] text-[var(--muted)]">{detail}</p>}</div>{action}</div>}<div className="p-4 md:p-5">{children}</div></section>;
}
export function Status({ value }: { value: string | null | undefined }) {
  const s = (value || "unknown").toLowerCase();
  const good = ["completed", "ready", "healthy", "succeeded", "evidence_found"].includes(s);
  const bad = ["failed", "error", "unhealthy", "insufficient_evidence"].includes(s);
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-medium ${good ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : bad ? "border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-300" : "border-[var(--line)] bg-[var(--soft)] text-[var(--muted)]"}`}><span className={`h-1.5 w-1.5 rounded-full ${good ? "bg-emerald-500" : bad ? "bg-rose-500" : "bg-neutral-400"}`}/>{value || "Unknown"}</span>;
}
export function Empty({ title, description }: { title: string; description: string }) { return <div className="py-10 text-center"><div className="mx-auto mb-3 flex h-9 w-9 items-center justify-center rounded-full bg-[var(--soft)] text-[var(--muted)]"><CircleAlert size={17}/></div><p className="text-sm font-medium">{title}</p><p className="mx-auto mt-1 max-w-sm text-xs leading-5 text-[var(--muted)]">{description}</p></div>; }
export function Loading() { return <div className="flex items-center gap-2 py-8 text-xs text-[var(--muted)]"><LoaderCircle className="animate-spin" size={15}/>Loading backend data…</div>; }
export function ErrorBox({ message, retry }: { message: string; retry?: () => void }) { return <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-xs text-rose-700 dark:text-rose-300"><div>{message}</div>{retry && <button className="btn mt-3" onClick={retry}>Retry</button>}</div>; }
export function LinkAction({ href, children }: { href: string; children: React.ReactNode }) { return <Link className="btn btn-primary" href={href}>{children}<ArrowUpRight size={14}/></Link>; }
export function FieldError({ children }: { children?: React.ReactNode }) { return children ? <p role="alert" className="mt-1 text-[11px] text-rose-600">{children}</p> : null; }
export function Label({ children, htmlFor }: { children: React.ReactNode; htmlFor: string }) { return <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium">{children}</label>; }
