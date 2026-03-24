"use client";

import Image from "next/image";
import { useState, useEffect } from "react";
import { Settings, Plus, MoreVertical, Trash2, Pencil, Loader2, Copy } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useRouter } from "next/navigation";
import { SettingsSidebar } from "@/components/SettingsSidebar";
import { CreateWorldModal } from "@/components/CreateWorldModal";

interface World {
    world_id: string;
    world_name: string;
    created_at: string;
    ingestion_status: string;
    total_chunks: number;
    total_nodes: number;
    total_edges: number;
    sources: Array<{ source_id: string; status: string }>;
    is_temporary_duplicate?: boolean;
    duplication_status?: string;
    duplication_progress_percent?: number;
    duplication_source_world_id?: string;
    duplication_source_world_name?: string;
    active_duplication_run?: boolean;
    duplication_locked?: boolean;
    duplication_error?: string | null;
}

function StatusBadge({ status }: { status: string }) {
    const styles: Record<string, string> = {
        pending: "background: var(--status-pending-bg); color: var(--status-pending-fg)",
        in_progress: "background: var(--status-progress-bg); color: var(--status-progress-fg)",
        duplicating: "background: var(--status-progress-bg); color: var(--status-progress-fg)",
        complete: "background: var(--status-success-bg); color: var(--status-success-fg)",
        error: "background: var(--status-error-bg); color: var(--status-error-fg)",
    };

    return (
        <span
            style={{
                ...Object.fromEntries((styles[status] || styles.pending).split(";").map(s => s.trim().split(":").map(v => v.trim())).filter(a => a.length === 2).map(([k, v]) => [k.replace(/-([a-z])/g, (_, c) => c.toUpperCase()), v])),
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "2px 10px",
                borderRadius: "9999px",
                fontSize: "12px",
                fontWeight: 500,
            }}
        >
            {(status === "in_progress" || status === "duplicating") && (
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--status-progress-fg)", animation: "pulse-glow 2s infinite" }} />
            )}
            {status === "complete" && (
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--status-success-fg)" }} />
            )}
            {status.replace("_", " ")}
        </span>
    );
}

const WORLD_STAT_ITEMS = [
    { key: "nodes", label: "Nodes" },
    { key: "edges", label: "Edges" },
    { key: "chunks", label: "Chunks" },
] as const;

