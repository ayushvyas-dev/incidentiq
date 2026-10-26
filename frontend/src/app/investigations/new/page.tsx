"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { api, json } from "@/lib/api/client";
import type { Analysis } from "@/lib/api/types";
import { FieldError, Heading, Label } from "@/components/ui";

const schema = z.object({ title: z.string().min(1).max(255), description: z.string().min(1).max(10000), service: z.string().min(1).max(128), environment: z.string().min(1).max(64), severity: z.enum(["SEV-1", "SEV-2", "SEV-3", "SEV-4", "unknown"]), symptoms: z.string(), log_excerpt: z.string().max(4000) }).superRefine((values, context) => {
  const symptoms = values.symptoms.split("\n").map(value => value.trim()).filter(Boolean);
  if (symptoms.length > 30) context.addIssue({ code: "custom", path: ["symptoms"], message: "Use at most 30 symptoms" });
  if (symptoms.some(value => value.length > 1000)) context.addIssue({ code: "custom", path: ["symptoms"], message: "Each symptom must be at most 1000 characters" });
});
type FormValues = z.infer<typeof schema>;

export default function NewInvestigationPage() {
  const router = useRouter();
  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { title: "", description: "", service: "", environment: "production", severity: "unknown", symptoms: "", log_excerpt: "" } });
  const mutation = useMutation({ mutationFn: (value: FormValues) => api<Analysis>("api/v1/incidents/analyze", json({ title: value.title, description: value.description, service: value.service, environment: value.environment, severity: value.severity, symptoms: value.symptoms.split("\n").map(s => s.trim()).filter(Boolean), log_excerpt: value.log_excerpt || null })), onSuccess: result => { toast.success("Investigation completed"); router.push(`/investigations/${result.incident_id}`); }, onError: error => toast.error(error.message) });
  return <><Heading eyebrow="Investigation" title="New analysis" description="Describe the incident. The result will distinguish retrieved evidence, hypotheses, and unknowns."/><form className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]" onSubmit={form.handleSubmit(value => mutation.mutate(value))}><div className="surface space-y-5 p-5 md:p-6"><div><Label htmlFor="title">Incident title</Label><input className="field" id="title" {...form.register("title")}/><FieldError>{form.formState.errors.title?.message}</FieldError></div><div><Label htmlFor="description">What happened?</Label><textarea className="field min-h-28 resize-y" id="description" {...form.register("description")}/><FieldError>{form.formState.errors.description?.message}</FieldError></div><div className="grid gap-4 sm:grid-cols-2"><div><Label htmlFor="service">Service</Label><input className="field" id="service" placeholder="payments-api" {...form.register("service")}/><FieldError>{form.formState.errors.service?.message}</FieldError></div><div><Label htmlFor="environment">Environment</Label><input className="field" id="environment" {...form.register("environment")}/><FieldError>{form.formState.errors.environment?.message}</FieldError></div></div><div className="grid gap-4 sm:grid-cols-2"><div><Label htmlFor="severity">Severity</Label><select className="field" id="severity" {...form.register("severity")}><option>unknown</option><option>SEV-1</option><option>SEV-2</option><option>SEV-3</option><option>SEV-4</option></select></div><div><Label htmlFor="symptoms">Symptoms (one per line)</Label><textarea className="field min-h-[74px]" id="symptoms" {...form.register("symptoms")}/><FieldError>{form.formState.errors.symptoms?.message}</FieldError></div></div><div><Label htmlFor="logs">Relevant log excerpt</Label><textarea className="field min-h-24 font-mono text-[11px]" id="logs" {...form.register("log_excerpt")}/><FieldError>{form.formState.errors.log_excerpt?.message}</FieldError></div><div className="flex justify-end"><button disabled={mutation.isPending} className="btn btn-primary" type="submit">{mutation.isPending ? "Analyzing…" : "Analyze incident"}</button></div></div><aside className="surface h-fit p-4"><div className="text-xs font-semibold">Evidence policy</div><p className="mt-2 text-xs leading-5 text-[var(--muted)]">Analysis uses the configured backend retrieval and model routing. IncidentIQ cites retrieved sources and reports when evidence is insufficient. Diagnostic actions are informational and read-only.</p></aside></form></>;
}
