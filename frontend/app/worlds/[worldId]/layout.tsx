"use client";

import { useState, useEffect, use, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, Upload, GitBranch, ChevronLeft, ChevronRight, Pencil } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface WorldMeta {
    world_id: string;
    world_name: string;
    ingestion_status: string;
}

const NAV_ITEMS = [
    { href: "chat", label: "Chat", icon: MessageSquare },
    { href: "ingest", label: "Ingest", icon: Upload },
    { href: "graph", label: "Graph", icon: GitBranch },
];

export default function WorldLayout({
    children,
    params,
}: {
    children: React.ReactNode;
    params: Promise<{ worldId: string }>;
}) {
    const { worldId } = use(params);
    const pathname = usePathname();
    const [collapsed, setCollapsed] = useState(() => {
        if (typeof window === "undefined") return false;
        return window.localStorage.getItem("sidebar-collapsed") === "true";
    });
    const [world, setWorld] = useState<WorldMeta | null>(null);
    const [editing, setEditing] = useState(false);
    const [editName, setEditName] = useState("");

    const loadWorld = useCallback(async () => {
        try {
            const data = await apiFetch<WorldMeta>(`/worlds/${worldId}/header`);
            setWorld(data);
            setEditName(data.world_name);
        } catch { /* ignore */ }
    }, [worldId]);

    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        void loadWorld();
    }, [loadWorld]);
    /* eslint-enable react-hooks/set-state-in-effect */

    const toggleCollapse = () => {
        const next = !collapsed;
        setCollapsed(next);
        localStorage.setItem("sidebar-collapsed", String(next));
    };

    const handleRename = async () => {
        if (!editName.trim() || !world) return;
        await apiFetch(`/worlds/${worldId}`, {
            method: "PATCH",
            body: JSON.stringify({ world_name: editName }),
        });
        setWorld({ ...world, world_name: editName });
        setEditing(false);
    };

    return (
        <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
            {/* Sidebar */}
            <div
                style={{
                    width: collapsed ? 56 : 240,
                    borderRight: "1px solid var(--border)",
                    background: "var(--card)",
                    display: "flex",
                    flexDirection: "column",
                    transition: "width 0.2s ease",
                    flexShrink: 0,
                }}
            >
                {/* World name */}
                <div style={{ padding: collapsed ? "16px 8px" : "16px", borderBottom: "1px solid var(--border)", minHeight: 56 }}>
                    {!collapsed && world && (
                        editing ? (
                            <input
                                autoFocus
                                value={editName}
                                onChange={(e) => setEditName(e.target.value)}
                                onBlur={handleRename}
                                onKeyDown={(e) => e.key === "Enter" && handleRename()}
                                style={{ width: "100%", fontSize: 15, fontWeight: 600 }}
                            />
                        ) : (
                            <div
                                onClick={() => setEditing(true)}
                                style={{ fontSize: 15, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}
                            >
                                {world.world_name}
                                <Pencil size={12} style={{ color: "var(--text-muted)", opacity: 0.5 }} />
                            </div>
                        )
                    )}
                </div>

                {/* Nav links */}
                <nav style={{ flex: 1, padding: "8px" }}>
                    {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
                        const isActive = pathname.includes(`/${href}`);
                        return (
                            <Link
                                key={href}
                                href={`/worlds/${worldId}/${href}`}
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 10,
                                    padding: collapsed ? "10px 8px" : "10px 12px",
                                    borderRadius: 8,
                                    marginBottom: 4,
                                    textDecoration: "none",
                                    color: isActive ? "var(--primary-light)" : "var(--text-subtle)",
                                    background: isActive ? "var(--primary-soft)" : "transparent",
                                    fontWeight: isActive ? 600 : 400,
                                    fontSize: 14,
                                    transition: "all 0.15s",
                                    justifyContent: collapsed ? "center" : "flex-start",
                                }}
                            >
                                <Icon size={18} />
                                {!collapsed && label}
                            </Link>
                        );
                    })}
                </nav>

                {/* Bottom */}
                <div style={{ padding: 8, borderTop: "1px solid var(--border)" }}>
                    <Link
                        href="/"
                        style={{
                            display: "flex", alignItems: "center", gap: 8, padding: "10px 12px",
                            color: "var(--text-subtle)", textDecoration: "none", fontSize: 13,
                            justifyContent: collapsed ? "center" : "flex-start",
                        }}
                    >
                        <ChevronLeft size={16} />
                        {!collapsed && "All Worlds"}
                    </Link>
                    <button
                        onClick={toggleCollapse}
                        style={{
                            width: "100%", display: "flex", justifyContent: "center", padding: 8,
                            background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer",
                        }}
                    >
                        {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                    </button>
                </div>
            </div>

            {/* Main content */}
            <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
                {children}
            </div>
        </div>
    );
}