function WorldCard({
    world,
    onRefresh,
    onDuplicate,
    duplicatePending,
}: {
    world: World;
    onRefresh: () => void;
    onDuplicate: (world: World) => Promise<void>;
    duplicatePending: boolean;
}) {
    const router = useRouter();
    const [menuOpen, setMenuOpen] = useState(false);
    const [renaming, setRenaming] = useState(false);
    const [newName, setNewName] = useState(world.world_name);
    const isTemporaryDuplicate = Boolean(world.is_temporary_duplicate);
    const isDuplicating = isTemporaryDuplicate && world.duplication_status === "in_progress";
    const isDuplicateError = isTemporaryDuplicate && world.duplication_status === "error";
    const displayStatus = isDuplicating ? "duplicating" : isDuplicateError ? "error" : world.ingestion_status;
    const duplicateDisabled = duplicatePending || isTemporaryDuplicate || Boolean(world.duplication_locked);
    const renameDisabled = duplicatePending || isTemporaryDuplicate;
    const deleteDisabled = duplicatePending || isDuplicating;
    const interactiveCard = !renaming && !menuOpen && !isTemporaryDuplicate && !duplicatePending;

    const handleClick = () => {
        if (renaming || menuOpen || isTemporaryDuplicate || duplicatePending) return;
        if (world.ingestion_status === "complete") {
            router.push(`/worlds/${world.world_id}/chat`);
        } else {
            router.push(`/worlds/${world.world_id}/ingest`);
        }
    };

    const handleRename = async () => {
        if (!newName.trim()) return;
        await apiFetch(`/worlds/${world.world_id}`, {
            method: "PATCH",
            body: JSON.stringify({ world_name: newName }),
        });
        setRenaming(false);
        onRefresh();
    };

    const handleDelete = async () => {
        if (!confirm(`Delete "${world.world_name}"? This cannot be undone.`)) return;
        try {
            await apiFetch(`/worlds/${world.world_id}`, { method: "DELETE" });
            onRefresh();
        } catch (err: unknown) {
            alert((err as Error).message);
        }
    };

    return (
        <div
            onClick={handleClick}
            style={{
                background: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                minHeight: 148,
                cursor: interactiveCard ? "pointer" : "default",
                transition: "border-color 0.2s, transform 0.2s",
                position: "relative",
                boxShadow: "0 12px 26px color-mix(in srgb, var(--shadow-color) 55%, transparent)",
            }}
            onMouseEnter={(e) => {
                if (!interactiveCard) return;
                (e.currentTarget as HTMLElement).style.borderColor = "var(--border-hover)";
                (e.currentTarget as HTMLElement).style.transform = "translateY(-2px)";
            }}
            onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
                (e.currentTarget as HTMLElement).style.transform = "none";
            }}
        >
            <div style={{ position: "absolute", top: 12, right: 12 }}>
                <button
                    onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
                    style={{ background: "none", border: "none", color: "var(--text-subtle)", cursor: "pointer", padding: 4 }}
                >
                    <MoreVertical size={16} />
                </button>
                {menuOpen && (
                    <div style={{
                        position: "absolute", right: 0, top: 28, background: "var(--card)", border: "1px solid var(--border)",
                        borderRadius: "8px", padding: "4px", zIndex: 10, minWidth: 120,
                    }}>
                        <button
                            disabled={duplicateDisabled}
                            onClick={(e) => {
                                e.stopPropagation();
                                setMenuOpen(false);
                                void onDuplicate(world);
                            }}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                width: "100%",
                                padding: "8px 12px",
                                background: "none",
                                border: "none",
                                color: "var(--text-primary)",
                                cursor: duplicateDisabled ? "not-allowed" : "pointer",
                                opacity: duplicateDisabled ? 0.55 : 1,
                                fontSize: 13,
                                borderRadius: 6,
                            }}
                        >
                            {duplicatePending ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Copy size={14} />}
                            {duplicatePending ? "Duplicating..." : "Duplicate"}
                        </button>
                        <button
                            disabled={renameDisabled}
                            onClick={(e) => { e.stopPropagation(); setRenaming(true); setMenuOpen(false); }}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                width: "100%",
                                padding: "8px 12px",
                                background: "none",
                                border: "none",
                                color: "var(--text-primary)",
                                cursor: renameDisabled ? "not-allowed" : "pointer",
                                opacity: renameDisabled ? 0.55 : 1,
                                fontSize: 13,
                                borderRadius: 6,
                            }}
                        >
                            <Pencil size={14} /> Rename
                        </button>
                        <button
                            disabled={deleteDisabled}
                            onClick={(e) => { e.stopPropagation(); handleDelete(); setMenuOpen(false); }}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                width: "100%",
                                padding: "8px 12px",
                                background: "none",
                                border: "none",
                                color: "var(--status-error-fg)",
                                cursor: deleteDisabled ? "not-allowed" : "pointer",
                                opacity: deleteDisabled ? 0.55 : 1,
                                fontSize: 13,
                                borderRadius: 6,
                            }}
                        >
                            <Trash2 size={14} /> Delete
                        </button>
                    </div>
                )}
            </div>

            {renaming ? (
                <input
                    autoFocus
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    onBlur={handleRename}
                    onKeyDown={(e) => e.key === "Enter" && handleRename()}
                    onClick={(e) => e.stopPropagation()}
                    style={{ fontSize: 18, fontWeight: 600, width: "80%", background: "var(--background-secondary)", padding: "4px 8px" }}
                />
            ) : (
                <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 12, paddingRight: 24 }}>{world.world_name}</h3>
            )}

            <div
                style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                    gap: 16,
                    marginBottom: 14,
                }}
            >
                {WORLD_STAT_ITEMS.map((item) => {
                    const value = item.key === "nodes"
                        ? world.total_nodes
                        : item.key === "edges"
                            ? world.total_edges
                            : world.total_chunks;
                    return (
                        <div key={item.key} style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                            <span style={{ fontSize: 21, lineHeight: 1.05, fontWeight: 500, color: "var(--text-primary)" }}>
                                {value}
                            </span>
                            <span style={{ fontSize: 12, lineHeight: 1.2, color: "var(--text-subtle)" }}>
                                {item.label}
                            </span>
                        </div>
                    );
                })}
            </div>

            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: isTemporaryDuplicate ? 10 : 0, width: "100%", marginTop: "auto" }}>
                <StatusBadge status={displayStatus} />
                {isTemporaryDuplicate && (
                    <div style={{ display: "grid", gap: 8, width: "100%" }}>
                        <div style={{ fontSize: 12, color: "var(--text-subtle)" }}>
                            {isDuplicateError
                                ? (world.duplication_error || "Duplication failed before the world finished copying.")
                                : world.duplication_source_world_name
                                ? `Copying from ${world.duplication_source_world_name}`
                                : "Duplicating world data"}
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
                                    width: `${Math.max(0, Math.min(100, Number(world.duplication_progress_percent || 0)))}%`,
                                    height: "100%",
                                    borderRadius: 999,
                                    background: isDuplicateError
                                        ? "linear-gradient(90deg, var(--status-error-fg), color-mix(in srgb, var(--status-error-fg) 65%, transparent))"
                                        : "linear-gradient(90deg, var(--primary), var(--primary-hover))",
                                    transition: "width 0.25s ease",
                                }}
                            />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

