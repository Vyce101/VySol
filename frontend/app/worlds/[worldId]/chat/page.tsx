"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable react-hooks/set-state-in-effect */

import { Children, cloneElement, isValidElement, useState, useEffect, useRef, use, useMemo } from "react";
import { Send, Loader2, ChevronRight, ChevronLeft, AlertTriangle, Trash2, Info, MessageSquare, Plus, MoreVertical, Edit2, RefreshCw, X, Check } from "lucide-react";
import { ApiError, apiFetch, apiStreamPost } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import InteractiveGraphViewer, {
    GraphViewerNode,
    GraphViewerLink,
    GraphViewerNodeDetail,
} from "@/components/interactive-graph-viewer";

interface Message {
    role: "user" | "model";
    content: string;
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

function getSystemInstructionFromPayload(payload: any): string {
    if (payload && typeof payload.system_instruction === "string") {
        return payload.system_instruction;
    }
    if (payload && Array.isArray(payload.messages)) {
        const systemMessage = payload.messages.find((message: any) => message?.role === "system");
        if (systemMessage && typeof systemMessage.content === "string") {
            return systemMessage.content;
        }
    }
    return "";
}

function parseContextGraphFromPayload(payload: any): ContextGraphSnapshot | null {
    const systemInstruction = getSystemInstructionFromPayload(payload);
    if (!systemInstruction) return null;

    const extractSection = (heading: string, nextHeadings: string[]) => {
        const escapedHeading = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const nextPattern = nextHeadings
            .map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
            .join("|");
        const regex = new RegExp(`${escapedHeading}\\n([\\s\\S]*?)(?=\\n(?:${nextPattern})|$)`);
        const match = systemInstruction.match(regex);
        return match?.[1]?.trim() || "";
    };

    const entryNodesSection = extractSection("# Entry Nodes", ["# Graph Nodes", "# Graph Edges", "# RAG Chunks", "# Chat History"]);
    const graphNodesSection = extractSection("# Graph Nodes", ["# Graph Edges", "# RAG Chunks", "# Chat History"]);
    const graphEdgesSection = extractSection("# Graph Edges", ["# RAG Chunks", "# Chat History"]);

    const nodeMap = new Map<string, { id: string; label: string; description: string; connection_count: number; neighbors: Array<{ id: string; label: string; description: string }> }>();
    const ensureNode = (name: string, description = "") => {
        const trimmedName = name.trim();
        if (!trimmedName) return null;
        const existing = nodeMap.get(trimmedName);
        if (existing) {
            if (description && !existing.description.includes(description)) {
                existing.description = existing.description ? `${existing.description} ${description}` : description;
            }
            return existing;
        }
        const created = {
            id: trimmedName,
            label: trimmedName,
            description: description.trim(),
            connection_count: 0,
            neighbors: [] as Array<{ id: string; label: string; description: string }>,
        };
        nodeMap.set(trimmedName, created);
        return created;
    };

    const parseNodeSection = (section: string) => {
        for (const line of section.split("\n")) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            const separatorIndex = trimmed.indexOf(":");
            if (separatorIndex === -1) continue;
            const name = trimmed.slice(0, separatorIndex).trim();
            const description = trimmed.slice(separatorIndex + 1).trim();
            ensureNode(name, description);
        }
    };

    parseNodeSection(entryNodesSection);
    parseNodeSection(graphNodesSection);

