"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BookOpenText, Command, FileSearch, LayoutDashboard, Menu, Search, Siren, X } from "lucide-react";
import { useState } from "react";

const nav = [
  { label: "Overview", href: "/", icon: LayoutDashboard },
  { label: "Investigations", href: "/investigations", icon: Siren },
  { label: "Knowledge base", href: "/knowledge", icon: BookOpenText },
  { label: "Search", href: "/search", icon: Search },
  { label: "Evaluations", href: "/evaluations", icon: FileSearch },
  { label: "Operations", href: "/operations", icon: Activity },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return <div className="min-h-screen md:flex">
    {open && <button aria-label="Close navigation" className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={() => setOpen(false)}/>}
    <aside className={`${open ? "fixed inset-y-0 left-0 z-40 flex w-60" : "hidden"} md:fixed md:inset-y-0 md:flex md:w-56 md:flex-col border-r border-[var(--line)] bg-[var(--panel)]`}>
      <div className="flex h-14 items-center gap-3 border-b border-[var(--line)] px-4"><div className="flex h-7 w-7 items-center justify-center rounded-md bg-neutral-900 text-white dark:bg-white dark:text-neutral-900"><Command size={15}/></div><span className="text-[14px] font-semibold tracking-[-.03em]">IncidentIQ</span><button className="ml-auto rounded p-1 text-[var(--muted)] hover:bg-[var(--soft)] md:hidden" onClick={() => setOpen(false)} aria-label="Close navigation"><X size={18}/></button></div>
      <nav aria-label="Main navigation" className="flex-1 space-y-1 px-3 pt-4">{nav.map(({ label, href, icon: Icon }) => { const active = href === "/" ? pathname === href : pathname.startsWith(href); return <Link key={href} href={href} onClick={() => setOpen(false)} aria-current={active ? "page" : undefined} className={`flex items-center gap-3 rounded-md px-3 py-2 text-[13px] ${active ? "bg-[var(--soft)] font-medium text-[var(--ink)]" : "text-[var(--muted)] hover:bg-[var(--soft)] hover:text-[var(--ink)]"}`}><Icon size={16} strokeWidth={1.8}/>{label}</Link>; })}</nav>
    </aside>
    <main className="min-w-0 flex-1 md:ml-56"><header className="sticky top-0 z-20 flex h-14 items-center border-b border-[var(--line)] bg-[var(--bg)] px-4 md:px-8"><button className="mr-3 rounded p-1 text-[var(--muted)] hover:bg-[var(--soft)] md:hidden" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)}><Menu size={19}/></button><div className="text-xs text-[var(--muted)]"><span className="text-[var(--ink)]">{nav.find((item) => item.href === "/" ? pathname === item.href : pathname.startsWith(item.href))?.label || "Investigation"}</span></div><div className="ml-auto flex items-center gap-2 text-[11px] text-[var(--muted)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]"/>Decision support</div></header><div className="mx-auto max-w-[1280px] px-4 py-6 md:px-8 md:py-8">{children}</div></main>
  </div>;
}
