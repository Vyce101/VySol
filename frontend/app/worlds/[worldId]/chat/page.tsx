"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable react-hooks/set-state-in-effect */

import { Children, cloneElement, isValidElement, memo, useState, useEffect, useRef, use, useMemo } from "react";
import { Send, Loader2, ChevronRight, ChevronLeft, AlertTriangle, Trash2, Info, MessageSquare, Plus, MoreVertical, Edit2, RefreshCw, X, Check } from "lucide-react";
import { ApiError, apiFetch, apiStreamPost } from "@/lib/api";
import * as Accordion from "@radix-ui/react-accordion";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import InteractiveGraphViewer, {
    GraphViewerNode,
    GraphViewerLink,
    GraphViewerNodeDetail,
} from "@/components/interactive-graph-viewer";

interface Message {
    role: "user" | "model";
    content: string;
    localKey: string;
    thoughtText?: string;
    geminiParts?: Array<Record<string, unknown>>;
    messageId?: string;
    status?: "streaming" | "complete" | "incomplete";
    nodesUsed?: Array<{ id: string; display_name: string; entity_type: string }>;
    contextPayload?: any;
    contextMeta?: any;
}

interface ChatThread {
    id: string;
    title: string;
    updated_at: string;
    version: number;
}

interface ContextModalData {
    payload: any;
    meta?: any;
}

interface ContextGraphSnapshot {
    schema_version: string;
    nodes: GraphViewerNode[];
    edges: GraphViewerLink[];
}

interface ChatDetailResponse {
    messages?: any[];
    version?: number;
}

interface ChatThreadState {
    messages: Message[];
    version: number | null;
    streaming: boolean;
    loadRequestId: number;
    streamRequestId: number;
}

function parseBooleanSetting(value: unknown): boolean {
    if (typeof value === "boolean") return value;
    if (typeof value === "string") {
        const normalized = value.trim().toLowerCase();
        if (["true", "1", "yes", "on"].includes(normalized)) return true;
        if (["false", "0", "no", "off", ""].includes(normalized)) return false;
    }
    if (typeof value === "number") return value !== 0;
    return Boolean(value);
}

function getContextCopyText(payload: any): string {
    if (typeof payload === "string") return payload;
    if (payload === null || payload === undefined) return "";
    const serialized = JSON.stringify(payload, null, 2);
    return serialized ?? "";
}

function stringifyContextValue(value: any): string {
    if (typeof value === "string") return value;
    if (value === null || value === undefined) return "";
    const serialized = JSON.stringify(value, null, 2);
    return serialized ?? String(value);
}