    const edges: GraphViewerLink[] = [];
    for (const line of graphEdgesSection.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        const temporalMatch = trimmed.match(/^\[B(\d+):C(\d+)\]\s*(.*)$/);
        const edgeBody = temporalMatch ? temporalMatch[3].trim() : trimmed;
        const firstComma = edgeBody.indexOf(",");
        const lastComma = edgeBody.lastIndexOf(",");
        if (firstComma === -1 || lastComma === -1 || lastComma <= firstComma) {
            continue;
        }

        const sourceName = edgeBody.slice(0, firstComma).trim();
        const description = edgeBody.slice(firstComma + 1, lastComma).trim();
        const targetName = edgeBody.slice(lastComma + 1).trim();
        if (!sourceName || !targetName) continue;

        ensureNode(sourceName);
        ensureNode(targetName);

        edges.push({
            source: sourceName,
            target: targetName,
            description,
            strength: 1,
            source_book: temporalMatch ? Number(temporalMatch[1]) : undefined,
            source_chunk: temporalMatch ? Number(temporalMatch[2]) : undefined,
        });
    }

    if (nodeMap.size === 0 && edges.length === 0) {
        return null;
    }

    const neighborMap = new Map<string, Map<string, string>>();
    for (const edge of edges) {
        const sourceName = edge.source;
        const targetName = edge.target;
        const description = edge.description || "";

        if (!neighborMap.has(sourceName)) neighborMap.set(sourceName, new Map());
        if (!neighborMap.has(targetName)) neighborMap.set(targetName, new Map());

        if (!neighborMap.get(sourceName)?.has(targetName)) {
            neighborMap.get(sourceName)?.set(targetName, description);
        }
        if (!neighborMap.get(targetName)?.has(sourceName)) {
            neighborMap.get(targetName)?.set(sourceName, description);
        }
    }

    const nodes = Array.from(nodeMap.values())
        .sort((a, b) => a.label.localeCompare(b.label))
        .map((node) => {
            const neighbors = Array.from(neighborMap.get(node.id)?.entries() || [])
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([neighborName, description]) => ({
                    id: neighborName,
                    label: neighborName,
                    description,
                }));
            return {
                ...node,
                connection_count: neighbors.length,
                neighbors,
            };
        });

    return {
        schema_version: "context_graph.fallback.v1",
        nodes,
        edges,
    };
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
};

function ChatMessageMarkdown({ content }: { content: string }) {
    return <ReactMarkdown components={markdownComponents}>{content.replace(/\n/g, "  \n")}</ReactMarkdown>;
}

