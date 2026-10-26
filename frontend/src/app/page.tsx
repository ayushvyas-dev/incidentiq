"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Siren } from "lucide-react";
import { api } from "@/lib/api/client";
import type { Incident, Page } from "@/lib/api/types";
import { Empty, ErrorBox, Heading, Loading, Status } from "@/components/ui";

export default function HomePage() {
  const readiness = useQuery({ queryKey: ["health/ready"], queryFn: () => api<{ status: string; dependencies: Record<string, string> }>("health/ready") });
  const incidents = useQuery({ queryKey: ["api/v1/incidents?limit=5"], queryFn: () => api<Page<Incident>>("api/v1/incidents?limit=5") });

  return <>
    <Heading title="Overview" description="Current system readiness and recent investigations." action={<Link href="/investigations/new" className="btn btn-primary"><Siren size={14}/> New investigation</Link>}/>
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_280px]">
      <section aria-labelledby="recent-heading">
        <div className="mb-2 flex items-center justify-between border-b border-[var(--line)] pb-3"><h2 id="recent-heading" className="text-[13px] font-semibold">Recent investigations</h2><Link href="/investigations" className="text-xs text-[var(--muted)] hover:text-[var(--ink)]">View all <ArrowRight className="ml-1 inline" size={13}/></Link></div>
        {incidents.isLoading ? <Loading/> : incidents.isError ? <ErrorBox message={incidents.error.message} retry={() => void incidents.refetch()}/> : incidents.data?.items.length ? <div className="divide-y divide-[var(--line)]">{incidents.data.items.map(item => <Link key={item.incident_id} href={`/investigations/${item.incident_id}`} className="flex items-center justify-between gap-4 py-3.5 hover:bg-[var(--soft)]"><div className="min-w-0"><div className="truncate text-[13px] font-medium">{item.title}</div><div className="mt-1 truncate text-[11px] text-[var(--muted)]">{item.service} · {item.environment} · {new Date(item.created_at).toLocaleString()}</div></div><Status value={item.status}/></Link>)}</div> : <div className="border-b border-[var(--line)]"><Empty title="No investigations yet" description="Start an investigation to review evidence and possible causes."/><div className="pb-5 text-center"><Link className="btn btn-primary" href="/investigations/new">Start an investigation</Link></div></div>}
      </section>
      <aside aria-labelledby="readiness-heading">
        <div className="mb-2 flex items-center justify-between border-b border-[var(--line)] pb-3"><h2 id="readiness-heading" className="text-[13px] font-semibold">System readiness</h2><span className="text-[10px] text-[var(--muted)]">Live</span></div>
        {readiness.isLoading ? <Loading/> : readiness.isError ? <ErrorBox message={readiness.error.message} retry={() => void readiness.refetch()}/> : readiness.data ? <div className="divide-y divide-[var(--line)]"><div className="flex items-center justify-between py-3 text-xs"><span>API</span><Status value={readiness.data.status}/></div>{Object.entries(readiness.data.dependencies || {}).map(([name, status]) => <div key={name} className="flex items-center justify-between py-3 text-xs"><span className="capitalize text-[var(--muted)]">{name.replaceAll("_", " ")}</span><Status value={status}/></div>)}</div> : <p className="py-3 text-xs text-[var(--muted)]">Readiness is unavailable.</p>}
        <Link href="/knowledge" className="mt-5 inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--ink)]">Add operational knowledge <ArrowRight size={13}/></Link>
      </aside>
    </div>
  </>;
}
