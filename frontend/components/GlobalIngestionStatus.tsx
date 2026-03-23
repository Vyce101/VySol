"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Copy, Loader2, Upload } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { buildIngestActivityLabel, clampPercent, resolveStableIngestProgress } from "@/lib/ingest-progress";

interface CheckpointInfo {
    chunk_index?: number;
    chunks_total?: number;
    active_ingestion_run?: boolean;
    stage_counters?: {
        expected_chunks?: number;
        extracted_chunks?: number;
        embedded_chunks?: number;
        current_unique_nodes?: number;
        embedded_unique_nodes?: number;
        failed_records?: number;
        blocking_issues?: number;
    };
    progress_phase?: "extracting" | "chunk_embedding" | "unique_node_rebuild" | "audit_finalization" | "aborting" | "idle";
    progress_scope?: "source" | "world";
    completed_chunks_current_phase?: number;
    total_chunks_current_phase?: number;
    completed_work_units?: number;
    total_work_units?: number;
    overall_percent?: number;
    progress_percent?: number;
    active_operation?: string;
    active_agent?: string | null;
    wait_state?: "queued_for_extraction_slot" | "queued_for_embedding_slot" | "waiting_for_api_key" | null;
    wait_stage?: "extracting" | "embedding" | null;
    wait_label?: string | null;
    wait_retry_after_seconds?: number | null;
    progress_source_id?: string | null;
    progress_source_display_name?: string | null;
    progress_source_book_number?: number | null;
}

interface IngestionActivity {
    activity_id: string;
    kind: "ingestion";
    world_id: string;
    world_name: string;
    link_href?: string | null;
    ingestion_status: string;
    checkpoint: CheckpointInfo;
}

interface DuplicationActivity {
    activity_id: string;
    kind: "duplication";
    world_id: string;
    world_name: string;
    source_world_id?: string | null;
    source_world_name?: string | null;
    duplication_status: string;
    phase: "copying";
    progress_percent: number;
    completed_work_units: number;
    total_work_units: number;
}

type WorldActivity = IngestionActivity | DuplicationActivity;

interface DisplayActivity {
    activity_id: string;
    kind: "ingestion" | "duplication";
    world_id: string;
    world_name: string;
    link_href?: string | null;
    percent: number;
    completedWorkUnits: number;
    totalWorkUnits: number;
    detail: string;
    trailingLabel: string;
    useStoppingStyle: boolean;
}

const STORAGE_KEY = "global-ingestion-status-expanded";