export default function ChatPage({ params }: { params: Promise<{ worldId: string }> }) {
    const { worldId } = use(params);
    const [threads, setThreads] = useState<ChatThread[]>([]);
    const [activeChatId, setActiveChatId] = useState<string | null>(null);
    const [messages, setMessages] = useState<Message[]>([]);
    const [chatVersion, setChatVersion] = useState<number | null>(null);
    const [input, setInput] = useState("");
    const [streaming, setStreaming] = useState(false);
    
    // UI Layout states
    const [threadsOpen, setThreadsOpen] = useState(true);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [incomplete, setIncomplete] = useState(false);
    
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const isAutoScrollEnabled = useRef(true);

    // Retrieval settings
    const [topK, setTopK] = useState(5);
    const [entryTopK, setEntryTopK] = useState(5);
    const [hops, setHops] = useState(2);
    const [maxNodes, setMaxNodes] = useState(50);
    const [chatPrompt, setChatPrompt] = useState("");
    const [promptSource, setPromptSource] = useState("default");
    const [searchContextMsgs, setSearchContextMsgs] = useState(3);
    const [chatHistoryMsgs, setChatHistoryMsgs] = useState(1000);

    // Message action states
    const [hoveredMsgIndex, setHoveredMsgIndex] = useState<number | null>(null);
    const [menuOpenIndex, setMenuOpenIndex] = useState<number | null>(null);
    const [editingIndex, setEditingIndex] = useState<number | null>(null);
    const [editContent, setEditContent] = useState("");
    const [editBubbleHeight, setEditBubbleHeight] = useState(140);
    const [contextModalData, setContextModalData] = useState<ContextModalData | null>(null);
    const [contextMetaOpen, setContextMetaOpen] = useState(false);
    const [contextViewMode, setContextViewMode] = useState<"rendered" | "graph" | "json">("rendered");

    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const messageBubbleRefs = useRef<Record<number, HTMLDivElement | null>>({});

    const mapMessage = (m: any): Message => ({
        ...m,
        messageId: m.messageId || m.message_id,
        status: m.status || "complete",
        nodesUsed: m.nodesUsed || m.nodes_used,
        contextPayload: m.contextPayload || m.context_payload,
        contextMeta: m.contextMeta || m.context_meta,
    });

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
            if (data.retrieval_context_messages !== undefined) setSearchContextMsgs(data.retrieval_context_messages);
            if (data.chat_history_messages !== undefined) setChatHistoryMsgs(data.chat_history_messages);
        } catch { /* ignore */ }
    };

    useEffect(() => {
        if (isAutoScrollEnabled.current) {
            messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
        }
    }, [messages]);

    useEffect(() => {
        if (!contextModalData) {
            setContextMetaOpen(false);
            setContextViewMode("rendered");
        }
    }, [contextModalData]);

    const handleScroll = () => {
        if (!scrollContainerRef.current) return;
        const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current;
        const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
        isAutoScrollEnabled.current = isNearBottom;
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
            if (deduped.length > 0 && !activeChatId) {
                setActiveChatId(deduped[0].id);
            }
        } catch { /* ignore */ }
    }

    async function loadChatDetails(chatId: string) {
        try {
            const data = await apiFetch<ChatDetailResponse>(`/worlds/${worldId}/chats/${chatId}`);
            const mapped = (data.messages || []).map(mapMessage);
            setMessages(mapped);
            setChatVersion(data.version ?? 0);
        } catch { /* ignore */ }
    }

    useEffect(() => {
        checkIngestionStatus();
        loadChatPrompt();
        loadThreads();
        loadRetrievalSettings();
    }, [worldId]);

    useEffect(() => {
        if (activeChatId) {
            loadChatDetails(activeChatId);
        } else {
            setMessages([]);
            setChatVersion(null);
        }
    }, [activeChatId, worldId]);

    const createNewChat = async () => {
        try {
            const data = await apiFetch<{ id: string; version?: number }>(`/worlds/${worldId}/chats`, {
                method: "POST", 
                body: JSON.stringify({ title: "New Chat" }) 
            });
            setActiveChatId(data.id);
            setMessages([]);
            setChatVersion(data.version ?? null);
            loadThreads();
        } catch { /* ignore */ }
    }

    const deleteChat = async (chatId: string) => {
        if (!confirm("Delete this chat?")) return;
        try {
            await apiFetch(`/worlds/${worldId}/chats/${chatId}`, { method: "DELETE" });
            if (activeChatId === chatId) {
                setActiveChatId(null);
            }
            loadThreads();
        } catch { /* ignore */ }
    };

    const saveRetrievalSettings = (updates: Record<string, unknown>) => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
            apiFetch("/settings", { method: "POST", body: JSON.stringify(updates) }).catch(() => { });
        }, 500);
    };

    const saveChatHistory = async (chatId: string, newMessages: Message[]) => {
        try {
            const data = await apiFetch<{ version?: number; messages?: any[] }>(`/worlds/${worldId}/chats/${chatId}/history`, {
                method: "PUT",
                body: JSON.stringify({
                    messages: newMessages.map((message) => ({
                        role: message.role,
                        content: message.content,
                        message_id: message.messageId,
                        status: message.status || "complete",
                        nodes_used: message.nodesUsed,
                        context_payload: message.contextPayload,
                        context_meta: message.contextMeta,
                    })),
                    base_version: chatVersion ?? 0,
                })
            });
            setChatVersion(data.version ?? chatVersion);
            if (data.messages) {
                setMessages(data.messages.map(mapMessage));
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

    const handleSend = async (customInput?: string, customHistory?: Message[]) => {
        const textToSend = customInput ?? input;
        if (!textToSend.trim() || streaming) return;

        let currentChatId = activeChatId;

        if (!currentChatId) {
            try {
                const title = textToSend.slice(0, 30) + (textToSend.length > 30 ? "..." : "");
                const data = await apiFetch<{ id: string; version?: number }>(`/worlds/${worldId}/chats`, {
                    method: "POST", 
                    body: JSON.stringify({ title }) 
                });
                currentChatId = data.id;
                setActiveChatId(currentChatId);
                setChatVersion(data.version ?? null);
                await loadThreads();
            } catch {
                alert("Failed to create chat");
                return;
            }
        }

        const userMsg: Message = { role: "user", content: textToSend, status: "complete" };
        const historyToUse = customHistory || messages;
        const newHistory = [...historyToUse, userMsg];
        const optimisticReply: Message = { role: "model", content: "", status: "streaming" };
        
        setMessages([...newHistory, optimisticReply]);
        if (customInput === undefined) setInput("");
        setStreaming(true);

        let accum = "";
        let nodesUsed: Message["nodesUsed"] = [];
        let contextPayload: any = null;
        let contextMeta: any = null;
        let persistedMessageId: string | undefined;
        let persistedVersion: number | null = null;

        await apiStreamPost(
            `/worlds/${worldId}/chats/${currentChatId}/message`,
            {
                message: userMsg.content,
                settings_override: {
                    retrieval_top_k_chunks: topK,
                    retrieval_entry_top_k_nodes: entryTopK,
                    retrieval_graph_hops: hops,
                    retrieval_max_nodes: maxNodes,
                    retrieval_context_messages: searchContextMsgs,
                    chat_history_messages: chatHistoryMsgs,
                },
            },
            (data) => {
                if (data.token) {
                    accum += data.token as string;
                    setMessages((prev) => {
                        const updated = [...prev];
                        updated[updated.length - 1] = {
                            ...updated[updated.length - 1],
                            role: "model",
                            content: accum,
                            status: "streaming",
                        };
                        return updated;
                    });
                }
                if (data.event === "done") {
                    if (typeof data.message_id === "string") persistedMessageId = data.message_id;
                    if (typeof data.chat_version === "number") persistedVersion = data.chat_version;
                    if (data.nodes_used) nodesUsed = data.nodes_used as Message["nodesUsed"];
                    if (data.context_payload) contextPayload = data.context_payload;
                    if (data.context_meta) contextMeta = data.context_meta;
                    if (typeof data.chat_version === "number") {
                        setChatVersion(data.chat_version);
                    }
                }
            },
            () => {
                setMessages((prev) => {
                    const updated = [...prev];
                    updated[updated.length - 1] = {
                        ...updated[updated.length - 1],
                        role: "model",
                        content: accum,
                        messageId: persistedMessageId,
                        status: "complete",
                        nodesUsed,
                        contextPayload,
                        contextMeta,
                    };
                    return updated;
                });
                if (persistedVersion !== null) {
                    setChatVersion(persistedVersion);
                }
                setStreaming(false);
                loadThreads(); // Refresh thread list to update timestamp/names
            },
            (err) => {
                setStreaming(false);
                void loadThreads();
                if (currentChatId) {
                    void loadChatDetails(currentChatId);
                }
                alert(err.message.includes("fully saved")
                    ? "The reply was interrupted before it finished saving. The partial reply was preserved as incomplete."
                    : err.message);
            }
        );
    }

    const deleteMessage = async (index: number) => {
        if (!confirm("Are you sure you want to delete this message?")) return;
        const newMessages = [...messages];
        newMessages.splice(index, 1);
        setMessages(newMessages);
        setMenuOpenIndex(null);
        if (activeChatId) {
            await saveChatHistory(activeChatId, newMessages);
        }
    };

    const startEditing = (index: number) => {
        const bubbleEl = messageBubbleRefs.current[index];
        const measuredHeight = bubbleEl ? Math.ceil(bubbleEl.getBoundingClientRect().height) : 140;
        setEditBubbleHeight(Math.max(90, measuredHeight));
        setEditingIndex(index);
        setEditContent(messages[index].content);
        setMenuOpenIndex(null);
    };

    const saveEdit = async (index: number) => {
        const newMessages = [...messages];
        newMessages[index].content = editContent;
        setMessages(newMessages);
        setEditingIndex(null);
        if (activeChatId) {
            await saveChatHistory(activeChatId, newMessages);
        }
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
        
        setMessages(newMessages);
        setMenuOpenIndex(null);
        if (activeChatId) {
            const saved = await saveChatHistory(activeChatId, newMessages);
            if (!saved) {
                return;
            }
        }
        handleSend(promptToResend, newMessages);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            handleSend();
        }
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
        () => getContextGraphSnapshot(modalMeta) || parseContextGraphFromPayload(modalPayload),
        [modalMeta, modalPayload]
    );

    return (
        <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
            
            {/* Left Sidebar - Chat Threads */}
            {threadsOpen && (
                <div style={{ width: 280, borderRight: "1px solid var(--border)", background: "var(--background)", display: "flex", flexDirection: "column", flexShrink: 0 }}>
                    <div style={{ padding: "16px", borderBottom: "1px solid var(--border)" }}>
                        <button onClick={createNewChat} style={{ 
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
                                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13, fontWeight: t.id === activeChatId ? 500 : 400, color: t.id === activeChatId ? "var(--primary-light)" : "var(--text-primary)" }}>
                                        {t.title}
                                    </div>
                                </div>
                                <button onClick={(e) => { e.stopPropagation(); deleteChat(t.id); }} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 4, visibility: t.id === activeChatId ? "visible" : "hidden" }}>
                                    <Trash2 size={13} />
                                </button>
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
                    {messages.length === 0 && (
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)" }}>
                            <div style={{ fontSize: 48, marginBottom: 12, opacity: 0.3 }}>💬</div>
                            <p>Ask a question about your world</p>
                            <p style={{ fontSize: 13 }}>Press Ctrl+Enter to send</p>
                        </div>
                    )}

                    {messages.map((msg, i) => (
                        <div 
                            key={msg.messageId || i}
                            style={{
                                display: "flex",
                                width: "100%",
                                marginBottom: 16,
                                position: "relative",
                                padding: "0 20px"
                            }}
                            onMouseEnter={() => setHoveredMsgIndex(i)}
                            onMouseLeave={() => setHoveredMsgIndex(null)}
                        >
                            <div style={{
                                width: "100%",
                                maxWidth: "100%",
                                display: "flex", 
                                flexDirection: msg.role === "user" ? "row-reverse" : "row",
                                alignItems: "flex-start",
                                gap: 0
                            }}>
                                {editingIndex === i ? (
                                    <div style={{
                                        position: "relative",
                                        padding: "16px 40px",
                                        borderRadius: "var(--radius)",
                                        background: msg.role === "user" ? "var(--primary)" : "var(--card)",
                                        border: msg.role === "model" ? "1px solid var(--border)" : "none",
                                        color: msg.role === "user" ? "white" : "var(--text-primary)",
                                        fontSize: 14,
                                        lineHeight: 1.6,
                                        width: "100%",
                                        height: editBubbleHeight,
                                    }}>
                                        <textarea 
                                            value={editContent} 
                                            onChange={e => setEditContent(e.target.value)} 
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
                                            <button onClick={() => setEditingIndex(null)} style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 8px", background: "transparent", border: "1px solid var(--border)", borderRadius: 4, color: "var(--text-subtle)", cursor: "pointer", fontSize: 12 }}>
                                                <X size={12} /> Cancel
                                            </button>
                                            <button onClick={() => saveEdit(i)} style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 8px", background: "var(--primary)", border: "none", borderRadius: 4, color: "var(--primary-contrast)", cursor: "pointer", fontSize: 12 }}>
                                                <Check size={12} /> Save
                                            </button>
                                        </div>
                                    </div>
                                ) : (
                                    <div style={{
                                        position: "relative",
                                        padding: "16px 40px",
                                        borderRadius: "var(--radius)",
                                        background: msg.role === "user" ? "var(--primary)" : "var(--card)",
                                        border: msg.role === "model" ? "1px solid var(--border)" : "none",
                                        color: msg.role === "user" ? "white" : "var(--text-primary)",
                                        fontSize: 14,
                                        lineHeight: 1.6,
                                        width: "100%"
                                    }}
                                    ref={(el) => {
                                        messageBubbleRefs.current[i] = el;
                                    }}>
                                        {/* Message Actions Menu Node */}
                                        {(hoveredMsgIndex === i || menuOpenIndex === i) && editingIndex !== i && (
                                            <div style={{ 
                                                position: "absolute",
                                                top: 12,
                                                [msg.role === "user" ? "right" : "left"]: 12,
                                                zIndex: menuOpenIndex === i ? 50 : 10
                                            }}>
                                                <button 
                                                    onClick={() => setMenuOpenIndex(menuOpenIndex === i ? null : i)}
                                                    style={{ 
                                                        background: "transparent", border: "none", color: msg.role === "user" ? "rgba(255,255,255,0.7)" : "var(--text-muted)", 
                                                        cursor: "pointer", padding: 4, borderRadius: 4,
                                                        display: "flex", alignItems: "center", justifyContent: "center"
                                                    }}
                                                    title="Message options"
                                                >
                                                    <MoreVertical size={16} />
                                                </button>

                                                {menuOpenIndex === i && (
                                                    <div style={{
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
                                                        color: "var(--text-primary)"
                                                    }}>
                                                        <ActionMenuItem icon={<Edit2 size={13} />} label="Edit" onClick={() => startEditing(i)} />
                                                        <ActionMenuItem icon={<RefreshCw size={13} />} label={msg.status === "incomplete" ? "Continue" : "Regenerate"} onClick={() => regenerateMessage(i)} />
                                                        {msg.contextPayload && (
                                                            <ActionMenuItem icon={<Info size={13} />} label="Context" onClick={() => { setContextModalData({ payload: msg.contextPayload, meta: msg.contextMeta }); setContextMetaOpen(false); setContextViewMode("rendered"); setMenuOpenIndex(null); }} />
                                                        )}
                                                        <div style={{ height: 1, background: "var(--border)", margin: "4px 0" }} />
                                                        <ActionMenuItem icon={<Trash2 size={13} />} label="Delete" onClick={() => deleteMessage(i)} danger />
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        <div
                                            style={{ overflowWrap: "break-word" }}
                                            className={`markdown-content ${msg.role === "user" ? "markdown-content-user" : "markdown-content-model"}`}
                                        >
                                            {msg.role === "user" && i === messages.length - 1 && !streaming ? (
                                                <ChatMessageMarkdown content={msg.content} />
                                            ) : msg.role === "model" || msg.role === "user" ? (
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
                                         
                                        {msg.role === "model" && (msg.status === "streaming" || (streaming && i === messages.length - 1)) && (
                                            <span style={{ display: "inline-block", width: 6, height: 16, background: "var(--primary)", marginLeft: 2, animation: "pulse-glow 1s infinite" }} />
                                        )}

                                        {msg.nodesUsed && msg.nodesUsed.length > 0 && (
                                            <details style={{ marginTop: 8, fontSize: 12, color: "var(--text-subtle)" }}>
                                                <summary style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>
                                                    <Info size={12} /> {msg.nodesUsed.length} nodes used
                                                </summary>
                                                <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
                                                    {msg.nodesUsed.map((n, j) => (
                                                        <span key={j} style={{
                                                            padding: "2px 8px", borderRadius: 9999, background: "var(--background)",
                                                            border: "1px solid var(--border)", fontSize: 11,
                                                            color: "var(--text-primary)"
                                                        }}>
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
                    ))}
                    <div ref={messagesEndRef} />
                </div>

                {/* Input */}
                <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)", background: "var(--card)" }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "flex-end", maxWidth: 900, margin: "0 auto" }}>
                        <textarea
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Ask about your world... (Ctrl+Enter to send)"
                            rows={1}
                            style={{
                                flex: 1, resize: "none", maxHeight: 150,
                                padding: "10px 14px", minHeight: 44,
                            }}
                            onInput={(e) => {
                                const el = e.target as HTMLTextAreaElement;
                                el.style.height = "auto";
                                el.style.height = Math.min(el.scrollHeight, 150) + "px";
                            }}
                        />
                        <button
                            onClick={() => handleSend()}
                            disabled={streaming || !input.trim()}
                            style={{
                                background: "var(--primary)", color: "var(--primary-contrast)", border: "none",
                                borderRadius: "var(--radius)", padding: "10px 14px", cursor: "pointer",
                                opacity: streaming || !input.trim() ? 0.5 : 1,
                                transition: "opacity 0.2s",
                            }}
                        >
                            {streaming ? <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> : <Send size={18} />}
                        </button>
                    </div>
                </div>
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
                <div style={{
                    width: 320, borderLeft: "1px solid var(--border)", background: "var(--card)",
                    overflowY: "auto", padding: 20, flexShrink: 0,
                }}>
                    <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-subtle)" }}>
                        Retrieval Settings
                    </h3>

                    <SliderField label="Top K Chunks" value={topK} min={1} max={20}
                        onChange={(v) => { setTopK(v); saveRetrievalSettings({ retrieval_top_k_chunks: v }); }} />

                    <SliderField label="Entry Nodes" value={entryTopK} min={1} max={20}
                        onChange={(v) => { setEntryTopK(v); saveRetrievalSettings({ retrieval_entry_top_k_nodes: v }); }} />

                    <SliderField label="Graph Hops" value={hops} min={0} max={5}
                        onChange={(v) => { setHops(v); saveRetrievalSettings({ retrieval_graph_hops: v }); }} />

                    <SliderField label="Max Graph Nodes" value={maxNodes} min={5} max={100}
                        onChange={(v) => { setMaxNodes(v); saveRetrievalSettings({ retrieval_max_nodes: v }); }} />

                    <SliderField label="Vector Query (Msgs)" value={searchContextMsgs} min={1} max={10}
                        onChange={(v) => { setSearchContextMsgs(v); saveRetrievalSettings({ retrieval_context_messages: v }); }} />

                    <SliderField label="Chat History Context (Msgs)" value={chatHistoryMsgs} min={1} max={20}
                        onChange={(v) => { setChatHistoryMsgs(v); saveRetrievalSettings({ chat_history_messages: v }); }} />

                    {/* Chat System Prompt */}
                    <div style={{ marginTop: 20, borderTop: "1px solid var(--border)", paddingTop: 16 }}>
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
                            onChange={(e) => setChatPrompt(e.target.value)}
                            rows={6}
                            style={{ width: "100%", resize: "vertical", fontSize: 12, minHeight: 100 }}
                        />
                        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                            <button onClick={saveChatPrompt} style={{ flex: 1, padding: "6px 12px", background: "var(--primary)", color: "var(--primary-contrast)", border: "none", borderRadius: "var(--radius)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                                Save
                            </button>
                            <button onClick={resetChatPrompt} style={{ flex: 1, padding: "6px 12px", background: "var(--border)", color: "var(--text-subtle)", border: "none", borderRadius: "var(--radius)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                                Reset
                            </button>
                        </div>
                    </div>
                </div>
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
                                            resolveNodeDetail={(node) => {
                                                const detailNode = modalContextGraph.nodes.find((candidate) => candidate.id === node.id);
                                                if (!detailNode) return null;
                                                return {
                                                    id: detailNode.id,
                                                    display_name: detailNode.label,
                                                    description: detailNode.description,
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