function renderContextSection(title: string, content: string, key: string): React.ReactNode {
    return (
        <div key={key} style={{ marginBottom: 18 }}>
            <div style={{ fontWeight: 700, color: "var(--primary)", textTransform: "uppercase", fontSize: 12, marginBottom: 8, letterSpacing: "0.05em", borderBottom: "1px solid var(--border)", paddingBottom: 4 }}>
                {title}
            </div>
            <pre style={{ margin: 0, fontFamily: "monospace", fontSize: 13, color: "var(--text-primary)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {content}
            </pre>
        </div>
    );
}

function renderHumanContextPayload(payload: any): React.ReactNode {
    if (payload === null || payload === undefined) {
        return (
            <pre style={{ margin: 0, fontFamily: "monospace", fontSize: 13, color: "var(--text-primary)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                (no context payload)
            </pre>
        );
    }

    if (typeof payload === "string") {
        return (
            <pre style={{ margin: 0, fontFamily: "monospace", fontSize: 13, color: "var(--text-primary)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {payload}
            </pre>
        );
    }

    if (Array.isArray(payload)) {
        return payload.map((msg, idx) => renderContextSection(`Role: ${msg?.role || "UNKNOWN"}`, stringifyContextValue(msg?.content), `legacy-${idx}`));
    }

    if (typeof payload === "object" && Array.isArray(payload.messages)) {
        return payload.messages.map((msg: any, idx: number) => renderContextSection(`Role: ${msg?.role || "UNKNOWN"}`, stringifyContextValue(msg?.content), `message-${idx}`));
    }

    if (typeof payload === "object" && typeof payload.system_instruction === "string" && Array.isArray(payload.contents)) {
        const sections: React.ReactNode[] = [];
        sections.push(renderContextSection("System Instruction", payload.system_instruction, "system"));
        payload.contents.forEach((entry: any, entryIdx: number) => {
            const role = entry?.role || "UNKNOWN";
            const parts = Array.isArray(entry?.parts) ? entry.parts : [];
            const joinedParts = parts.map((part: any, partIdx: number) => {
                const renderedPart = stringifyContextValue(part);
                return `[Part ${partIdx + 1}]\n${renderedPart}`;
            }).join("\n\n");
            sections.push(renderContextSection(`Role: ${role}`, joinedParts, `content-${entryIdx}`));
        });
        return sections;
    }

    return (
        <pre style={{ margin: 0, fontFamily: "monospace", fontSize: 13, color: "var(--text-primary)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {getContextCopyText(payload)}
        </pre>
    );
}

function getContextGraphSnapshot(meta: any): ContextGraphSnapshot | null {
    const snapshot = meta?.visualization?.context_graph;
    if (!snapshot || !Array.isArray(snapshot.nodes) || !Array.isArray(snapshot.edges)) {
        return null;
    }
    return snapshot as ContextGraphSnapshot;
}

const DIALOGUE_PATTERN = /\u201C[^\u201D\n]+\u201D|"[^"\n]+"/g;

function highlightDialogueText(text: string, keyPrefix: string): React.ReactNode {
    DIALOGUE_PATTERN.lastIndex = 0;
    if (!DIALOGUE_PATTERN.test(text)) {
        return text;
    }

    DIALOGUE_PATTERN.lastIndex = 0;
    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let matchIndex = 0;

    for (const match of text.matchAll(DIALOGUE_PATTERN)) {
        const matchedText = match[0];
        const startIndex = match.index ?? 0;

        if (startIndex > lastIndex) {
            parts.push(text.slice(lastIndex, startIndex));
        }

        parts.push(
            <span key={`${keyPrefix}-dialogue-${matchIndex}`} className="chat-dialogue">
                {matchedText}
            </span>
        );

        lastIndex = startIndex + matchedText.length;
        matchIndex += 1;
    }

    if (lastIndex < text.length) {
        parts.push(text.slice(lastIndex));
    }

    return parts;
}

function highlightDialogueNode(node: React.ReactNode, keyPrefix = "dialogue"): React.ReactNode {
    if (typeof node === "string") {
        return highlightDialogueText(node, keyPrefix);
    }

    if (Array.isArray(node)) {
        return node.map((child, index) => highlightDialogueNode(child, `${keyPrefix}-${index}`));
    }

    if (!isValidElement<{ children?: React.ReactNode }>(node)) {
        return node;
    }

    if (typeof node.type === "string" && (node.type === "code" || node.type === "pre")) {
        return node;
    }

    const childCount = Children.count(node.props.children);
    if (childCount === 0) {
        return node;
    }

    const highlightedChildren = Children.map(node.props.children, (child, index) =>
        highlightDialogueNode(child, `${keyPrefix}-${index}`)
    );

    return cloneElement(node, node.props, highlightedChildren);
}

const markdownComponents = {
    p: ({ children, ...props }: any) => <p {...props}>{highlightDialogueNode(children, "p")}</p>,
    li: ({ children, ...props }: any) => <li {...props}>{highlightDialogueNode(children, "li")}</li>,
    em: ({ children, ...props }: any) => <em {...props}>{highlightDialogueNode(children, "em")}</em>,
    strong: ({ children, ...props }: any) => <strong {...props}>{highlightDialogueNode(children, "strong")}</strong>,
    blockquote: ({ children, ...props }: any) => <blockquote {...props}>{highlightDialogueNode(children, "blockquote")}</blockquote>,
    a: ({ children, ...props }: any) => <a {...props}>{highlightDialogueNode(children, "link")}</a>,
    h1: ({ children, ...props }: any) => <h1 {...props}>{highlightDialogueNode(children, "h1")}</h1>,
    h2: ({ children, ...props }: any) => <h2 {...props}>{highlightDialogueNode(children, "h2")}</h2>,
    h3: ({ children, ...props }: any) => <h3 {...props}>{highlightDialogueNode(children, "h3")}</h3>,
    h4: ({ children, ...props }: any) => <h4 {...props}>{highlightDialogueNode(children, "h4")}</h4>,
    h5: ({ children, ...props }: any) => <h5 {...props}>{highlightDialogueNode(children, "h5")}</h5>,
    h6: ({ children, ...props }: any) => <h6 {...props}>{highlightDialogueNode(children, "h6")}</h6>,
    th: ({ children, ...props }: any) => <th {...props}>{highlightDialogueNode(children, "th")}</th>,
    td: ({ children, ...props }: any) => <td {...props}>{highlightDialogueNode(children, "td")}</td>,
    table: ({ children, ...props }: any) => (
        <div className="markdown-table-wrap">
            <table {...props}>{children}</table>
        </div>
    ),
    pre: ({ children, className, ...props }: any) => (
        <pre {...props} className={["markdown-pre", className].filter(Boolean).join(" ")}>
            {children}
        </pre>
    ),
    code: ({ inline, className, children, ...props }: any) => (
        <code
            {...props}
            className={[
                inline ? "markdown-inline-code" : "markdown-code-block",
                className,
            ].filter(Boolean).join(" ")}
        >
            {children}
        </code>
    ),
};

const ChatMessageMarkdown = memo(function ChatMessageMarkdown({ content }: { content: string }) {
    return (
        <ReactMarkdown
            components={markdownComponents}
            remarkPlugins={[remarkGfm, remarkBreaks]}
            skipHtml
        >
            {content}
        </ReactMarkdown>
    );
});

interface ChatMessageBubbleProps {
    msg: Message;
    index: number;
    thoughtExpanded: boolean;
    isHovered: boolean;
    isMenuOpen: boolean;
    isEditing: boolean;
    editContent?: string;
    editBubbleHeight?: number;
    showStreamingCursor: boolean;
    onHoverChange: (index: number | null) => void;
    onToggleMenu: (index: number) => void;
    onStartEditing: (index: number, content: string) => void;
    onEditContentChange: (value: string) => void;
    onCancelEditing: () => void;
    onSaveEdit: (index: number) => void;
    onRegenerate: (index: number) => void;
    onDelete: (index: number) => void;
    onThoughtExpandedChange: (messageKey: string, expanded: boolean) => void;
    onOpenContext: (payload: any, meta?: any) => void;
    onMessageBubbleRef: (index: number, element: HTMLDivElement | null) => void;
}

const ChatMessageBubble = memo(function ChatMessageBubble({
    msg,
    index,
    thoughtExpanded,
    isHovered,
    isMenuOpen,
    isEditing,
    editContent,
    editBubbleHeight,
    showStreamingCursor,
    onHoverChange,
    onToggleMenu,
    onStartEditing,
    onEditContentChange,
    onCancelEditing,
    onSaveEdit,
    onRegenerate,
    onDelete,
    onThoughtExpandedChange,
    onOpenContext,
    onMessageBubbleRef,
}: ChatMessageBubbleProps) {
    return (
        <div
            style={{
                display: "flex",
                width: "100%",
                marginBottom: 16,
                position: "relative",
                padding: "0 20px",
            }}
            onMouseEnter={() => onHoverChange(index)}
            onMouseLeave={() => onHoverChange(null)}
        >
            <div
                style={{
                    width: "100%",
                    maxWidth: "100%",
                    display: "flex",
                    flexDirection: msg.role === "user" ? "row-reverse" : "row",
                    alignItems: "flex-start",
                    gap: 0,
                }}
            >
                {isEditing ? (
                    <div
                        style={{
                            position: "relative",
                            padding: "16px 40px",
                            borderRadius: "var(--radius)",
                            background: msg.role === "user" ? "var(--primary)" : "var(--card)",
                            border: msg.role === "model" ? "1px solid var(--border)" : "none",
                            color: msg.role === "user" ? "white" : "var(--text-primary)",
                            fontSize: 14,
                            lineHeight: 1.6,
                            width: "100%",
                            height: editBubbleHeight ?? 140,
                        }}
                    >
                        <textarea
                            value={editContent ?? ""}
                            onChange={(e) => onEditContentChange(e.target.value)}
                            style={{
                                width: "100%",
                                height: "100%",
                                resize: "none",
                                background: "transparent",
                                border: msg.role === "user" ? "1px solid rgba(255,255,255,0.35)" : "1px solid var(--border)",
                                padding: "8px 10px 46px 10px",
                                color: msg.role === "user" ? "white" : "var(--text-primary)",
                                borderRadius: 4,
                                fontFamily: "inherit",
                                lineHeight: 1.6,
                            }}
                        />
                        <div style={{ position: "absolute", right: 48, bottom: 10, display: "flex", justifyContent: "flex-end", gap: 8 }}>
                            <button onClick={onCancelEditing} style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 8px", background: "transparent", border: "1px solid var(--border)", borderRadius: 4, color: "var(--text-subtle)", cursor: "pointer", fontSize: 12 }}>
                                <X size={12} /> Cancel
                            </button>
                            <button onClick={() => onSaveEdit(index)} style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 8px", background: "var(--primary)", border: "none", borderRadius: 4, color: "var(--primary-contrast)", cursor: "pointer", fontSize: 12 }}>
                                <Check size={12} /> Save
                            </button>
                        </div>
                    </div>
                ) : (
                    <div
                        style={{
                            position: "relative",
                            padding: "16px 40px",
                            borderRadius: "var(--radius)",
                            background: msg.role === "user" ? "var(--primary)" : "var(--card)",
                            border: msg.role === "model" ? "1px solid var(--border)" : "none",
                            color: msg.role === "user" ? "white" : "var(--text-primary)",
                            fontSize: 14,
                            lineHeight: 1.6,
                            width: "100%",
                        }}
                        ref={(element) => onMessageBubbleRef(index, element)}
                    >
                        {(isHovered || isMenuOpen) && (
                            <div
                                style={{
                                    position: "absolute",
                                    top: 12,
                                    [msg.role === "user" ? "right" : "left"]: 12,
                                    zIndex: isMenuOpen ? 50 : 10,
                                }}
                            >
                                <button
                                    onClick={() => onToggleMenu(index)}
                                    style={{
                                        background: "transparent",
                                        border: "none",
                                        color: msg.role === "user" ? "rgba(255,255,255,0.7)" : "var(--text-muted)",
                                        cursor: "pointer",
                                        padding: 4,
                                        borderRadius: 4,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                    }}
                                    title="Message options"
                                >
                                    <MoreVertical size={16} />
                                </button>

                                {isMenuOpen && (
                                    <div
                                        style={{
                                            position: "absolute",
                                            top: 24,
                                            [msg.role === "user" ? "right" : "left"]: 0,
                                            background: "var(--card)",
                                            border: "1px solid var(--border)",
                                            borderRadius: 6,
                                            boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                                            zIndex: 50,
                                            padding: 4,
                                            minWidth: 120,
                                            display: "flex",
                                            flexDirection: "column",
                                            gap: 2,
                                            color: "var(--text-primary)",
                                        }}
                                    >
                                        <ActionMenuItem icon={<Edit2 size={13} />} label="Edit" onClick={() => onStartEditing(index, msg.content)} />
                                        <ActionMenuItem icon={<RefreshCw size={13} />} label={msg.status === "incomplete" ? "Continue" : "Regenerate"} onClick={() => onRegenerate(index)} />
                                        {msg.contextPayload && (
                                            <ActionMenuItem icon={<Info size={13} />} label="Context" onClick={() => onOpenContext(msg.contextPayload, msg.contextMeta)} />
                                        )}
                                        <div style={{ height: 1, background: "var(--border)", margin: "4px 0" }} />
                                        <ActionMenuItem icon={<Trash2 size={13} />} label="Delete" onClick={() => onDelete(index)} danger />
                                    </div>
                                )}
                            </div>
                        )}

                        <div
                            style={{ overflowWrap: "break-word" }}
                            className={`markdown-content ${msg.role === "user" ? "markdown-content-user" : "markdown-content-model"}`}
                        >
                            {msg.role === "model" && msg.thoughtText && (
                                <div
                                    style={{
                                        marginBottom: 12,
                                        paddingLeft: 12,
                                        borderLeft: "2px solid var(--border)",
                                        color: "var(--text-muted)",
                                    }}
                                >
                                    <button
                                        type="button"
                                        onClick={() => onThoughtExpandedChange(msg.localKey, !thoughtExpanded)}
                                        style={{
                                            display: "inline-flex",
                                            alignItems: "center",
                                            gap: 6,
                                            padding: 0,
                                            background: "transparent",
                                            border: "none",
                                            cursor: "pointer",
                                            fontSize: 12,
                                            fontWeight: 600,
                                            color: "var(--text-subtle)",
                                        }}
                                    >
                                        <ChevronRight size={14} style={{ transform: thoughtExpanded ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.2s ease" }} />
                                        <span>Model Thinking</span>
                                    </button>
                                    {thoughtExpanded && (
                                        <div style={{ marginTop: 10 }}>
                                        <ChatMessageMarkdown content={msg.thoughtText} />
                                        </div>
                                    )}
                                </div>
                            )}
                            {(msg.role === "model" || msg.role === "user") ? (
                                <ChatMessageMarkdown content={msg.content} />
                            ) : (
                                msg.content
                            )}
                        </div>

                        {msg.role === "model" && msg.status === "incomplete" && (
                            <div style={{ marginTop: 10, fontSize: 12, color: "var(--status-progress-fg)", display: "flex", alignItems: "center", gap: 6 }}>
                                <AlertTriangle size={12} /> Interrupted reply. Use Continue to retry from the last user turn.
                            </div>
                        )}

                        {showStreamingCursor && (
                            <span style={{ display: "inline-block", width: 6, height: 16, background: "var(--primary)", marginLeft: 2, animation: "pulse-glow 1s infinite" }} />
                        )}

                        {msg.nodesUsed && msg.nodesUsed.length > 0 && (
                            <details style={{ marginTop: 8, fontSize: 12, color: "var(--text-subtle)" }}>
                                <summary style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>
                                    <Info size={12} /> {msg.nodesUsed.length} nodes used
                                </summary>
                                <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
                                    {msg.nodesUsed.map((n, j) => (
                                        <span
                                            key={j}
                                            style={{
                                                padding: "2px 8px",
                                                borderRadius: 9999,
                                                background: "var(--background)",
                                                border: "1px solid var(--border)",
                                                fontSize: 11,
                                                color: "var(--text-primary)",
                                            }}
                                        >
                                            {n.display_name}
                                        </span>
                                    ))}
                                </div>
                            </details>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}, (prev, next) => (
    prev.msg === next.msg
    && prev.index === next.index
    && prev.thoughtExpanded === next.thoughtExpanded
    && prev.isHovered === next.isHovered
    && prev.isMenuOpen === next.isMenuOpen
    && prev.isEditing === next.isEditing
    && prev.editContent === next.editContent
    && prev.editBubbleHeight === next.editBubbleHeight
    && prev.showStreamingCursor === next.showStreamingCursor
));

interface ChatMessageListProps {
    messages: Message[];
    hoveredMsgIndex: number | null;
    menuOpenIndex: number | null;
    editingIndex: number | null;
    editContent: string;
    editBubbleHeight: number;
    streaming: boolean;
    messagesEndRef: React.RefObject<HTMLDivElement | null>;
    expandedThoughtBlocks: Record<string, boolean>;
    onHoverChange: (index: number | null) => void;
    onToggleMenu: (index: number) => void;
    onStartEditing: (index: number, content: string) => void;
    onEditContentChange: (value: string) => void;
    onCancelEditing: () => void;
    onSaveEdit: (index: number) => void;
    onRegenerate: (index: number) => void;
    onDelete: (index: number) => void;
    onThoughtExpandedChange: (messageKey: string, expanded: boolean) => void;
    onOpenContext: (payload: any, meta?: any) => void;
    onMessageBubbleRef: (index: number, element: HTMLDivElement | null) => void;
}

const ChatMessageList = memo(function ChatMessageList({
    messages,
    hoveredMsgIndex,
    menuOpenIndex,
    editingIndex,
    editContent,
    editBubbleHeight,
    streaming,
    messagesEndRef,
    expandedThoughtBlocks,
    onHoverChange,
    onToggleMenu,
    onStartEditing,
    onEditContentChange,
    onCancelEditing,
    onSaveEdit,
    onRegenerate,
    onDelete,
    onThoughtExpandedChange,
    onOpenContext,
    onMessageBubbleRef,
}: ChatMessageListProps) {
    if (messages.length === 0) {
        return (
            <>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)" }}>
                    <MessageSquare size={48} style={{ marginBottom: 12, opacity: 0.3 }} />
                    <p>Ask a question about your world</p>
                    <p style={{ fontSize: 13 }}>Press Ctrl+Enter to send</p>
                </div>
                <div ref={messagesEndRef} />
            </>
        );
    }

    return (
        <>
            {messages.map((msg, index) => {
                const isEditing = editingIndex === index;
                return (
                    <ChatMessageBubble
                        key={msg.localKey}
                        msg={msg}
                        index={index}
                        thoughtExpanded={Boolean(expandedThoughtBlocks[msg.localKey])}
                        isHovered={hoveredMsgIndex === index}
                        isMenuOpen={menuOpenIndex === index}
                        isEditing={isEditing}
                        editContent={isEditing ? editContent : undefined}
                        editBubbleHeight={isEditing ? editBubbleHeight : undefined}
                        showStreamingCursor={msg.role === "model" && (msg.status === "streaming" || (streaming && index === messages.length - 1))}
                        onHoverChange={onHoverChange}
                        onToggleMenu={onToggleMenu}
                        onStartEditing={onStartEditing}
                        onEditContentChange={onEditContentChange}
                        onCancelEditing={onCancelEditing}
                        onSaveEdit={onSaveEdit}
                        onRegenerate={onRegenerate}
                        onDelete={onDelete}
                        onThoughtExpandedChange={onThoughtExpandedChange}
                        onOpenContext={onOpenContext}
                        onMessageBubbleRef={onMessageBubbleRef}
                    />
                );
            })}
            <div ref={messagesEndRef} />
        </>
    );
}, (prev, next) => (
    prev.messages === next.messages
    && prev.hoveredMsgIndex === next.hoveredMsgIndex
    && prev.menuOpenIndex === next.menuOpenIndex
    && prev.editingIndex === next.editingIndex
    && prev.editContent === next.editContent
    && prev.editBubbleHeight === next.editBubbleHeight
    && prev.streaming === next.streaming
    && prev.expandedThoughtBlocks === next.expandedThoughtBlocks
));

interface ChatComposerProps {
    draftKey: string;
    streaming: boolean;
    onSend: (draft: string) => Promise<boolean>;
}

function ChatComposer({ draftKey, streaming, onSend }: ChatComposerProps) {
    const [draft, setDraft] = useState("");
    const textareaRef = useRef<HTMLTextAreaElement | null>(null);

    useEffect(() => {
        setDraft("");
        if (textareaRef.current) {
            textareaRef.current.style.height = "auto";
        }
    }, [draftKey]);

    const handleComposerSend = async () => {
        if (streaming || !draft.trim()) return;
        const sent = await onSend(draft);
        if (!sent) return;
        setDraft("");
        if (textareaRef.current) {
            textareaRef.current.style.height = "auto";
        }
    };

    return (
        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)", background: "var(--card)" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end", maxWidth: 900, margin: "0 auto" }}>
                <textarea
                    ref={textareaRef}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                            e.preventDefault();
                            void handleComposerSend();
                        }
                    }}
                    placeholder="Ask about your world... (Ctrl+Enter to send)"
                    rows={1}
                    style={{
                        flex: 1,
                        resize: "none",
                        maxHeight: 150,
                        padding: "10px 14px",
                        minHeight: 44,
                    }}
                    onInput={(e) => {
                        const element = e.target as HTMLTextAreaElement;
                        element.style.height = "auto";
                        element.style.height = `${Math.min(element.scrollHeight, 150)}px`;
                    }}
                />
                <button
                    onClick={() => { void handleComposerSend(); }}
                    disabled={streaming || !draft.trim()}
                    style={{
                        background: "var(--primary)",
                        color: "var(--primary-contrast)",
                        border: "none",
                        borderRadius: "var(--radius)",
                        padding: "10px 14px",
                        cursor: "pointer",
                        opacity: streaming || !draft.trim() ? 0.5 : 1,
                        transition: "opacity 0.2s",
                    }}
                >
                    {streaming ? <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> : <Send size={18} />}
                </button>
            </div>
        </div>
    );
}

type SettingsSectionId = "general" | "chunk" | "graph" | "prompt";

interface ChatSettingsSidebarProps {
    topK: number;
    entryTopK: number;
    hops: number;
    maxNodes: number;
    chatProvider: string;
    sendThinking: boolean;
    chatPrompt: string;
    promptSource: string;
    searchContextMsgs: number;
    chatHistoryMsgs: number;
    openSections: SettingsSectionId[];
    onOpenSectionsChange: React.Dispatch<React.SetStateAction<SettingsSectionId[]>>;
    onTopKChange: (value: number) => void;
    onEntryTopKChange: (value: number) => void;
    onHopsChange: (value: number) => void;
    onMaxNodesChange: (value: number) => void;
    onSendThinkingChange: (value: boolean) => void;
    onSearchContextMsgsChange: (value: number) => void;
    onChatHistoryMsgsChange: (value: number) => void;
    onChatPromptChange: (value: string) => void;
    onSaveChatPrompt: () => void;
    onResetChatPrompt: () => void;
}

function ChatSettingsSidebar({
    topK,
    entryTopK,
    hops,
    maxNodes,
    chatProvider,
    sendThinking,
    chatPrompt,
    promptSource,
    searchContextMsgs,
    chatHistoryMsgs,
    openSections,
    onOpenSectionsChange,
    onTopKChange,
    onEntryTopKChange,
    onHopsChange,
    onMaxNodesChange,
    onSendThinkingChange,
    onSearchContextMsgsChange,
    onChatHistoryMsgsChange,
    onChatPromptChange,
    onSaveChatPrompt,
    onResetChatPrompt,
}: ChatSettingsSidebarProps) {
    return (
        <div style={{
            width: 320, borderLeft: "1px solid var(--border)", background: "var(--card)",
            overflowY: "auto", padding: 20, flexShrink: 0,
        }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-subtle)" }}>
                Retrieval Settings
            </h3>

            <Accordion.Root type="multiple" value={openSections} onValueChange={(value) => onOpenSectionsChange(value as SettingsSectionId[])} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <SettingsAccordionSection value="general" title="General Settings" isOpen={openSections.includes("general")}>
                    {chatProvider === "gemini" && (
                        <div style={{ marginBottom: 14 }}>
                            <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                                <div>
                                    <div style={{ fontSize: 13, fontWeight: 500 }}>Send Thinking</div>
                                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                                        Show Gemini thought blocks in the reply when the model returns them.
                                    </div>
                                </div>
                                <input
                                    type="checkbox"
                                    checked={sendThinking}
                                    onChange={(e) => onSendThinkingChange(e.target.checked)}
                                    style={{ width: 18, height: 18, cursor: "pointer" }}
                                />
                            </label>
                        </div>
                    )}
                    <SliderField label="Vector Query (Msgs)" value={searchContextMsgs} min={1} max={10} onChange={onSearchContextMsgsChange} />
                    <SliderField label="Chat History Context (Msgs)" value={chatHistoryMsgs} min={1} max={20} onChange={onChatHistoryMsgsChange} />
                </SettingsAccordionSection>

                <SettingsAccordionSection value="chunk" title="Chunk Settings" isOpen={openSections.includes("chunk")}>
                    <SliderField label="Top K Chunks" value={topK} min={1} max={20} onChange={onTopKChange} />
                </SettingsAccordionSection>

                <SettingsAccordionSection value="graph" title="Graph Settings" isOpen={openSections.includes("graph")}>
                    <SliderField label="Entry Nodes" value={entryTopK} min={1} max={20} onChange={onEntryTopKChange} />
                    <SliderField label="Graph Hops" value={hops} min={0} max={5} onChange={onHopsChange} />
                    <SliderField label="Max Graph Nodes" value={maxNodes} min={5} max={100} onChange={onMaxNodesChange} />
                </SettingsAccordionSection>

                <SettingsAccordionSection value="prompt" title="Prompt" isOpen={openSections.includes("prompt")}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                        <span style={{ fontSize: 13, fontWeight: 500 }}>Chat System Prompt</span>
                        <span style={{
                            fontSize: 11, padding: "2px 8px", borderRadius: 9999, fontWeight: 500,
                            background: promptSource === "custom" ? "var(--primary-soft-strong)" : "var(--status-pending-bg)",
                            color: promptSource === "custom" ? "var(--primary-light)" : "var(--status-pending-fg)",
                        }}>
                            {promptSource}
                        </span>
                    </div>
                    <textarea
                        value={chatPrompt}
                        onChange={(e) => onChatPromptChange(e.target.value)}
                        rows={6}
                        style={{ width: "100%", resize: "vertical", fontSize: 12, minHeight: 100 }}
                    />
                    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                        <button onClick={onSaveChatPrompt} style={{ flex: 1, padding: "6px 12px", background: "var(--primary)", color: "var(--primary-contrast)", border: "none", borderRadius: "var(--radius)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                            Save
                        </button>
                        <button onClick={onResetChatPrompt} style={{ flex: 1, padding: "6px 12px", background: "var(--border)", color: "var(--text-subtle)", border: "none", borderRadius: "var(--radius)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                            Reset
                        </button>
                    </div>
                </SettingsAccordionSection>
            </Accordion.Root>
        </div>
    );
}

function SettingsAccordionSection({
    value,
    title,
    isOpen,
    children,
}: {
    value: SettingsSectionId;
    title: string;
    isOpen: boolean;
    children: React.ReactNode;
}) {
    return (
        <Accordion.Item value={value} style={{ border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden", background: "var(--background)" }}>
            <Accordion.Header>
                <Accordion.Trigger
                    style={{
                        width: "100%",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 12,
                        padding: "14px 16px",
                        background: "transparent",
                        border: "none",
                        color: "var(--text-primary)",
                        cursor: "pointer",
                        fontSize: 13,
                        fontWeight: 600,
                        letterSpacing: "0.04em",
                        textTransform: "uppercase",
                    }}
                >
                    <span>{title}</span>
                    <ChevronRight size={16} style={{ color: "var(--text-muted)", transform: isOpen ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.2s ease" }} />
                </Accordion.Trigger>
            </Accordion.Header>
            <Accordion.Content style={{ padding: "0 16px 16px" }}>
                <div style={{ paddingTop: 4 }}>
                    {children}
                </div>
            </Accordion.Content>
        </Accordion.Item>
    );
}

export default function ChatPage({ params }: { params: Promise<{ worldId: string }> }) {
    const { worldId } = use(params);
    const [threads, setThreads] = useState<ChatThread[]>([]);
    const [activeChatId, setActiveChatId] = useState<string | null>(null);
    const [chatStates, setChatStates] = useState<Record<string, ChatThreadState>>({});

    // UI Layout states
    const [threadsOpen, setThreadsOpen] = useState(true);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [incomplete, setIncomplete] = useState(false);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const isAutoScrollEnabled = useRef(true);
    const previousScrollTopRef = useRef(0);
    const chatStatesRef = useRef<Record<string, ChatThreadState>>({});
    const loadRequestCounterRef = useRef(0);
    const streamRequestCounterRef = useRef(0);
    const localMessageKeyCounterRef = useRef(0);
    const streamAbortControllersRef = useRef<Record<string, AbortController>>({});

    // Retrieval settings
    const [topK, setTopK] = useState(5);
    const [entryTopK, setEntryTopK] = useState(5);
    const [hops, setHops] = useState(2);
    const [maxNodes, setMaxNodes] = useState(50);
    const [chatProvider, setChatProvider] = useState("gemini");
    const [sendThinking, setSendThinking] = useState(true);
    const [chatPrompt, setChatPrompt] = useState("");
    const [promptSource, setPromptSource] = useState("default");
    const [searchContextMsgs, setSearchContextMsgs] = useState(3);
    const [chatHistoryMsgs, setChatHistoryMsgs] = useState(1000);
    const [openSections, setOpenSections] = useState<SettingsSectionId[]>([]);

    // Message action states
    const [hoveredMsgIndex, setHoveredMsgIndex] = useState<number | null>(null);
    const [menuOpenIndex, setMenuOpenIndex] = useState<number | null>(null);
    const [editingIndex, setEditingIndex] = useState<number | null>(null);
    const [editContent, setEditContent] = useState("");
    const [editBubbleHeight, setEditBubbleHeight] = useState(140);
    const [expandedThoughtBlocks, setExpandedThoughtBlocks] = useState<Record<string, boolean>>({});
    const [contextModalData, setContextModalData] = useState<ContextModalData | null>(null);
    const [contextMetaOpen, setContextMetaOpen] = useState(false);
    const [contextViewMode, setContextViewMode] = useState<"rendered" | "graph" | "json">("rendered");
    const [hoveredThreadId, setHoveredThreadId] = useState<string | null>(null);
    const [renamingChatId, setRenamingChatId] = useState<string | null>(null);
    const [renameDraft, setRenameDraft] = useState("");
    const [renamingBusyChatId, setRenamingBusyChatId] = useState<string | null>(null);

    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const messageBubbleRefs = useRef<Record<number, HTMLDivElement | null>>({});
    const renameInputRef = useRef<HTMLInputElement | null>(null);
    const renamingChatIdRef = useRef<string | null>(null);

    const createEmptyThreadState = (): ChatThreadState => ({
        messages: [],
        version: null,
        streaming: false,
        loadRequestId: 0,
        streamRequestId: 0,
    });

    const activeThreadState = activeChatId ? (chatStates[activeChatId] ?? createEmptyThreadState()) : createEmptyThreadState();
    const messages = activeThreadState.messages;
    const streaming = activeThreadState.streaming;

    const createLocalMessageKey = () => {
        localMessageKeyCounterRef.current += 1;
        return `msg-${localMessageKeyCounterRef.current}`;
    };

    const mapMessage = (m: any, fallbackKey?: string): Message => ({
        ...m,
        localKey:
            (typeof m.localKey === "string" && m.localKey)
            || (typeof m.local_key === "string" && m.local_key)
            || (typeof m.messageId === "string" && m.messageId)
            || (typeof m.message_id === "string" && m.message_id)
            || fallbackKey
            || createLocalMessageKey(),
        thoughtText: m.thoughtText || m.thought_text || "",
        geminiParts: m.geminiParts || m.gemini_parts,
        messageId: m.messageId || m.message_id,
        status: m.status || "complete",
        nodesUsed: m.nodesUsed || m.nodes_used,
        contextPayload: m.contextPayload || m.context_payload,
        contextMeta: m.contextMeta || m.context_meta,
    });

    const setThreadState = (chatId: string, updater: (current: ChatThreadState) => ChatThreadState) => {
        setChatStates((prev) => {
            const current = prev[chatId] ?? createEmptyThreadState();
            const next = updater(current);
            if (next === current) {
                return prev;
            }
            return { ...prev, [chatId]: next };
        });
    };

    const removeThreadState = (chatId: string) => {
        setChatStates((prev) => {
            if (!(chatId in prev)) {
                return prev;
            }
            const next = { ...prev };
            delete next[chatId];
            return next;
        });
    };

    const setThoughtExpandedState = (messageKey: string, expanded: boolean) => {
        setExpandedThoughtBlocks((prev) => {
            if (expanded) {
                if (prev[messageKey]) {
                    return prev;
                }
                return { ...prev, [messageKey]: true };
            }

            if (!prev[messageKey]) {
                return prev;
            }
            const next = { ...prev };
            delete next[messageKey];
            return next;
        });
    };

    const abortChatStream = (chatId: string) => {
        const controller = streamAbortControllersRef.current[chatId];
        if (controller) {
            controller.abort();
            delete streamAbortControllersRef.current[chatId];
        }
    };

    const abortAllChatStreams = () => {
        Object.keys(streamAbortControllersRef.current).forEach((chatId) => abortChatStream(chatId));
    };

    async function loadRetrievalSettings() {
        try {
            const data = await apiFetch<any>("/settings");
            if (data.retrieval_top_k_chunks !== undefined) setTopK(data.retrieval_top_k_chunks);
            if (data.retrieval_entry_top_k_nodes !== undefined) {
                setEntryTopK(data.retrieval_entry_top_k_nodes);
            } else if (data.retrieval_entry_top_k_chunks !== undefined) {
                setEntryTopK(data.retrieval_entry_top_k_chunks);
            } else if (data.retrieval_top_k_chunks !== undefined) {
                setEntryTopK(data.retrieval_top_k_chunks);
            }
            if (data.retrieval_graph_hops !== undefined) setHops(data.retrieval_graph_hops);
            if (data.retrieval_max_nodes !== undefined) setMaxNodes(data.retrieval_max_nodes);
            if (data.chat_provider !== undefined) setChatProvider(data.chat_provider || "gemini");
            if (data.gemini_chat_send_thinking !== undefined) setSendThinking(parseBooleanSetting(data.gemini_chat_send_thinking));
            if (data.retrieval_context_messages !== undefined) setSearchContextMsgs(data.retrieval_context_messages);
            if (data.chat_history_messages !== undefined) setChatHistoryMsgs(data.chat_history_messages);
        } catch { /* ignore */ }
    };

    useEffect(() => {
        chatStatesRef.current = chatStates;
    }, [chatStates]);

    useEffect(() => {
        renamingChatIdRef.current = renamingChatId;
    }, [renamingChatId]);

    useEffect(() => {
        if (isAutoScrollEnabled.current) {
            messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
        }
    }, [messages]);

    useEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;
        previousScrollTopRef.current = container.scrollTop;
    }, [activeChatId]);

    useEffect(() => {
        if (!contextModalData) {
            setContextMetaOpen(false);
            setContextViewMode("rendered");
        }
    }, [contextModalData]);

    useEffect(() => {
        if (renamingChatId && renameInputRef.current) {
            renameInputRef.current.focus();
            renameInputRef.current.select();
        }
    }, [renamingChatId]);

    const handleScroll = () => {
        const container = scrollContainerRef.current;
        if (!container) return;
        const { scrollTop, scrollHeight, clientHeight } = container;
        const previousScrollTop = previousScrollTopRef.current;
        const bottomDistance = scrollHeight - scrollTop - clientHeight;
        const isAtBottom = bottomDistance <= 2;

        if (scrollTop < previousScrollTop) {
            isAutoScrollEnabled.current = false;
        } else if (isAtBottom) {
            isAutoScrollEnabled.current = true;
        }

        previousScrollTopRef.current = scrollTop;
    };

    async function checkIngestionStatus() {
        try {
            const data = await apiFetch<{ ingestion_status: string }>(`/worlds/${worldId}`);
            setIncomplete(data.ingestion_status !== "complete");
        } catch { /* ignore */ }
    };

    async function loadChatPrompt() {
        try {
            const prompts = await apiFetch<Record<string, { value: string; source: string }>>("/settings/prompts");
            if (prompts.chat_system_prompt) {
                setChatPrompt(prompts.chat_system_prompt.value);
                setPromptSource(prompts.chat_system_prompt.source);
            }
        } catch { /* ignore */ }
    };

    async function loadThreads() {
        try {
            const data = await apiFetch<ChatThread[]>(`/worlds/${worldId}/chats`);
            const deduped: ChatThread[] = [];
            const seen = new Set<string>();
            for (const thread of data) {
                if (!thread?.id || seen.has(thread.id)) continue;
                seen.add(thread.id);
                deduped.push(thread);
            }
            setThreads(deduped);
            setActiveChatId((prev) => {
                if (prev && deduped.some((thread) => thread.id === prev)) {
                    return prev;
                }
                return deduped[0]?.id ?? null;
            });
        } catch { /* ignore */ }
    }

    async function loadChatDetails(chatId: string) {
        const requestId = ++loadRequestCounterRef.current;
        setThreadState(chatId, (current) => ({
            ...current,
            loadRequestId: requestId,
        }));
        try {
            const data = await apiFetch<ChatDetailResponse>(`/worlds/${worldId}/chats/${chatId}`);
            const mapped = (data.messages || []).map((message, index) => mapMessage(message, `loaded-${chatId}-${index}`));
            setThreadState(chatId, (current) => {
                if (current.loadRequestId !== requestId || current.streaming) {
                    return current;
                }
                return {
                    ...current,
                    messages: mapped,
                    version: data.version ?? 0,
                };
            });
            if (typeof data.version === "number") {
                setThreads((prev) => prev.map((thread) => (
                    thread.id === chatId
                        ? { ...thread, version: data.version ?? thread.version }
                        : thread
                )));
            }
        } catch { /* ignore */ }
    }

    // Cleanup should run when the world changes or the page unmounts, but does
    // not need to retrigger for every render-time helper identity change.
    useEffect(() => {
        return () => {
            abortAllChatStreams();
        };
    }, [worldId]); // eslint-disable-line react-hooks/exhaustive-deps

    // These loaders are scoped to the current world id and intentionally rerun
    // only when the world changes.
    useEffect(() => {
        setThreads([]);
        setActiveChatId(null);
        setChatStates({});
        abortAllChatStreams();
        checkIngestionStatus();
        loadChatPrompt();
        loadThreads();
        loadRetrievalSettings();
    }, [worldId]); // eslint-disable-line react-hooks/exhaustive-deps

    // Thread details should refresh when the active chat changes, while the
    // per-thread cache preserves the currently rendered history immediately.
    useEffect(() => {
        if (activeChatId) {
            void loadChatDetails(activeChatId);
        }
    }, [activeChatId, worldId]); // eslint-disable-line react-hooks/exhaustive-deps

    const createNewChat = async (title = "New Chat"): Promise<string | null> => {
        try {
            const data = await apiFetch<{ id: string; version?: number }>(`/worlds/${worldId}/chats`, {
                method: "POST", 
                body: JSON.stringify({ title })
            });
            setThreadState(data.id, (current) => ({
                ...current,
                messages: [],
                version: data.version ?? null,
                streaming: false,
            }));
            setActiveChatId(data.id);
            void loadThreads();
            return data.id;
        } catch { /* ignore */ }
        return null;
    };

    const deleteChat = async (chatId: string) => {
        if (!confirm("Delete this chat?")) return;
        try {
            abortChatStream(chatId);
            await apiFetch(`/worlds/${worldId}/chats/${chatId}`, { method: "DELETE" });
            removeThreadState(chatId);
            if (activeChatId === chatId) {
                setActiveChatId(null);
            }
            void loadThreads();
        } catch { /* ignore */ }
    };

    const startRenamingChat = (thread: ChatThread) => {
        setRenamingBusyChatId(null);
        setRenamingChatId(thread.id);
        setRenameDraft(thread.title);
    };

    const cancelRenamingChat = (chatId?: string) => {
        setRenamingBusyChatId((current) => (
            chatId === undefined || current === chatId ? null : current
        ));
        if (chatId === undefined || renamingChatIdRef.current === chatId) {
            setRenamingChatId(null);
            setRenameDraft("");
        }
    };

    const renameChat = async (thread: ChatThread) => {
        const nextTitle = renameDraft.trim();
        const baseVersion = activeChatId === thread.id
            ? (chatStatesRef.current[thread.id]?.version ?? thread.version)
            : thread.version;
        if (renamingBusyChatId === thread.id) return;
        if (!nextTitle || nextTitle === thread.title.trim()) {
            cancelRenamingChat(thread.id);
            return;
        }

        setRenamingBusyChatId(thread.id);
        try {
            const renamed = await apiFetch<ChatThread>(`/worlds/${worldId}/chats/${thread.id}`, {
                method: "PATCH",
                body: JSON.stringify({
                    title: nextTitle,
                    base_version: baseVersion,
                }),
            });
            setThreads((prev) => prev.map((current) => (
                current.id === thread.id
                    ? { ...current, title: renamed.title, version: renamed.version }
                    : current
            )));
            if (activeChatId === thread.id) {
                setThreadState(thread.id, (current) => ({
                    ...current,
                    version: renamed.version ?? current.version,
                }));
            }
            cancelRenamingChat(thread.id);
        } catch (err) {
            cancelRenamingChat(thread.id);
            await loadThreads();
            if (activeChatId === thread.id) {
                await loadChatDetails(thread.id);
            }
            if (err instanceof ApiError && err.status === 409) {
                alert("This chat changed in another tab. Reloaded the latest chat titles instead.");
                return;
            }
            alert("Failed to rename chat.");
        }
    };

    const saveRetrievalSettings = (updates: Record<string, unknown>) => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
            apiFetch("/settings", { method: "POST", body: JSON.stringify(updates) }).catch(() => { });
        }, 500);
    };

    const saveChatHistory = async (chatId: string, newMessages: Message[]) => {
        const baseVersion = chatStatesRef.current[chatId]?.version ?? 0;
        try {
            const data = await apiFetch<{ version?: number; messages?: any[] }>(`/worlds/${worldId}/chats/${chatId}/history`, {
                method: "PUT",
                body: JSON.stringify({
                    messages: newMessages.map((message) => ({
                        role: message.role,
                        content: message.content,
                        thought_text: message.thoughtText,
                        gemini_parts: message.geminiParts,
                        message_id: message.messageId,
                        status: message.status || "complete",
                        nodes_used: message.nodesUsed,
                        context_payload: message.contextPayload,
                        context_meta: message.contextMeta,
                    })),
                    base_version: baseVersion,
                })
            });
            setThreadState(chatId, (current) => ({
                ...current,
                version: data.version ?? current.version,
                messages: data.messages ? data.messages.map((message, index) => mapMessage(message, newMessages[index]?.localKey)) : newMessages,
                streaming: false,
            }));
            if (typeof data.version === "number") {
                setThreads((prev) => prev.map((thread) => (
                    thread.id === chatId
                        ? { ...thread, version: data.version ?? thread.version }
                        : thread
                )));
            }
            return true;
        } catch (err) {
            if (err instanceof ApiError && err.status === 409) {
                await loadChatDetails(chatId);
                alert("This chat changed in another tab. Loaded the latest saved messages instead.");
                return false;
            }
            alert("Failed to update chat history on server.");
            return false;
        }
    }

    const handleSend = async (draft: string, customHistory?: Message[]) => {
        const textToSend = draft.trim();
        if (!textToSend) return false;

        let currentChatId = activeChatId;

        if (!currentChatId) {
            const title = textToSend.slice(0, 30) + (textToSend.length > 30 ? "..." : "");
            currentChatId = await createNewChat(title);
            if (!currentChatId) {
                alert("Failed to create chat");
                return false;
            }
        }

        const currentState = chatStatesRef.current[currentChatId] ?? createEmptyThreadState();
        if (currentState.streaming) return false;

        const userMsg: Message = { localKey: createLocalMessageKey(), role: "user", content: textToSend, status: "complete" };
        const historyToUse = customHistory ?? currentState.messages;
        const newHistory = [...historyToUse, userMsg];
        const optimisticReply: Message = { localKey: createLocalMessageKey(), role: "model", content: "", thoughtText: "", geminiParts: [], status: "streaming" };
        const streamRequestId = ++streamRequestCounterRef.current;

        setThreadState(currentChatId, (current) => ({
            ...current,
            messages: [...newHistory, optimisticReply],
            streaming: true,
            streamRequestId,
        }));

        let accum = "";
        let thoughtAccum = "";
        let geminiParts: Message["geminiParts"] = [];
        let nodesUsed: Message["nodesUsed"] = [];
        let contextPayload: any = null;
        let contextMeta: any = null;
        let persistedMessageId: string | undefined;
        let persistedVersion: number | null = null;
        const controller = new AbortController();

        abortChatStream(currentChatId);
        streamAbortControllersRef.current[currentChatId] = controller;

        void apiStreamPost(
            `/worlds/${worldId}/chats/${currentChatId}/message`,
            {
                message: userMsg.content,
                settings_override: {
                    retrieval_top_k_chunks: topK,
                    retrieval_entry_top_k_nodes: entryTopK,
                    retrieval_graph_hops: hops,
                    retrieval_max_nodes: maxNodes,
                    gemini_chat_send_thinking: sendThinking,
                    retrieval_context_messages: searchContextMsgs,
                    chat_history_messages: chatHistoryMsgs,
                },
            },
            (data) => {
                if (data.token) {
                    accum += data.token as string;
                    setThreadState(currentChatId, (current) => {
                        if (current.streamRequestId !== streamRequestId || current.messages.length === 0) {
                            return current;
                        }
                        const updated = [...current.messages];
                        updated[updated.length - 1] = {
                            ...updated[updated.length - 1],
                            role: "model",
                            content: accum,
                            thoughtText: thoughtAccum,
                            status: "streaming",
                        };
                        return {
                            ...current,
                            messages: updated,
                        };
                    });
                }
                if (data.thought_token) {
                    thoughtAccum += data.thought_token as string;
                    setThreadState(currentChatId, (current) => {
                        if (current.streamRequestId !== streamRequestId || current.messages.length === 0) {
                            return current;
                        }
                        const updated = [...current.messages];
                        updated[updated.length - 1] = {
                            ...updated[updated.length - 1],
                            role: "model",
                            content: accum,
                            thoughtText: thoughtAccum,
                            status: "streaming",
                        };
                        return {
                            ...current,
                            messages: updated,
                        };
                    });
                }
                if (data.event === "done") {
                    if (typeof data.message_id === "string") persistedMessageId = data.message_id;
                    if (typeof data.chat_version === "number") persistedVersion = data.chat_version;
                    if (data.nodes_used) nodesUsed = data.nodes_used as Message["nodesUsed"];
                    if (data.context_payload) contextPayload = data.context_payload;
                    if (data.context_meta) contextMeta = data.context_meta;
                    if (typeof data.thought_text === "string") thoughtAccum = data.thought_text;
                    if (Array.isArray(data.gemini_parts)) geminiParts = data.gemini_parts as Message["geminiParts"];
                    if (typeof data.chat_version === "number") {
                        setThreadState(currentChatId, (current) => (
                            current.streamRequestId !== streamRequestId
                                ? current
                                : { ...current, version: data.chat_version as number }
                        ));
                    }
                }
            },
            () => {
                delete streamAbortControllersRef.current[currentChatId];
                setThreadState(currentChatId, (current) => {
                    if (current.streamRequestId !== streamRequestId) {
                        return current;
                    }
                    const updated = [...current.messages];
                    if (updated.length > 0) {
                        updated[updated.length - 1] = {
                            ...updated[updated.length - 1],
                            role: "model",
                            content: accum,
                            thoughtText: thoughtAccum,
                            geminiParts,
                            messageId: persistedMessageId,
                            status: "complete",
                            nodesUsed,
                            contextPayload,
                            contextMeta,
                        };
                    }
                    return {
                        ...current,
                        messages: updated,
                        version: persistedVersion ?? current.version,
                        streaming: false,
                    };
                });
                void loadThreads();
            },
            (err) => {
                delete streamAbortControllersRef.current[currentChatId];
                setThreadState(currentChatId, (current) => (
                    current.streamRequestId !== streamRequestId
                        ? current
                        : { ...current, streaming: false }
                ));
                void loadThreads();
                void loadChatDetails(currentChatId);
                alert(err.message.includes("fully saved")
                    ? "The reply was interrupted before it finished saving. The partial reply was preserved as incomplete."
                    : err.message);
            },
            { signal: controller.signal }
        );

        return true;
    };

    const deleteMessage = async (index: number) => {
        if (!confirm("Are you sure you want to delete this message?")) return;
        if (!activeChatId) return;
        const newMessages = [...messages];
        newMessages.splice(index, 1);
        setThreadState(activeChatId, (current) => ({
            ...current,
            messages: newMessages,
        }));
        setMenuOpenIndex(null);
        await saveChatHistory(activeChatId, newMessages);
    };

    const startEditing = (index: number, content: string) => {
        const bubbleEl = messageBubbleRefs.current[index];
        const measuredHeight = bubbleEl ? Math.ceil(bubbleEl.getBoundingClientRect().height) : 140;
        setEditBubbleHeight(Math.max(90, measuredHeight));
        setEditingIndex(index);
        setEditContent(content);
        setMenuOpenIndex(null);
    };

    const saveEdit = async (index: number) => {
        if (!activeChatId) return;
        const newMessages = [...messages];
        newMessages[index].content = editContent;
        if (newMessages[index].role === "model") {
            newMessages[index].thoughtText = "";
            newMessages[index].geminiParts = [];
        }
        setThreadState(activeChatId, (current) => ({
            ...current,
            messages: newMessages,
        }));
        setEditingIndex(null);
        await saveChatHistory(activeChatId, newMessages);
    };

    const regenerateMessage = async (index: number) => {
        const msg = messages[index];
        let newMessages: Message[] = [];
        let promptToResend = "";
        
        if (msg.role === "model") {
            if (index > 0 && messages[index-1].role === "user") {
                newMessages = messages.slice(0, index - 1);
                promptToResend = messages[index-1].content;
            } else {
                alert("Cannot regenerate model message without a preceding user message.");
                return;
            }
        } else {
            newMessages = messages.slice(0, index);
            promptToResend = msg.content;
        }
        
        if (activeChatId) {
            setThreadState(activeChatId, (current) => ({
                ...current,
                messages: newMessages,
            }));
        }
        setMenuOpenIndex(null);
        if (activeChatId) {
            const saved = await saveChatHistory(activeChatId, newMessages);
            if (!saved) {
                return;
            }
        }
        await handleSend(promptToResend, newMessages);
    };

    const saveChatPrompt = async () => {
        try {
            await apiFetch("/settings/prompts", { method: "POST", body: JSON.stringify({ key: "chat_system_prompt", value: chatPrompt }) });
            setPromptSource("custom");
        } catch { /* ignore */ }
    };

    const resetChatPrompt = async () => {
        try {
            const result = await apiFetch<{ default_value: string }>("/settings/prompts/reset/chat_system_prompt", { method: "POST" });
            setChatPrompt(result.default_value);
            setPromptSource("default");
        } catch { /* ignore */ }
    };

    const modalPayload = contextModalData?.payload;
    const modalMeta = contextModalData?.meta;
    const modalContextGraph = useMemo(
        () => getContextGraphSnapshot(modalMeta),
        [modalMeta]
    );

    return (
        <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
            
            {/* Left Sidebar - Chat Threads */}
            {threadsOpen && (
                <div style={{ width: 280, borderRight: "1px solid var(--border)", background: "var(--background)", display: "flex", flexDirection: "column", flexShrink: 0 }}>
                    <div style={{ padding: "16px", borderBottom: "1px solid var(--border)" }}>
                        <button onClick={() => { void createNewChat(); }} style={{
                            width: "100%", padding: "8px 16px", background: "var(--primary)", 
                            color: "var(--primary-contrast)", borderRadius: "var(--radius)", border: "none", 
                            cursor: "pointer", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 6
                        }}>
                            <Plus size={16} /> New Chat
                        </button>
                    </div>
                    <div style={{ flex: 1, overflowY: "auto", padding: "12px 12px" }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em", paddingLeft: 4 }}>
                            Recent
                        </div>
                        {threads.map(t => (
                            <div 
                                key={t.id} 
                                onClick={() => setActiveChatId(t.id)} 
                                onMouseEnter={() => setHoveredThreadId(t.id)}
                                onMouseLeave={() => setHoveredThreadId((current) => (current === t.id ? null : current))}
                                style={{ 
                                    padding: "10px 12px", 
                                    background: t.id === activeChatId ? "var(--primary-soft)" : "transparent",
                                    border: `1px solid ${t.id === activeChatId ? "var(--primary)" : "transparent"}`,
                                    cursor: "pointer", borderRadius: 8, marginBottom: 4, 
                                    display: "flex", justifyContent: "space-between", alignItems: "center",
                                    transition: "background 0.2s"
                                }}
                            >
                                <div style={{ display: "flex", alignItems: "center", gap: 8, overflow: "hidden", flex: 1 }}>
                                    <MessageSquare size={14} style={{ color: t.id === activeChatId ? "var(--primary-light)" : "var(--text-muted)", flexShrink: 0 }} />
                                    {renamingChatId === t.id ? (
                                        <input
                                            ref={renameInputRef}
                                            value={renameDraft}
                                            onClick={(e) => e.stopPropagation()}
                                            onChange={(e) => setRenameDraft(e.target.value)}
                                            onKeyDown={(e) => {
                                                e.stopPropagation();
                                                if (e.key === "Enter") {
                                                    e.preventDefault();
                                                    void renameChat(t);
                                                } else if (e.key === "Escape") {
                                                    e.preventDefault();
                                                    cancelRenamingChat();
                                                }
                                            }}
                                            onBlur={() => { void renameChat(t); }}
                                            disabled={renamingBusyChatId === t.id}
                                            style={{
                                                flex: 1,
                                                minWidth: 0,
                                                fontSize: 13,
                                                fontWeight: t.id === activeChatId ? 500 : 400,
                                                color: t.id === activeChatId ? "var(--primary-light)" : "var(--text-primary)",
                                                background: "var(--card)",
                                                border: "1px solid var(--primary)",
                                                borderRadius: 6,
                                                padding: "4px 8px",
                                                outline: "none",
                                            }}
                                        />
                                    ) : (
                                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13, fontWeight: t.id === activeChatId ? 500 : 400, color: t.id === activeChatId ? "var(--primary-light)" : "var(--text-primary)" }}>
                                            {t.title}
                                        </div>
                                    )}
                                </div>
                                {renamingChatId !== t.id && (
                                    <div style={{ display: "flex", alignItems: "center", gap: 2, visibility: hoveredThreadId === t.id || t.id === activeChatId ? "visible" : "hidden" }}>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                startRenamingChat(t);
                                            }}
                                            title="Rename chat"
                                            style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 4 }}
                                        >
                                            <Edit2 size={13} />
                                        </button>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                deleteChat(t.id);
                                            }}
                                            title="Delete chat"
                                            style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 4 }}
                                        >
                                            <Trash2 size={13} />
                                        </button>
                                    </div>
                                )}
                            </div>
                        ))}
                        {threads.length === 0 && (
                            <div style={{ padding: 16, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
                                No past chats here.
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Chat area */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative" }}>
                
                {/* Toggle Left Sidebar */}
                <button
                    onClick={() => setThreadsOpen(!threadsOpen)}
                    style={{
                        position: "absolute", left: 0, top: "20px",
                        zIndex: 10,
                        background: "var(--card)", border: "1px solid var(--border)", borderLeft: "none",
                        borderRadius: "0 8px 8px 0", padding: "8px 4px", cursor: "pointer",
                        color: "var(--text-muted)",
                    }}
                >
                    {threadsOpen ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
                </button>

                {/* Warning banner */}
                {incomplete && (
                    <div style={{
                        padding: "8px 16px", background: "#78350f22", borderBottom: "1px solid #78350f",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 8, fontSize: 13, color: "#fbbf24",
                    }}>
                        <AlertTriangle size={14} /> World not fully ingested. Answers may be incomplete.
                    </div>
                )}

                {/* Fixed Overlay for Menu Closing */}
                {menuOpenIndex !== null && (
                    <div 
                        style={{ position: "fixed", inset: 0, zIndex: 40 }} 
                        onClick={(e) => { e.stopPropagation(); setMenuOpenIndex(null); }} 
                    />
                )}

                {/* Messages */}
                <div
                    ref={scrollContainerRef}
                    onScroll={handleScroll}
                    style={{ flex: 1, overflowY: "auto", padding: "20px 0" }}
                >
                    <ChatMessageList
                        messages={messages}
                        hoveredMsgIndex={hoveredMsgIndex}
                        menuOpenIndex={menuOpenIndex}
                        editingIndex={editingIndex}
                        editContent={editContent}
                        editBubbleHeight={editBubbleHeight}
                        streaming={streaming}
                        messagesEndRef={messagesEndRef}
                        expandedThoughtBlocks={expandedThoughtBlocks}
                        onHoverChange={setHoveredMsgIndex}
                        onToggleMenu={(index) => setMenuOpenIndex((current) => (current === index ? null : index))}
                        onStartEditing={startEditing}
                        onEditContentChange={setEditContent}
                        onCancelEditing={() => setEditingIndex(null)}
                        onSaveEdit={saveEdit}
                        onRegenerate={(index) => { void regenerateMessage(index); }}
                        onDelete={(index) => { void deleteMessage(index); }}
                        onThoughtExpandedChange={setThoughtExpandedState}
                        onOpenContext={(payload, meta) => {
                            setContextModalData({ payload, meta });
                            setContextMetaOpen(false);
                            setContextViewMode("rendered");
                            setMenuOpenIndex(null);
                        }}
                        onMessageBubbleRef={(index, element) => {
                            messageBubbleRefs.current[index] = element;
                        }}
                    />
                </div>

                {/* Input */}
                <ChatComposer
                    draftKey={activeChatId ?? "new-chat"}
                    streaming={streaming}
                    onSend={handleSend}
                />
            </div>

            {/* Toggle right sidebar */}
            <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                style={{
                    position: "absolute", right: sidebarOpen ? 320 : 0, top: "20px",
                    zIndex: 10,
                    background: "var(--card)", border: "1px solid var(--border)", borderRight: "none",
                    borderRadius: "8px 0 0 8px", padding: "8px 4px", cursor: "pointer",
                    color: "var(--text-muted)",
                }}
            >
                {sidebarOpen ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
            </button>

            {/* Retrieval Settings Sidebar */}
            {sidebarOpen && (
                <ChatSettingsSidebar
                    topK={topK}
                    entryTopK={entryTopK}
                    hops={hops}
                    maxNodes={maxNodes}
                    chatProvider={chatProvider}
                    sendThinking={sendThinking}
                    chatPrompt={chatPrompt}
                    promptSource={promptSource}
                    searchContextMsgs={searchContextMsgs}
                    chatHistoryMsgs={chatHistoryMsgs}
                    openSections={openSections}
                    onOpenSectionsChange={setOpenSections}
                    onTopKChange={(value) => {
                        setTopK(value);
                        saveRetrievalSettings({ retrieval_top_k_chunks: value });
                    }}
                    onEntryTopKChange={(value) => {
                        setEntryTopK(value);
                        saveRetrievalSettings({ retrieval_entry_top_k_nodes: value });
                    }}
                    onHopsChange={(value) => {
                        setHops(value);
                        saveRetrievalSettings({ retrieval_graph_hops: value });
                    }}
                    onMaxNodesChange={(value) => {
                        setMaxNodes(value);
                        saveRetrievalSettings({ retrieval_max_nodes: value });
                    }}
                    onSendThinkingChange={(value) => {
                        setSendThinking(value);
                        saveRetrievalSettings({ gemini_chat_send_thinking: value });
                    }}
                    onSearchContextMsgsChange={(value) => {
                        setSearchContextMsgs(value);
                        saveRetrievalSettings({ retrieval_context_messages: value });
                    }}
                    onChatHistoryMsgsChange={(value) => {
                        setChatHistoryMsgs(value);
                        saveRetrievalSettings({ chat_history_messages: value });
                    }}
                    onChatPromptChange={setChatPrompt}
                    onSaveChatPrompt={() => { void saveChatPrompt(); }}
                    onResetChatPrompt={() => { void resetChatPrompt(); }}
                />
            )}
            {/* Context Modal */}
            {contextModalData && (
                <div style={{ position: "fixed", inset: 0, zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: 24, background: "var(--overlay-strong)" }} onClick={() => { setContextModalData(null); setContextMetaOpen(false); setContextViewMode("rendered"); }}>
                    <div style={{ width: "100%", maxWidth: contextViewMode === "graph" ? 1280 : 900, height: contextViewMode === "graph" ? "90vh" : "auto", maxHeight: "90vh", background: "var(--card)", borderRadius: "var(--radius)", border: "1px solid var(--border)", display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }} onClick={e => e.stopPropagation()}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
                            <h2 style={{ fontSize: 16, fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
                                <Info size={18} style={{ color: "var(--primary)" }} /> Exact Model Context
                            </h2>
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                                <button onClick={() => setContextViewMode("rendered")} style={{ display: "flex", alignItems: "center", gap: 6, background: contextViewMode === "rendered" ? "var(--primary)" : "var(--background)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontSize: 12, color: contextViewMode === "rendered" ? "white" : "var(--text-primary)" }}>
                                    Rendered
                                </button>
                                <button
                                    onClick={() => {
                                        if (modalContextGraph) {
                                            setContextViewMode("graph");
                                        }
                                    }}
                                    disabled={!modalContextGraph}
                                    title={modalContextGraph ? "View exact sent-context graph" : "Available for new messages only"}
                                    style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: 6,
                                        background: contextViewMode === "graph" ? "var(--primary)" : "var(--background)",
                                        border: "1px solid var(--border)",
                                        borderRadius: 6,
                                        padding: "6px 12px",
                                        cursor: modalContextGraph ? "pointer" : "not-allowed",
                                        fontSize: 12,
                                        color: contextViewMode === "graph" ? "white" : "var(--text-primary)",
                                        opacity: modalContextGraph ? 1 : 0.55,
                                    }}
                                >
                                    Context Graph
                                </button>
                                <button onClick={() => setContextViewMode("json")} style={{ display: "flex", alignItems: "center", gap: 6, background: contextViewMode === "json" ? "var(--primary)" : "var(--background)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontSize: 12, color: contextViewMode === "json" ? "white" : "var(--text-primary)" }}>
                                    Exact JSON
                                </button>
                                {!modalContextGraph && (
                                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                        Graph view available for new messages only
                                    </span>
                                )}
                                {modalMeta && (
                                    <button onClick={() => setContextMetaOpen((prev) => !prev)} style={{ display: "flex", alignItems: "center", gap: 6, background: "var(--background)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontSize: 12, color: "var(--text-primary)" }}>
                                        <Info size={14} /> i
                                    </button>
                                )}
                                <button onClick={() => {
                                    const copyText = getContextCopyText(modalPayload);
                                    navigator.clipboard.writeText(copyText); 
                                    alert("Copied!"); 
                                }} style={{ display: "flex", alignItems: "center", gap: 6, background: "var(--background)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontSize: 12, color: "var(--text-primary)" }}>
                                    <Check size={14} /> Copy
                                </button>
                                <button onClick={() => { setContextModalData(null); setContextMetaOpen(false); setContextViewMode("rendered"); }} style={{ background: "none", border: "none", color: "var(--text-subtle)", cursor: "pointer", padding: 4 }}>
                                    <X size={18} />
                                </button>
                            </div>
                        </div>
                        <div style={{ flex: 1, minHeight: 0, display: contextViewMode === "graph" ? "flex" : "block", overflow: contextViewMode === "graph" ? "hidden" : "auto", padding: contextViewMode === "graph" ? 0 : 20 }}>
                            {contextViewMode === "graph" ? (
                                modalContextGraph ? (
                                    <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: "flex" }}>
                                        <InteractiveGraphViewer
                                            nodes={modalContextGraph.nodes}
                                            edges={modalContextGraph.edges}
                                            useEntryRoleColors
                                            resolveNodeDetail={(node) => {
                                                const detailNode = modalContextGraph.nodes.find((candidate) => candidate.id === node.id);
                                                if (!detailNode) return null;
                                                return {
                                                    id: detailNode.id,
                                                    display_name: detailNode.label,
                                                    description: detailNode.description,
                                                    is_entry_node: detailNode.is_entry_node,
                                                    connection_count: detailNode.connection_count,
                                                    claims: detailNode.claims || [],
                                                    neighbors: detailNode.neighbors || [],
                                                } as GraphViewerNodeDetail;
                                            }}
                                            emptyStateTitle="No context graph captured."
                                            emptyStateSubtitle="This message did not store a context-graph snapshot."
                                            panelPlaceholderTitle="Click a context node to inspect"
                                            panelPlaceholderSubtitle="This graph only shows what was sent in this message's context"
                                        />
                                    </div>
                                ) : (
                                    <div style={{ padding: 20, color: "var(--text-muted)", fontSize: 13 }}>
                                        Context graph available for new messages only.
                                    </div>
                                )
                            ) : contextViewMode === "json" ? (
                                <pre style={{ margin: 0, fontFamily: "monospace", fontSize: 13, color: "var(--text-primary)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                                    {getContextCopyText(modalPayload)}
                                </pre>
                            ) : (
                                renderHumanContextPayload(modalPayload)
                            )}
                        </div>
                        {contextMetaOpen && modalMeta && (
                            <div style={{ position: "absolute", right: 16, top: 70, width: 300, pointerEvents: "none", zIndex: 2 }}>
                                <div style={{ background: "var(--background)", border: "1px solid var(--border)", borderRadius: 8, boxShadow: "0 8px 18px rgba(0,0,0,0.22)", padding: 12 }}>
                                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-subtle)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                                        Context Metadata
                                    </div>
                                    <pre style={{ margin: 0, fontFamily: "monospace", fontSize: 12, color: "var(--text-primary)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                                        {JSON.stringify(modalMeta, null, 2)}
                                    </pre>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

function SliderField({ label, value, min, max, onChange }: {
    label: string; value: number; min: number; max: number; onChange: (v: number) => void;
}) {
    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                <span style={{ fontSize: 13, color: "var(--text-subtle)", display: "flex", alignItems: "center" }}>{label}</span>
                <input 
                    type="number"
                    value={value || 0}
                    onChange={(e) => onChange(Number(e.target.value))}
                    style={{ width: 60, fontSize: 13, fontWeight: 600, color: "var(--primary-light)", background: "var(--background)", border: "1px solid var(--border)", borderRadius: 4, textAlign: "right", padding: "2px 4px", fontFamily: "inherit" }}
                />
            </div>
            <input
                type="range"
                min={min}
                max={Math.max(max, value || 0)}
                value={value || 0}
                onChange={(e) => onChange(Number(e.target.value))}
                style={{ width: "100%", accentColor: "var(--primary)" }}
            />
        </div>
    );
}

function ActionMenuItem({ icon, label, onClick, danger }: { icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean }) {
    const [hover, setHover] = useState(false);
    return (
        <button
            onClick={onClick}
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
            style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 10px", background: hover ? "var(--background)" : "transparent",
                border: "none", borderRadius: 4, cursor: "pointer",
                color: danger ? "#ef4444" : "var(--text-primary)",
                fontSize: 13, textAlign: "left", transition: "background 0.1s"
            }}
        >
            {icon} {label}
        </button>
    );
}
