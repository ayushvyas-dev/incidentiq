"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { Incident, Page } from "@/lib/api/types";
import { Empty, ErrorBox, Heading, Loading, Status } from "@/components/ui";

export default function InvestigationsPage() {
  const query = useQuery({ queryKey: ["incidents"], queryFn: () => api<Page<Incident>>("api/v1/incidents?limit=100") });
  return <><Heading eyebrow="Incident intelligence" title="Investigations" description="Incidents and their evidence-grounded analysis runs." action={<Link className="btn btn-primary" href="/investigations/new">＋ New investigation</Link>}/>
    {query.isLoading ? <Loading/> : query.isError ? <ErrorBox message={query.error.message} retry={() => void query.refetch()}/> : query.data?.items.length ? <div className="surface overflow-hidden"><div className="hidden grid-cols-[minmax(0,2fr)_1fr_1fr_1fr] gap-4 border-b border-[var(--line)] bg-[var(--soft)] px-5 py-3 text-[10px] font-medium uppercase tracking-wider text-[var(--muted)] md:grid"><span>Incident</span><span>Service</span><span>Severity</span><span>Status</span></div>{query.data.items.map(item => <Link key={item.incident_id} href={`/investigations/${item.incident_id}`} className="grid gap-2 border-b border-[var(--line)] px-4 py-4 last:border-0 hover:bg-[var(--soft)] md:grid-cols-[minmax(0,2fr)_1fr_1fr_1fr] md:items-center md:gap-4 md:px-5"><div className="min-w-0"><div className="truncate text-sm font-medium">{item.title}</div><div className="mt-1 truncate text-[11px] text-[var(--muted)]">{item.description}</div></div><span className="text-xs text-[var(--muted)]">{item.service} · {item.environment}</span><span className="text-xs">{item.severity}</span><Status value={item.status}/></Link>)}</div> : <div className="surface"><Empty title="No investigations returned" description="Start an analysis to create an incident and inspect its retrieved evidence."/></div>}</>;
}