export default function HomePage() {
    const [worlds, setWorlds] = useState<World[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [showCreate, setShowCreate] = useState(false);
    const [showSettings, setShowSettings] = useState(false);
    const [duplicatePendingWorldId, setDuplicatePendingWorldId] = useState<string | null>(null);

    const fetchWorlds = async () => {
        try {
            const data = await apiFetch<World[]>("/worlds");
            setWorlds(data);
            setLoadError(null);
        } catch (err: unknown) {
            setLoadError((err as Error).message || "Could not load worlds.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchWorlds(); }, []);

    useEffect(() => {
        const hasDuplicateInProgress = worlds.some(
            (world) => world.is_temporary_duplicate && world.duplication_status === "in_progress",
        );
        if (!hasDuplicateInProgress) return;
        const intervalId = window.setInterval(() => {
            void fetchWorlds();
        }, 2500);
        return () => window.clearInterval(intervalId);
    }, [worlds]);

    const handleDuplicateWorld = async (world: World) => {
        if (duplicatePendingWorldId || world.is_temporary_duplicate || world.duplication_locked) {
            return;
        }
        setDuplicatePendingWorldId(world.world_id);
        try {
            await apiFetch(`/worlds/${world.world_id}/duplicate`, { method: "POST" });
            await fetchWorlds();
        } catch (err: unknown) {
            alert((err as Error).message);
        } finally {
            setDuplicatePendingWorldId(null);
        }
    };

    return (
        <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 24px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32 }}>
                <h1 style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 28, fontWeight: 700, color: "var(--text-primary)" }}>
                    <Image
                        src="/vysol-square.png"
                        alt=""
                        aria-hidden="true"
                        width={30}
                        height={30}
                        priority
                        style={{
                            width: 30,
                            height: 30,
                            objectFit: "contain",
                            transform: "translateY(-1px)",
                        }}
                    />
                    <span>VySol</span>
                </h1>
                <button
                    onClick={() => setShowSettings(true)}
                    style={{
                        background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius)",
                        padding: "8px 12px", cursor: "pointer", color: "var(--text-subtle)", transition: "color 0.2s",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text-primary)")}
                    onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-subtle)")}
                >
                    <Settings size={18} />
                </button>
            </div>

            {loading ? (
                <div style={{ display: "flex", justifyContent: "center", padding: 80 }}>
                    <Loader2 size={32} style={{ animation: "spin 1s linear infinite", color: "var(--primary)" }} />
                </div>
            ) : loadError ? (
                <div
                    style={{
                        display: "grid",
                        gap: 16,
                        background: "var(--card)",
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius)",
                        padding: 24,
                        boxShadow: "0 12px 26px color-mix(in srgb, var(--shadow-color) 55%, transparent)",
                    }}
                >
                    <div style={{ display: "grid", gap: 6 }}>
                        <h2 style={{ fontSize: 20, fontWeight: 600, color: "var(--text-primary)" }}>
                            Could not load worlds
                        </h2>
                        <p style={{ fontSize: 14, lineHeight: 1.5, color: "var(--text-subtle)", margin: 0 }}>
                            {loadError}
                        </p>
                        <p style={{ fontSize: 13, lineHeight: 1.5, color: "var(--text-muted)", margin: 0 }}>
                            Your saved worlds may still exist on disk, but the app cannot confirm that until the backend responds.
                        </p>
                    </div>
                    <div>
                        <button
                            onClick={() => {
                                setLoading(true);
                                void fetchWorlds();
                            }}
                            style={{
                                border: "1px solid var(--border)",
                                borderRadius: "var(--radius)",
                                background: "var(--background-secondary)",
                                color: "var(--text-primary)",
                                padding: "10px 14px",
                                cursor: "pointer",
                                fontWeight: 600,
                            }}
                        >
                            Retry
                        </button>
                    </div>
                </div>
            ) : (
                <div style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
                    gap: 16,
                }}>
                    {worlds.map((w) => (
                        <WorldCard
                            key={w.world_id}
                            world={w}
                            onRefresh={fetchWorlds}
                            onDuplicate={handleDuplicateWorld}
                            duplicatePending={duplicatePendingWorldId === w.world_id}
                        />
                    ))}

                    <div
                        onClick={() => setShowCreate(true)}
                        style={{
                            border: "2px dashed var(--border)",
                            borderRadius: "var(--radius)",
                            padding: 20,
                            cursor: "pointer",
                            display: "flex",
                            flexDirection: "column",
                            alignItems: "center",
                            justifyContent: "center",
                            minHeight: 140,
                            transition: "border-color 0.2s",
                            color: "var(--text-subtle)",
                            background: "var(--background-secondary)",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "var(--primary)"; (e.currentTarget as HTMLElement).style.color = "var(--primary-light)"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = "var(--border)"; (e.currentTarget as HTMLElement).style.color = "var(--text-subtle)"; }}
                    >
                        <Plus size={32} />
                        <span style={{ marginTop: 8, fontWeight: 500 }}>Create World</span>
                    </div>
                </div>
            )}

            {showCreate && (
                <CreateWorldModal
                    onClose={() => setShowCreate(false)}
                    onCreated={() => { setShowCreate(false); fetchWorlds(); }}
                />
            )}

            {showSettings && (
                <SettingsSidebar onClose={() => setShowSettings(false)} />
            )}
        </div>
    );
}