export function GlobalIngestionStatus() {
    const [activities, setActivities] = useState<WorldActivity[]>([]);
    const [expanded, setExpanded] = useState(false);
    const [hydrated, setHydrated] = useState(false);

    useEffect(() => {
        setHydrated(true);
        try {
            const stored = window.localStorage.getItem(STORAGE_KEY);
            if (stored === "true") {
                setExpanded(true);
            }
        } catch {
            // Ignore localStorage issues.
        }
    }, []);

    useEffect(() => {
        if (!hydrated) return;

        let cancelled = false;
        let timeoutId: number | undefined;

        const poll = async () => {
            try {
                const nextActivities = await apiFetch<WorldActivity[]>("/worlds/activities");
                if (!cancelled) {
                    setActivities(nextActivities);
                }
            } catch {
                if (!cancelled) {
                    setActivities([]);
                }
            } finally {
                if (!cancelled) {
                    const nextDelay = activities.length > 0 ? 2500 : 6000;
                    timeoutId = window.setTimeout(poll, nextDelay);
                }
            }
        };

        void poll();

        return () => {
            cancelled = true;
            if (timeoutId) {
                window.clearTimeout(timeoutId);
            }
        };
    }, [hydrated, activities.length]);

    useEffect(() => {
        if (!hydrated) return;
        try {
            window.localStorage.setItem(STORAGE_KEY, String(expanded));
        } catch {
            // Ignore localStorage issues.
        }
    }, [expanded, hydrated]);

    const displayActivities = useMemo<DisplayActivity[]>(() => {
        return activities.map((activity) => {
            if (activity.kind === "duplication") {
                const total = Math.max(1, Number(activity.total_work_units || 0));
                const completed = Math.max(0, Math.min(total, Number(activity.completed_work_units || 0)));
                const percent = total > 0
                    ? clampPercent((completed / total) * 100)
                    : clampPercent(Number(activity.progress_percent || 0));
                return {
                    activity_id: activity.activity_id,
                    kind: activity.kind,
                    world_id: activity.world_id,
                    world_name: activity.world_name,
                    percent,
                    completedWorkUnits: completed,
                    totalWorkUnits: total,
                    detail: activity.source_world_name
                        ? `Duplicating from ${activity.source_world_name}`
                        : "Duplicating world data",
                    trailingLabel: `${Math.round(percent)}%`,
                    useStoppingStyle: false,
                };
            }

            const progress = resolveStableIngestProgress(activity.checkpoint);
            const isStopping = progress.phase === "aborting";
            return {
                activity_id: activity.activity_id,
                kind: activity.kind,
                world_id: activity.world_id,
                world_name: activity.world_name,
                link_href: activity.link_href,
                percent: progress.overallPercent,
                completedWorkUnits: progress.completedWorkUnits,
                totalWorkUnits: progress.totalWorkUnits,
                detail: isStopping
                    ? "Stopping after current in-flight work finishes"
                    : (
                        buildIngestActivityLabel(progress)
                        || (progress.operation === "reembed_all"
                            ? `Re-embedded ${progress.embeddedChunks}/${progress.expectedChunks || "?"} chunks`
                            : `Extracted ${progress.extractedChunks}/${progress.expectedChunks || "?"} • Embedded ${progress.embeddedChunks}/${progress.expectedChunks || "?"}`)
                    ),
                trailingLabel: isStopping ? "Stopping" : `${Math.round(progress.overallPercent)}%`,
                useStoppingStyle: isStopping,
            };
        });
    }, [activities]);

    const aggregate = useMemo(() => {
        const totalWorkUnits = displayActivities.reduce((sum, activity) => sum + activity.totalWorkUnits, 0);
        const completedWorkUnits = displayActivities.reduce((sum, activity) => sum + activity.completedWorkUnits, 0);
        const percent = totalWorkUnits > 0 ? clampPercent((completedWorkUnits / totalWorkUnits) * 100) : 0;
        return {
            totalWorkUnits,
            completedWorkUnits,
            percent,
        };
    }, [displayActivities]);

    const allDuplicating = displayActivities.length > 0 && displayActivities.every((activity) => activity.kind === "duplication");
    const allStopping = displayActivities.length > 0 && displayActivities.every((activity) => activity.useStoppingStyle);
    const HeaderIcon = allDuplicating ? Copy : Upload;

    if (!displayActivities.length) {
        return null;
    }

    const expandedTitle = allDuplicating
        ? (displayActivities.length === 1 ? "World duplication in progress" : `${displayActivities.length} worlds duplicating`)
        : (displayActivities.length === 1 ? "World activity in progress" : `${displayActivities.length} world activities running`);
    const expandedSubtitle = allStopping
        ? "Stopping in-flight work..."
        : allDuplicating
            ? (displayActivities.length === 1 ? "Creating a full copy of this world" : "Tracking duplicate-world jobs")
            : "Stable progress across active worlds";

    const collapsedTitle = displayActivities.length === 1
        ? displayActivities[0].world_name
        : allDuplicating
            ? `${displayActivities.length} worlds duplicating`
            : `${displayActivities.length} world activities`;
    const collapsedSubtitle = allStopping
        ? "Aborting..."
        : displayActivities.length === 1
            ? displayActivities[0].detail
            : allDuplicating
                ? "Duplication in progress"
                : "Work in progress";

    return (
        <div
            style={{
                position: "fixed",
                right: 20,
                bottom: 20,
                zIndex: 2000,
                width: expanded ? 340 : "auto",
                maxWidth: "calc(100vw - 32px)",
            }}
        >
            {expanded ? (
                <div
                    style={{
                        background: "var(--floating-surface)",
                        border: "1px solid var(--border-strong)",
                        borderRadius: 18,
                        boxShadow: "0 18px 40px var(--shadow-color)",
                        backdropFilter: "blur(14px)",
                        overflow: "hidden",
                    }}
                >
                    <button
                        onClick={() => setExpanded(false)}
                        style={{
                            width: "100%",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 12,
                            padding: "14px 16px 12px",
                            background: "linear-gradient(180deg, var(--primary-soft-strong), var(--primary-soft))",
                            border: "none",
                            color: "var(--text-primary)",
                            cursor: "pointer",
                            textAlign: "left",
                        }}
                    >
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <div
                                style={{
                                    width: 28,
                                    height: 28,
                                    borderRadius: 999,
                                    display: "grid",
                                    placeItems: "center",
                                    background: "var(--primary-soft-strong)",
                                    color: "var(--primary-light)",
                                }}
                            >
                                <HeaderIcon size={15} />
                            </div>
                            <div>
                                <div style={{ fontSize: 13, fontWeight: 600 }}>
                                    {expandedTitle}
                                </div>
                                <div style={{ fontSize: 12, color: "var(--text-subtle)" }}>
                                    {expandedSubtitle}
                                </div>
                            </div>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span style={{ fontSize: 12, color: "var(--primary-light)", fontWeight: 600 }}>
                                {allStopping ? "..." : `${Math.round(aggregate.percent)}%`}
                            </span>
                            <ChevronDown size={16} />
                        </div>
                    </button>

                    <div style={{ padding: "10px 12px 12px", display: "grid", gap: 10 }}>
                        {displayActivities.map((activity) => {
                            const body = (
                                <>
                                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
                                        <div style={{ minWidth: 0 }}>
                                            <div
                                                style={{
                                                    fontSize: 13,
                                                    fontWeight: 600,
                                                    whiteSpace: "nowrap",
                                                    overflow: "hidden",
                                                    textOverflow: "ellipsis",
                                                }}
                                            >
                                                {activity.world_name}
                                            </div>
                                            <div style={{ fontSize: 12, color: "var(--text-subtle)" }}>
                                                {activity.detail}
                                            </div>
                                        </div>
                                        <div style={{
                                            display: "flex",
                                            alignItems: "center",
                                            gap: 6,
                                            color: activity.useStoppingStyle ? "#fca5a5" : "var(--warning)",
                                            fontSize: 12,
                                            flexShrink: 0,
                                        }}>
                                            <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} />
                                            {activity.trailingLabel}
                                        </div>
                                    </div>
                                    <div
                                        style={{
                                            height: 8,
                                            borderRadius: 999,
                                            background: "var(--overlay-heavy)",
                                            overflow: "hidden",
                                        }}
                                    >
                                        <div
                                            style={{
                                                width: `${activity.percent}%`,
                                                height: "100%",
                                                borderRadius: 999,
                                                background: "linear-gradient(90deg, var(--primary), var(--primary-hover))",
                                                transition: "width 0.25s ease",
                                            }}
                                        />
                                    </div>
                                </>
                            );

                            const sharedStyle = {
                                display: "block",
                                padding: 12,
                                borderRadius: 14,
                                border: "1px solid var(--border)",
                                background: "var(--overlay)",
                                textDecoration: "none",
                                color: "inherit",
                            } as const;

                            return activity.link_href ? (
                                <Link key={activity.activity_id} href={activity.link_href} style={sharedStyle}>
                                    {body}
                                </Link>
                            ) : (
                                <div key={activity.activity_id} style={sharedStyle}>
                                    {body}
                                </div>
                            );
                        })}
                    </div>
                </div>
            ) : (
                <button
                    onClick={() => setExpanded(true)}
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        background: "var(--floating-surface)",
                        color: "var(--text-primary)",
                        border: "1px solid var(--border-strong)",
                        borderRadius: 999,
                        padding: "10px 14px",
                        boxShadow: "0 16px 34px var(--shadow-color)",
                        backdropFilter: "blur(14px)",
                        cursor: "pointer",
                    }}
                >
                    <span
                        style={{
                            width: 9,
                            height: 9,
                            borderRadius: "50%",
                            background: "var(--warning)",
                            boxShadow: "0 0 0 6px rgba(245, 158, 11, 0.12)",
                            animation: "pulse-glow 2s ease-in-out infinite",
                            flexShrink: 0,
                        }}
                    />
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", minWidth: 0 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.1 }}>
                            {collapsedTitle}
                        </span>
                        <span style={{ fontSize: 11, color: "var(--text-subtle)", lineHeight: 1.1 }}>
                            {collapsedSubtitle}
                        </span>
                    </div>
                    <span style={{ fontSize: 12, color: "var(--primary-light)", fontWeight: 600 }}>
                        {allStopping ? "..." : `${Math.round(aggregate.percent)}%`}
                    </span>
                    <ChevronUp size={16} />
                </button>
            )}
        </div>
    );
}
